"""
Score the fine-tuned stage-2 model against the base model it was tuned from.

The same stage-2 prompt goes to both servers, both replies are run against the
same DuckDB file, and both result sets are compared to the query
intent_to_sql.py composes for that intent - the composed SQL is correct by
construction, so it is the reference here, exactly as it is the training target
in sentence_to_sql.py.

The comparison is by execution, not by SQL text: two queries that join in a
different order, alias differently or project an extra column are the same
answer, and a diff of the SQL says they are not. So a case counts as "match"
when the rows come back equal as a multiset, and as "keys" when only the first
column agrees - that is the entity name in nearly every composed query, so the
model found the right people/works but projected something else beside them.

Both servers speak the OpenAI chat API - llama-server natively, Ollama through
its /v1 compatibility layer - so one request path covers both, and the reply of
one is comparable to the reply of the other rather than to an artifact of two
different clients.

Requests go out one at a time. Both models sit on the same machine (and often
the same GPU), so anything concurrent would be measuring the queue rather than
the models.

A case the model was fine-tuned on measures memorization, not generalization,
and only the held-out cases say what it will do with a question it has not
seen. Hand --splits the train and eval files the tuning run was fed and every
number is reported per split as well as overall; without them the whole set is
scored together and should be read as an upper bound.

Run:
    python compare_models.py                         # 144 cases, both servers, DuckDB
    python compare_models.py --max-cases 5           # a quick end-to-end check
    python compare_models.py --filter compare_       # one family of question shapes
    python compare_models.py --cases full_20260920.jsonl   # the training log's own prompts
    python compare_models.py --no-db                 # generate and diff SQL only, no database
    python compare_models.py --splits full_20260920_train.jsonl full_20260920_eval.jsonl
    python compare_models.py --report model_compare_full.jsonl --splits ...  # rescore, no calls

Every case is written to --out as it finishes, so a run stopped halfway still
leaves the cases it did get through, with both completions in full for reading.
"""

import argparse
import hashlib
import json
import logging
import statistics
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))

# The pipeline's own helpers, so a prompt built here is the prompt production
# sends - rebuilding it separately is how the training log ended up holding
# prompts the pipeline never sent. Pulls in OllamaClient through
# sentence_to_sql, i.e. the same sibling-repo layout the pipeline needs anyway.
from sentence_to_sql import (  # noqa: E402 - after sys.path fixup
    _fill,
    _intent_text,
    _strip_sql_fence,
    compose_sql,
)

logger = logging.getLogger("compare_models")

PROJECT_DIR = AGENT_DIR.parent
DEFAULT_CASES = PROJECT_DIR / "training" / "training_intents"
DEFAULT_CONTEXT2 = AGENT_DIR / "sentence_to_sql_stage2_context.txt"
DEFAULT_SCHEMA = PROJECT_DIR / "db_model.sql"
DEFAULT_SQL_EXAMPLES = PROJECT_DIR / "queries.sql"


class Endpoint:
    """One model server: where it is, what to call the model there, and the
    running tally of what it answered."""

    def __init__(self, key: str, url: str, model: str):
        self.key = key
        self.url = url.rstrip("/")
        self.model = model

    def __str__(self) -> str:
        return f"{self.key} ({self.url}, model={self.model})"


def discover_model(url: str) -> str:
    """The model name a server will accept, asked of the server itself.

    llama-server names the model by the path of the .gguf it loaded, which is
    not something worth retyping on the command line, and it rejects a request
    naming anything else."""
    response = requests.get(url.rstrip("/") + "/v1/models", timeout=30)
    response.raise_for_status()
    models = response.json().get("data") or []
    if not models:
        raise RuntimeError(f"{url} lists no models")
    return models[0]["id"]


