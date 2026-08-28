#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score stage 1 - the sentence -> intent JSON step - against the gold intents.

compare_models.py measures stage 2 and hands it the gold intent read from a
file, so stage 1 has never been measured at all. In the pipeline as it is
normally run (--sql composer) that is the wrong half: the composer expresses
138 of the 144 cases, so for all but a handful of questions the answer is
decided by whether stage 1 read the sentence correctly, and the model that
writes SQL is never asked.

Three things are reported, because an intent can be wrong without the answer
being wrong:

    intent   does the JSON equal the gold intent, field by field
    sql      does the composer build the same query from it - a field the
             composer ignores can differ without costing anything
    rows     do the two queries return the same rows, which is the only
             end-to-end number here

The third is the one to read. The first says where to look when it is bad.

    python eval_stage1.py
    python eval_stage1.py --model llama3.1:8b --out eval_llama.jsonl
    python eval_stage1.py --filter 12_ --no-db

Writes one JSON record per case to --out and a summary beside it.
"""

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))
# OllamaClient lives in the sibling AI_agents repo, not this one. Done here
# rather than left to sentence_to_sql's copy of it, so the import below does
# not depend on which module happens to be loaded first.
sys.path.insert(0, str(AGENT_DIR.parent.parent / "AI_agents"))

from OllamaClient import OllamaClient           # noqa: E402 - after sys.path fixup
from compare_models import Db, verdict          # noqa: E402 - sibling module
from sentence_to_sql import (                   # noqa: E402
    DEFAULT_CONTEXT1,
    _extract_intent_json,
    _fill,
    compose_sql,
)

logger = logging.getLogger("eval_stage1")

PROJECT_DIR = AGENT_DIR.parent
DEFAULT_SENTENCES = PROJECT_DIR / "training" / "training_sentences"
DEFAULT_INTENTS = PROJECT_DIR / "training" / "training_intents"

#A field is right, or wrong in one of three ways worth telling apart: the model
#filled in something the sentence never said, left out something it did say, or
#read it and got it wrong. They have different fixes.
OK, INVENTED, DROPPED, WRONG = "ok", "invented", "dropped", "wrong"
FIELD_STATES = (OK, INVENTED, DROPPED, WRONG)

RIGHT = ("match", "empty2", "keys")
UNSCORED = ("no_gold", "not_run")
VERDICTS = ("match", "empty2", "keys", "differs", "empty", "big", "error") + UNSCORED


def load_cases(sentences_dir: Path, intents_dir: Path) -> list:
    """Pair each sentence with the intent stage 1 should have produced.

    Both folders are named by case, so the pairing is the file name. A sentence
    with no gold intent is skipped with a warning rather than scored against
    nothing."""
    cases = []
    for sentence_file in sorted(sentences_dir.glob("*.txt")):
        case = sentence_file.stem
        intent_file = intents_dir / f"{case}.json"
        if not intent_file.exists():
            logger.warning("no gold intent for %s, skipping", case)
            continue
        record = json.loads(intent_file.read_text())
        cases.append({
            "case": case,
            #the sentence in the .txt is what a user would type; the one inside
            #the intent file is the same text, kept there for readability
            "sentence": sentence_file.read_text().strip(),
            "gold_intent": record["intent"],
        })
    return cases


def _flatten(value, prefix: str = "") -> dict:
    """An intent as {dotted.path: leaf}, so nested shapes compare field by field.

    time_constraint and related_entity are objects, and "got the years right but
    called it the wrong type" is a different fault from "missed it entirely".
    Flattening makes each of those its own field instead of one all-or-nothing
    comparison. A None stays a leaf: "no occupation filter" is an answer."""
    if isinstance(value, dict):
        out = {}
        for key, sub in value.items():
            out.update(_flatten(sub, f"{prefix}.{key}" if prefix else key))
        return out
    #a list is compared whole - entities is ordered and partial credit for
    #getting one of three names would flatter the model
    return {prefix: value}


def _norm(value):
    """Strings compared without surrounding space; everything else as it is."""
    return value.strip() if isinstance(value, str) else value


def compare_intents(gold: dict, got) -> dict:
    """Field-by-field comparison of one intent against the gold one."""
    if not isinstance(got, dict):
        return {"parsed": False, "exact": False, "fields": {}, "wrong_fields": []}

    flat_gold, flat_got = _flatten(gold), _flatten(got)
    fields, wrong = {}, []
    for path in sorted(set(flat_gold) | set(flat_got)):
        a, b = _norm(flat_gold.get(path)), _norm(flat_got.get(path))
        if a == b:
            state = OK
        elif a is None:
            state = INVENTED
        elif b is None:
            state = DROPPED
        else:
            state = WRONG
        fields[path] = state
        if state != OK:
            wrong.append({"field": path, "state": state, "gold": a, "got": b,
                          #a value that differs only by case is a normalisation
                          #problem, not a reading-comprehension one
                          "case_only": isinstance(a, str) and isinstance(b, str)
                          and a.lower() == b.lower()})
    return {"parsed": True, "exact": not wrong, "fields": fields, "wrong_fields": wrong}


def ask(client: OllamaClient, context1: str, sentence: str) -> dict:
    """One sentence through stage 1, returning the intent it produced."""
    prompt = _fill(context1, sentence=sentence)
    started = time.perf_counter()
    try:
        reply = client.chat_once(prompt)
    except Exception as e:
        logger.warning("stage 1 failed after %.1fs: %s", time.perf_counter() - started, e)
        return {"reply": None, "intent": None, "error": str(e),
                "seconds": time.perf_counter() - started}

    elapsed = time.perf_counter() - started
    try:
        intent = json.loads(_extract_intent_json(reply))
    except (json.JSONDecodeError, ValueError) as e:
        #kept apart from a wrong intent: unparseable output is a formatting
        #failure and is fixed in the prompt, not in the reading of the sentence
        logger.warning("stage 1 did not return JSON: %s", e)
        return {"reply": reply, "intent": None, "error": f"not JSON ({e})",
                "seconds": elapsed}
    return {"reply": reply, "intent": intent, "error": None, "seconds": elapsed}


def run_case(case: dict, client: OllamaClient, context1: str, db, args) -> dict:
    """One sentence, scored at all three levels."""
    answer = ask(client, context1, case["sentence"])
    detail = {
        "case": case["case"],
        "sentence": case["sentence"],
        "gold_intent": case["gold_intent"],
        "intent": answer["intent"],
        "reply": answer["reply"] if answer["intent"] is None else None,
        "error": answer["error"],
        "seconds": round(answer["seconds"], 2),
    }
    detail["comparison"] = compare_intents(case["gold_intent"], answer["intent"])

    gold_sql, gold_reason = compose_sql(json.dumps(case["gold_intent"]), args.limit)
    if answer["intent"] is None:
        got_sql, got_reason = None, "stage 1 produced no intent"
    else:
        got_sql, got_reason = compose_sql(json.dumps(answer["intent"]), args.limit)
    detail["gold_sql"], detail["sql"] = gold_sql, got_sql
    detail["compose_declined"] = got_reason
    detail["same_sql"] = bool(gold_sql and got_sql and gold_sql.strip() == got_sql.strip())

    gold_result = db.run(gold_sql) if db and gold_sql else None
    got_result = db.run(got_sql) if db and got_sql else None
    detail["verdict"] = verdict(got_result, gold_result) if db else "not_run"
    detail["gold_rows"] = gold_result["row_count"] if gold_result else None
    detail["rows"] = got_result["row_count"] if got_result else None

    logger.info("[%s] intent=%s sql=%s rows=%s (%.1fs)", case["case"],
                "exact" if detail["comparison"]["exact"] else "differs",
                "same" if detail["same_sql"] else "differs",
                detail["verdict"], detail["seconds"])
    return detail


def summarize(details: list) -> dict:
    """The three levels, plus which fields stage 1 gets wrong."""
    verdicts = Counter(d["verdict"] for d in details)
    scored = sum(verdicts[v] for v in VERDICTS if v not in UNSCORED)
    per_field = {}
    for d in details:
        for path, state in d["comparison"]["fields"].items():
            per_field.setdefault(path, Counter())[state] += 1

    latencies = [d["seconds"] for d in details if d["error"] is None]
    return {
        "cases": len(details),
        "parsed": sum(1 for d in details if d["comparison"]["parsed"]),
        "intent_exact": sum(1 for d in details if d["comparison"]["exact"]),
        "sql_same": sum(1 for d in details if d["same_sql"]),
        "sql_declined": sum(1 for d in details if d["sql"] is None),
        "verdicts": {v: verdicts.get(v, 0) for v in VERDICTS},
        "right": sum(verdicts.get(v, 0) for v in RIGHT),
        "scored": scored,
        "seconds_total": round(sum(latencies), 1),
        "per_field": {path: dict(counts) for path, counts in per_field.items()},
        "wrong_values": Counter(
            f"{w['field']} ({w['state']})"
            for d in details for w in d["comparison"]["wrong_fields"]
        ).most_common(15),
    }


def print_summary(summary: dict, title: str = "stage 1") -> None:
    n = summary["cases"]

    def pct(count):
        return f"{count:>5}  ({100.0 * count / n:>5.1f}%)" if n else f"{count:>5}"

    print("\n" + "=" * 62)
    print(f"  {title} - {n} case(s)")
    print("=" * 62)
    print(f"  {'returned parseable JSON':<34}{pct(summary['parsed'])}")
    print(f"  {'intent matches gold exactly':<34}{pct(summary['intent_exact'])}")
    print(f"  {'composes the same SQL':<34}{pct(summary['sql_same'])}")
    print(f"  {'composer declined the intent':<34}{pct(summary['sql_declined'])}")
    print("  " + "-" * 58)
    for name in VERDICTS:
        print(f"  {'verdict ' + name:<34}{summary['verdicts'][name]:>5}")
    print(f"  {'right / scored':<34}{summary['right']:>5}/{summary['scored']}")
    print("  " + "-" * 58)
    print(f"  {'seconds, all cases':<34}{summary['seconds_total']:>5}")

    print("\n  per field - how often each is right, and how it is wrong:")
    print(f"    {'field':<40}{'ok':>6}{'invented':>10}{'dropped':>9}{'wrong':>7}")
    for path, counts in sorted(summary["per_field"].items(),
                               key=lambda kv: kv[1].get(OK, 0)):
        cells = "".join(f"{counts.get(s, 0):>{w}}" for s, w in
                        zip(FIELD_STATES, (6, 10, 9, 7)))
        print(f"    {path:<40}{cells}")

    if summary["wrong_values"]:
        print("\n  most common mistakes:")
        for name, count in summary["wrong_values"]:
            print(f"    {count:>3}x {name}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stage 1 over the test sentences and score the intents it "
                    "produces against the gold ones, the SQL they compose, and the "
                    "rows that SQL returns",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sentences", default=str(DEFAULT_SENTENCES),
                        help="folder of *.txt sentences, one per case")
    parser.add_argument("--intents", default=str(DEFAULT_INTENTS),
                        help="folder of *.json gold intents, named to match the sentences")
    parser.add_argument("--context1", default=str(DEFAULT_CONTEXT1),
                        help="the stage-1 prompt template")
    parser.add_argument("--url", default="http://192.168.1.57:11434", help="Ollama server URL")
    parser.add_argument("--model", default="llama3.1:8b",
                        help="the stage-1 model. Run twice with different --out files to "
                        "compare two of them")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--filter", default=None,
                        help="only cases whose name contains this string")
    parser.add_argument("--max-cases", type=int, default=0,
                        help="stop after this many cases (0 = all of them)")
    parser.add_argument("--db", default="/home/denis/projects/wiki_data/run3/wiki.duckdb",
                        help="DuckDB file the composed queries are run against")
    parser.add_argument("--no-db", action="store_true",
                        help="skip execution: score the intent and the SQL text only, which "
                        "needs no database and takes seconds")
    parser.add_argument("--limit", type=int, default=200, help="LIMIT for composed queries")
    parser.add_argument("--sql-timeout", type=float, default=60.0)
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--out", default=None,
                        help="detail JSONL (default: eval_stage1_<timestamp>.jsonl)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    out_path = Path(args.out) if args.out else AGENT_DIR / (
        "eval_stage1_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".jsonl")

    cases = load_cases(Path(args.sentences), Path(args.intents))
    if args.filter:
        cases = [c for c in cases if args.filter in c["case"]]
    found = len(cases)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        logger.error("no cases to run from %s", args.sentences)
        return

    logger.info("%d of %d case(s), model=%s, detail -> %s",
                len(cases), found, args.model, out_path)

    db = None
    if not args.no_db:
        db = Db(args.db, args.sql_timeout, args.max_rows)
        logger.info("database %s", args.db)

    context1 = Path(args.context1).read_text()
    client = OllamaClient(args.url, args.model,
                          options={"temperature": args.temperature, "seed": args.seed})

    details = []
    with open(out_path, "w") as out:
        for case in cases:
            detail = run_case(case, client, context1, db, args)
            details.append(detail)
            out.write(json.dumps(detail) + "\n")
            out.flush()

    summary = summarize(details)
    summary.update({"model": args.model, "url": args.url, "detail_file": str(out_path),
                    "db": None if db is None else args.db, "temperature": args.temperature})
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2))
    print_summary(summary, title=f"stage 1 - {args.model}")
    logger.info("summary -> %s", summary_path)


if __name__ == "__main__":
    main()