def ask(endpoint: Endpoint, prompt: str, args: argparse.Namespace) -> dict:
    """Send one prompt, return the reply with the SQL pulled out of it.

    A server that is down or slow must not end a run of a hundred cases, so a
    failure here is recorded as this model's answer to this case (no SQL) and
    the run continues.

    max_tokens is not optional here. llama-server generates until the context
    is full when no cap is given, and the tuned model does run away on some
    prompts - it starts a plausible query and then enumerates 'P44', 'P45',
    'P46' ... forever. Uncapped that is 27k tokens, fifteen minutes, and a
    verdict of "the server timed out" for what is really "the model did not
    stop". Capped it is twenty seconds and a truncated reply that says so."""
    body = {
        "model": endpoint.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": args.temperature,
        "seed": args.seed,
        "stream": False,
        "max_tokens": args.max_tokens,
    }
    started = time.perf_counter()
    try:
        response = requests.post(
            endpoint.url + "/v1/chat/completions", json=body, timeout=args.request_timeout
        )
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]
        completion = choice["message"]["content"]
    except Exception as e:
        elapsed = time.perf_counter() - started
        logger.warning("%s failed after %.1fs: %s", endpoint.key, elapsed, e)
        return {"completion": None, "sql": None, "error": str(e), "seconds": elapsed,
                "completion_tokens": None, "finish_reason": None}

    usage = data.get("usage") or {}
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        #kept apart from a parse failure: the SQL is unusable either way, but
        #"it never stopped" and "it wrote something wrong" are different faults
        logger.warning("%s hit the %d token cap - reply cut off, not a finished answer",
                       endpoint.key, args.max_tokens)
    return {
        "completion": completion,
        "sql": _strip_sql_fence(completion) or None,
        "error": None,
        "seconds": time.perf_counter() - started,
        "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": finish_reason,
    }


class Db:
    """The DuckDB file, opened once, read-only, with a leash on each query.

    Read-only because this only ever SELECTs, and a read-write handle takes an
    exclusive lock - a batch that runs for an hour would otherwise fail the
    moment a DuckDB CLI is open on the same file, and vice versa.

    The leash is the point: a model is free to write a query that cross-joins
    15 GB, so each statement gets --sql-timeout seconds and is then interrupted.
    Rows are fetched up to --max-rows; a query returning more is reported as
    truncated rather than compared, since a partial result set proves nothing
    either way.

    Identical SQL is executed once and remembered - the reference query is the
    same for both models, and the two often agree with each other as well."""

    def __init__(self, path: str, sql_timeout: float, max_rows: int):
        import duckdb  # imported here so --no-db works without the package

        self.connection = duckdb.connect(path, read_only=True)
        self.sql_timeout = sql_timeout
        self.max_rows = max_rows
        self.cache: dict = {}

    def run(self, sql: str) -> dict:
        key = sql.strip()
        if key in self.cache:
            return self.cache[key]

        started = time.perf_counter()
        timer = threading.Timer(self.sql_timeout, self.connection.interrupt)
        timer.start()
        try:
            cursor = self.connection.execute(sql)
            rows = cursor.fetchmany(self.max_rows + 1)
            columns = [d[0] for d in cursor.description]
            result = {
                "status": "ok",
                "error": None,
                "rows": rows[: self.max_rows],
                "columns": columns,
                "row_count": len(rows[: self.max_rows]),
                "truncated": len(rows) > self.max_rows,
                "seconds": time.perf_counter() - started,
            }
        except Exception as e:
            timed_out = "Interrupt" in type(e).__name__
            result = {
                "status": "timeout" if timed_out else "failed",
                "error": f"timed out after {self.sql_timeout:.0f}s" if timed_out else str(e),
                "rows": None,
                "columns": None,
                "row_count": None,
                "truncated": False,
                "seconds": time.perf_counter() - started,
            }
        finally:
            timer.cancel()

        self.cache[key] = result
        return result


def _normalized(rows: list) -> list:
    """Rows as comparable values: everything to text, NULL kept distinct from
    the empty string, and the row order dropped. Two queries answering the same
    question may return int vs bigint or a different row order; neither is a
    wrong answer, while NULL where a name should be is."""
    return sorted(tuple("\0NULL" if v is None else str(v) for v in row) for row in rows)


def verdict(model_result: dict, gold_result: dict) -> str:
    """How one model's rows compare to the reference query's rows.

        match    same rows, in any order
        empty2   same rows, and there were none - the reference query returns
                 nothing for a handful of these questions (the extract simply
                 has no such rows), and there a wrong query matches as easily
                 as a right one, so it is counted apart from a real match
        keys     same values in the first column, other columns differ - the
                 composed queries lead with the entity name, so this is the
                 right answer carrying different detail beside it
        differs  ran, but answered something else
        empty    ran, returned nothing, and the reference returned rows
        error    the SQL did not run at all (or was never produced)
        big      one side hit --max-rows, so the sets cannot be compared
        no_gold  the composer declined this intent, so there is nothing to
                 score against - the two models are still comparable to each
                 other on whether their SQL ran
        not_run  --no-db: nothing was executed, so nothing is scored
    """
    #no reference first: without one nothing can be scored either way, and
    #whether the SQL ran is still counted in sql_ran/sql_failed
    if gold_result is None or gold_result["status"] != "ok":
        return "no_gold"
    if model_result is None or model_result["status"] != "ok":
        return "error"
    if model_result["truncated"] or gold_result["truncated"]:
        return "big"

    model_rows, gold_rows = model_result["rows"], gold_result["rows"]
    if _normalized(model_rows) == _normalized(gold_rows):
        return "match" if gold_rows else "empty2"
    if not model_rows:
        return "empty"
    model_keys = {row[0] for row in model_rows if row}
    gold_keys = {row[0] for row in gold_rows if row}
    if model_keys and model_keys == gold_keys:
        return "keys"
    return "differs"


def load_cases(args: argparse.Namespace) -> list:
    """The test set: intent, prompt and reference SQL per case.

    A folder of stage-1 intent files is the normal source - each file is a
    named case with the sentence it came from, and the reference query is
    composed here. A JSONL training log works too: it holds the prompts that
    were actually recorded, with the reference query already in them, which is
    the set to use when the question is what the tuning data itself taught."""
    path = Path(args.cases)
    if path.is_dir():
        context2 = Path(args.context2).read_text()
        schema = Path(args.schema).read_text()
        sqlexamples = Path(args.sqlexamples).read_text()
        cases = []
        for json_file in sorted(path.glob("*.json")):
            try:
                raw = json.loads(json_file.read_text())
                intent = _intent_text(json_file)
            except json.JSONDecodeError as e:
                logger.error("skipping %s: not JSON (%s)", json_file.name, e)
                continue
            cases.append({
                "case": json_file.stem,
                "sentence": raw.get("sentence") if isinstance(raw, dict) else None,
                "intent": json.loads(intent),
                "intent_text": intent,
                "prompt": _fill(context2, answer=intent, schema=schema, examples=sqlexamples),
                "gold_sql": None,
            })
        return cases

    cases = []
    with open(path) as f:
        for number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            cases.append({
                "case": f"line_{number:03d}",
                "sentence": None,
                "intent": None,
                "intent_text": None,
                "prompt": record["prompt"],
                "gold_sql": record.get("gold_sql"),
            })
    return cases


def _record_prompt(record: dict):
    """The prompt out of one line of a split file, whichever way the tuning
    script chose to write it - a plain field, a chat message list, or one of
    the usual field names. A split file that says nothing recognizable is
    reported as unmatched rather than silently labelling nothing."""
    if isinstance(record.get("prompt"), str):
        return record["prompt"]
    messages = record.get("messages")
    if isinstance(messages, list):
        users = [m.get("content") for m in messages
                 if isinstance(m, dict) and m.get("role") == "user"]
        if users and isinstance(users[-1], str):
            return users[-1]
    for field in ("input", "text", "instruction", "question"):
        if isinstance(record.get(field), str):
            return record[field]
    return None


def case_key(intent=None, prompt: str = None) -> str:
    """What identifies a case across files: the intent it was built from.

    A split file holds prompts, an intent file holds the intent, and the prompt
    ends with the intent verbatim ("Request: {...}"), so the intent is the one
    thing both certainly share - and it survives an edit to the schema or the
    examples pasted into the prompt, which a hash of the whole prompt does not.
    Prompts that do not carry a readable intent fall back to a hash of the
    text, which still matches an unchanged prompt against itself."""
    if intent is None and prompt is not None:
        tail = prompt.rsplit("Request:", 1)[-1] if "Request:" in prompt else prompt
        try:
            intent = json.loads(tail.strip())
        except json.JSONDecodeError:
            return "prompt:" + hashlib.sha256(prompt.strip().encode()).hexdigest()
    return "intent:" + json.dumps(intent, sort_keys=True)


def load_splits(paths: list) -> dict:
    """case_key -> split name, from the files the tuning run was fed.

    The name is the tail of the file name (full_20260920_train.jsonl ->
    "train"), which is how these are named in practice and keeps the report
    readable without another flag."""
    labels = {}
    for path in paths:
        label = Path(path).stem.split("_")[-1]
        matched = 0
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                prompt = _record_prompt(json.loads(line))
                if prompt is None:
                    continue
                labels[case_key(prompt=prompt)] = label
                matched += 1
        logger.info("split %s: %d prompt(s) from %s", label, matched, path)
    return labels


def attach_splits(cases: list, labels: dict) -> None:
    """Tag each case with the split it came from, or "unsplit" when the tuning
    files do not account for it - a case in neither file was neither trained on
    nor evaluated, and lumping it in with either would misreport both."""
    for case in cases:
        #a detail record from an earlier run carries the intent but not the
        #prompt, a JSONL case the prompt but not the intent - either identifies it
        if case.get("intent") is not None:
            key = case_key(intent=case["intent"])
        elif case.get("prompt") is not None:
            key = case_key(prompt=case["prompt"])
        else:
            key = None
        case["split"] = labels.get(key, "unsplit") if key else "unsplit"


def attach_gold(cases: list, limit: int) -> None:
    """Compose the reference query for every case that did not bring one.

    Done after --filter and --max-cases have cut the list down, so a five-case
    run does not log a decline for each of the other hundred and thirty-nine."""
    for case in cases:
        if case["gold_sql"] or not case["intent_text"]:
            continue
        gold, reason = compose_sql(case["intent_text"], limit)
        case["gold_sql"] = gold
        if gold is None:
            logger.info("no reference SQL for %s: %s", case["case"], reason)


def run_case(case: dict, endpoints: list, db, args: argparse.Namespace) -> dict:
    """One prompt through both servers and both answers through the database."""
    gold_result = db.run(case["gold_sql"]) if db and case["gold_sql"] else None
    if gold_result and gold_result["status"] != "ok":
        #the reference query failing is a bug in the composer, not in a model
        logger.warning("[%s] reference SQL %s: %s", case["case"], gold_result["status"],
                       gold_result["error"])

    detail = {
        "case": case["case"],
        "split": case.get("split", "unsplit"),
        "sentence": case["sentence"],
        "intent": case["intent"],
        "prompt_chars": len(case["prompt"]),
        "gold_sql": case["gold_sql"],
        "gold_rows": gold_result["row_count"] if gold_result else None,
    }

    for endpoint in endpoints:
        answer = ask(endpoint, case["prompt"], args)
        db_result = db.run(answer["sql"]) if db and answer["sql"] else None
        answer["verdict"] = verdict(db_result, gold_result) if db else "not_run"
        answer["db_status"] = db_result["status"] if db_result else "not run"
        answer["db_error"] = db_result["error"] if db_result else None
        answer["row_count"] = db_result["row_count"] if db_result else None
        answer["columns"] = db_result["columns"] if db_result else None
        answer["sample"] = _sample(db_result)
        detail[endpoint.key] = answer

    sqls = [detail[e.key]["sql"] for e in endpoints]
    detail["same_sql"] = len(sqls) == 2 and sqls[0] is not None and sqls[0].strip() == (
        sqls[1] or "").strip()

    logger.info(
        "[%s] %s",
        case["case"],
        "  ".join(
            "%s=%s(%s rows, %.1fs)" % (
                e.key, detail[e.key]["verdict"],
                detail[e.key]["row_count"] if detail[e.key]["row_count"] is not None else "-",
                detail[e.key]["seconds"],
            )
            for e in endpoints
        ),
    )
    return detail


def _sample(db_result: dict) -> list:
    """A few rows kept with the case, so a "differs" can be read rather than
    re-run. Values are cut short - some labels are paragraphs."""
    if not db_result or db_result["status"] != "ok":
        return []
    return [
        [("" if v is None else str(v))[:120] for v in row]
        for row in db_result["rows"][:5]
    ]


VERDICTS = ("match", "empty2", "keys", "differs", "empty", "big", "error", "no_gold", "not_run")
UNSCORED = ("no_gold", "not_run")
RIGHT = ("match", "empty2", "keys")


def summarize(details: list, endpoints: list) -> dict:
    """Counts per model, plus the head-to-head that is the actual question:
    on how many cases did tuning change the answer, and in which direction."""
    summary = {"cases": len(details), "per_model": {}, "head_to_head": {}, "same_sql": 0}
    summary["same_sql"] = sum(1 for d in details if d.get("same_sql"))

    for endpoint in endpoints:
        answers = [d[endpoint.key] for d in details]
        latencies = [a["seconds"] for a in answers if a["error"] is None]
        counts = Counter(a["verdict"] for a in answers)
        summary["per_model"][endpoint.key] = {
            "model": endpoint.model,
            "url": endpoint.url,
            "replied": sum(1 for a in answers if a["sql"]),
            "sql_ran": sum(1 for a in answers if a["db_status"] == "ok"),
            "sql_failed": sum(1 for a in answers if a["db_status"] in ("failed", "timeout")),
            "returned_rows": sum(1 for a in answers if (a["row_count"] or 0) > 0),
            "verdicts": {v: counts.get(v, 0) for v in VERDICTS},
            "right": sum(counts.get(v, 0) for v in RIGHT),
            "scored": sum(counts.get(v, 0) for v in VERDICTS if v not in UNSCORED),
            "median_seconds": round(statistics.median(latencies), 2) if latencies else None,
            "median_tokens": (
                statistics.median([a["completion_tokens"] for a in answers
                                   if a["completion_tokens"]])
                if any(a["completion_tokens"] for a in answers) else None
            ),
            "top_errors": Counter(
                (a["db_error"] or "").split("\n")[0][:70]
                for a in answers if a["db_status"] in ("failed", "timeout")
            ).most_common(5),
        }

    if len(endpoints) == 2:
        a_key, b_key = endpoints[0].key, endpoints[1].key
        good = RIGHT
        scored = [d for d in details if d[a_key]["verdict"] not in UNSCORED
                  and d[b_key]["verdict"] not in UNSCORED]
        summary["head_to_head"] = {
            "scored_cases": len(scored),
            f"{a_key}_only": sum(1 for d in scored
                                 if d[a_key]["verdict"] in good and d[b_key]["verdict"] not in good),
            f"{b_key}_only": sum(1 for d in scored
                                 if d[b_key]["verdict"] in good and d[a_key]["verdict"] not in good),
            "both": sum(1 for d in scored
                        if d[a_key]["verdict"] in good and d[b_key]["verdict"] in good),
            "neither": sum(1 for d in scored
                           if d[a_key]["verdict"] not in good and d[b_key]["verdict"] not in good),
        }
    return summary


def print_summary(summary: dict, endpoints: list, title: str = "all cases") -> None:
    keys = [e.key for e in endpoints]
    width = 14

    def row(label, values):
        cells = "".join(str(v).rjust(width) for v in values)
        print(f"  {label:<24}{cells}")

    print("\n" + "=" * (26 + width * len(keys)))
    print(f"  {title} - {summary['cases']} case(s)")
    print("=" * (26 + width * len(keys)))
    row("", keys)
    per = summary["per_model"]
    row("replied with SQL", [per[k]["replied"] for k in keys])
    row("SQL ran", [per[k]["sql_ran"] for k in keys])
    row("SQL failed", [per[k]["sql_failed"] for k in keys])
    row("returned rows", [per[k]["returned_rows"] for k in keys])
    print("  " + "-" * (24 + width * len(keys)))
    for name in VERDICTS:
        row(f"verdict {name}", [per[k]["verdicts"][name] for k in keys])
    row("right / scored", [f"{per[k]['right']}/{per[k]['scored']}" for k in keys])
    print("  " + "-" * (24 + width * len(keys)))
    row("median seconds", [per[k]["median_seconds"] for k in keys])
    row("median tokens out", [per[k]["median_tokens"] for k in keys])

    h2h = summary.get("head_to_head")
    if h2h:
        print(f"\n  head to head over {h2h['scored_cases']} scored case(s) "
              f"({'/'.join(RIGHT)} counts as right):")
        for name, value in h2h.items():
            if name != "scored_cases":
                print(f"    {name:<22}{value}")
    print(f"\n  identical SQL from both models: {summary['same_sql']}")

    for key in keys:
        errors = per[key]["top_errors"]
        if errors:
            print(f"\n  {key} - most common SQL errors:")
            for message, count in errors:
                print(f"    {count:>3}x {message}")
    print()


def emit(details: list, endpoints: list, summary_path: Path, extra: dict) -> dict:
    """Print and save the scoreboard: one table per split, then all cases.

    Trained-on and held-out cases answer different questions and averaging them
    answers neither, so the split tables come first and the overall one last."""
    summary = summarize(details, endpoints)
    summary.update(extra)

    splits = sorted({d.get("split", "unsplit") for d in details})
    by_split = ({s: summarize([d for d in details if d.get("split", "unsplit") == s], endpoints)
                 for s in splits} if splits != ["unsplit"] else {})
    summary["by_split"] = by_split

    summary_path.write_text(json.dumps(summary, indent=2))
    for name, part in by_split.items():
        print_summary(part, endpoints, title=f"split: {name}")
    print_summary(summary, endpoints, title="all cases")
    logger.info("summary -> %s", summary_path)
    return summary


def load_details(path: str) -> list:
    """The per-case records of an earlier run, for rescoring it without asking
    either server anything again."""
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the same stage-2 prompts against the tuned and the base model, "
                    "execute both answers, and score each against the composed reference SQL"
    )
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES),
        help="folder of stage-1 intent *.json files (reference SQL is composed for each), "
        "or a JSONL training log written by sentence_to_sql.py (its prompts and gold_sql "
        "are used as they were recorded)",
    )
    parser.add_argument("--filter", default=None,
                        help="only cases whose name contains this string")
    parser.add_argument("--splits", nargs="*", default=[],
                        help="the JSONL files the tuning run was fed (e.g. "
                        "full_20260920_train.jsonl full_20260920_eval.jsonl). Each case is "
                        "labelled by the file its intent appears in and every number is "
                        "reported per split - held-out cases are the ones that say whether "
                        "the model learned the task or the answers")
    parser.add_argument("--report", default=None,
                        help="rescore the detail JSONL of an earlier run and exit: prints the "
                        "same tables, asks neither server nor the database anything. Use it to "
                        "apply --splits to a pass that already ran")
    parser.add_argument("--max-cases", type=int, default=0,
                        help="stop after this many cases (0 = all of them). Two model calls "
                        "plus up to three queries per case, so a full pass takes tens of minutes")
    parser.add_argument("--tuned-url", default="http://192.168.1.57:1235",
                        help="llama-server serving the fine-tuned model")
    parser.add_argument("--tuned-model", default=None,
                        help="model name to send to --tuned-url (default: ask it, which is "
                        "what llama-server wants since it names models by .gguf path)")
    parser.add_argument("--base-url", default="http://192.168.1.57:11434",
                        help="Ollama serving the untuned base model")
    parser.add_argument("--base-model", default="Qwen2.5-Coder-7B-Instruct-Q4_K_M:latest",
                        help="model name to send to --base-url")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="0 = greedy, so a rerun of a case gives the same SQL and a "
                        "difference between the two columns is the models, not sampling")
    parser.add_argument("--seed", type=int, default=42,
                        help="sampling seed sent to both servers; temperature 0 alone has not "
                        "been enough to make runs repeatable here")
    parser.add_argument("--request-timeout", type=float, default=600.0,
                        help="seconds to wait for one model reply")
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="cap on the reply, so a model that never emits end-of-text is cut "
                        "off in seconds instead of generating until the context is full. 1024 is "
                        "well clear of anything legitimate: the longest completion in the "
                        "training log is ~540 tokens and the longest correct answer seen here 299")
    parser.add_argument("--context2", default=str(DEFAULT_CONTEXT2),
                        help="stage 2 context/template file (folder cases only)")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                        help="DDL file pasted into the prompt (folder cases only)")
    parser.add_argument("--sqlexamples", default=str(DEFAULT_SQL_EXAMPLES),
                        help="SQL examples pasted into the prompt (folder cases only)")
    parser.add_argument("--limit", type=int, default=200,
                        help="row limit the composer puts on the reference query")
    parser.add_argument("--db", default="/home/denis/projects/wiki_data/run2/wiki.duckdb",
                        help="DuckDB file to execute every query against, opened read-only")
    parser.add_argument("--no-db", action="store_true",
                        help="skip execution entirely - collects and diffs the SQL only, "
                        "which is the fast way to eyeball what tuning changed")
    parser.add_argument("--sql-timeout", type=float, default=120.0,
                        help="seconds one query may run before it is interrupted")
    parser.add_argument("--max-rows", type=int, default=1000,
                        help="rows fetched per query; a query returning more is reported as "
                        "truncated instead of compared")
    parser.add_argument("--out", default=None,
                        help="JSONL file for the per-case detail, written as the run goes "
                        "(default: model_compare_<timestamp>.jsonl next to this script). "
                        "The summary is written beside it as <out>.summary.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    out_path = Path(args.out) if args.out else AGENT_DIR / (
        "model_compare_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + ".jsonl")
    labels = load_splits(args.splits) if args.splits else {}

    if args.report:
        #rescoring an existing run: the servers are not asked for the model
        #names either, since the point is that nothing is called
        endpoints = [Endpoint("tuned", args.tuned_url, args.tuned_model or "(from report)"),
                     Endpoint("base", args.base_url, args.base_model)]
        details = load_details(args.report)
        if labels:
            attach_splits(details, labels)
        unsplit = sum(1 for d in details if d.get("split", "unsplit") == "unsplit")
        if labels and unsplit:
            logger.warning("%d of %d case(s) matched no split file", unsplit, len(details))
        emit(details, endpoints,
             Path(args.report).with_suffix(".summary.json"),
             {"detail_file": args.report, "splits": args.splits})
        return

    tuned_model = args.tuned_model or discover_model(args.tuned_url)
    endpoints = [Endpoint("tuned", args.tuned_url, tuned_model),
                 Endpoint("base", args.base_url, args.base_model)]
    for endpoint in endpoints:
        logger.info("%s", endpoint)

    cases = load_cases(args)
    if args.filter:
        cases = [c for c in cases if args.filter in c["case"]]
    found = len(cases)
    if args.max_cases > 0:
        cases = cases[: args.max_cases]
    if not cases:
        logger.error("no cases to run from %s", args.cases)
        return
    attach_gold(cases, args.limit)
    if labels:
        attach_splits(cases, labels)
        unsplit = sum(1 for c in cases if c["split"] == "unsplit")
        if unsplit:
            logger.warning("%d of %d case(s) matched no split file", unsplit, len(cases))
    with_gold = sum(1 for c in cases if c["gold_sql"])
    logger.info("%d of %d case(s) from %s, %d with reference SQL, detail -> %s",
                len(cases), found, args.cases, with_gold, out_path)

    db = None
    if not args.no_db:
        try:
            db = Db(args.db, args.sql_timeout, args.max_rows)
        except Exception as e:
            #a missing duckdb package or a locked file is a reason to fall back
            #to SQL-only comparison, not to lose the model replies as well
            logger.warning("no database (%s) - comparing SQL text only", e)

    details = []
    started = time.perf_counter()
    with open(out_path, "a") as out:
        for number, case in enumerate(cases, start=1):
            logger.info("case %d/%d: %s", number, len(cases), case["case"])
            detail = run_case(case, endpoints, db, args)
            details.append(detail)
            out.write(json.dumps(detail) + "\n")
            out.flush()

    logger.info("%d case(s) in %.0fs", len(details), time.perf_counter() - started)
    emit(details, endpoints, out_path.with_suffix(".summary.json"),
         {"cases_file": str(args.cases), "db": None if db is None else args.db,
          "detail_file": str(out_path), "splits": args.splits})


if __name__ == "__main__":
    main()
