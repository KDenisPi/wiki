"""
Two-stage pipeline: a sentence goes to a model with a context (template) file
to become a structured JSON intent, then that intent becomes a DuckDB SQL
query, which is run against a local DuckDB file.

Stage 2 is intent_to_sql.py by default, not a model. Asking a 7B model for the
SQL produced queries that ran and returned rows while answering a different
question - a creator name dropped and replaced with "a.property IS NOT NULL"
(1.5M rows instead of 9), a domain filter invented against a column holding
QIDs (0 rows). Nothing raised, because the SQL was valid. The composer builds
the same query from the intent deterministically and hands anything it cannot
express back to the model, which is what --sql controls:

    composer  compose, ask the model only for shapes the composer refuses
    model     the original stage-2 prompt
    both      run each, record the composed query as the training target

Schema-agnostic - point --schema at whatever DDL/description file matches
the database you actually want SQL for; the default is just a small
placeholder so this runs out of the box.

duckdb isn't installed in every environment this repo runs in - if it's
missing, that step is logged and skipped instead of failing the run.

Run:
    python examples/sentence_to_sql.py --sentence "Total quantity ordered per product last month"
    python examples/sentence_to_sql.py --sentence "..." --schema /path/to/your_schema.txt
    python examples/sentence_to_sql.py --sentence "..." --context1 my_stage1.txt --context2 my_stage2.txt
    python examples/sentence_to_sql.py --sentence "..." --db my.duckdb

With --training-folder set, the full sentence->intent->SQL pipeline is
skipped in favor of step2_train: every *.json file in that folder (each
holding a stage-1 intent, i.e. what run_stage(stage1) would have produced)
is fed straight into stage 2 (intent -> SQL) one by one. Those files may
wrap the intent as {"sentence": ..., "intent": {...}}; the wrapper is
removed so stage 2 and the composer see what stage 1 would have emitted.
--sql means the same thing there as anywhere else, and --max-files stops
the pass early:
    python examples/sentence_to_sql.py --training-folder /path/to/intents
    python examples/sentence_to_sql.py --training-folder ... --sql both --max-files 5

Every model call's prompt and reply are logged here; OllamaClient's own
@_timed logging (via the "ollama" logger) adds elapsed time and token
counts for each call to the same log. Stage 2 (intent -> SQL) additionally
appends a (prompt, completion, execution outcome) record per run to
--training-log, meant as raw material for later fine-tuning that model.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# OllamaClient lives in the sibling AI_agents repo, not this one.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "AI_agents"))

from OllamaClient import OllamaClient  # noqa: E402 - after sys.path fixup

from intent_to_sql import Unsupported, build_sql  # noqa: E402 - sibling module

logger = logging.getLogger("examples.sentence_to_sql")

EXAMPLES_DIR = Path(__file__).resolve().parent
DEFAULT_CONTEXT1 = EXAMPLES_DIR / "sentence_to_sql_stage1_context.txt"
DEFAULT_CONTEXT2 = EXAMPLES_DIR / "sentence_to_sql_stage2_context.txt"
DEFAULT_SCHEMA = EXAMPLES_DIR / "db_model.sql"
DEFAULT_SQL_EXAMPLES = EXAMPLES_DIR / "queries.sql"



def _fill(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key.upper() + "}}", value)
    return template


def _strip_sql_fence(text: str) -> str:
    """Models sometimes wrap SQL in a ```sql ... ``` fence despite being
    asked not to - strip it so what follows is plain SQL."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_intent_json(text: str) -> str:
    """Stage 1 is asked for JSON only, but smaller models sometimes wrap it in a
    prose preamble or a ```json fence. Pull out the first complete top-level
    {...} object (brace-matched, ignoring braces inside strings) so stage 2
    receives the intent alone rather than the surrounding chatter. If no balanced
    object is found, return the text stripped - stage 2 still sees something, and
    run_stage has already logged the raw reply for inspection."""
    start = text.find("{")
    if start == -1:
        return text.strip()
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text.strip()


def _intent_text(path: Path) -> str:
    """The intent held in a training file, as stage 1 would have produced it.

    Those files are written to be read by people too, so they keep the intent
    next to the sentence it came from:

        {"sentence": "...", "intent": {"target_type": "person", ...}}

    Stage 1 emits the inner object alone. Handing the envelope on gave the
    composer nothing to dispatch on - "intent shape not covered (target_type
    None)" for every file in the folder - and fed stage 2 a prompt the pipeline
    never sends in production, which is exactly the prompt the training log is
    supposed to capture. A file that is already flat is passed through.
    """
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        raw = raw.get("intent", raw)
    return json.dumps(raw, indent=2)


def _lazy_client(url: str, model: str, options: dict):
    """A no-argument factory building one OllamaClient on first call and
    reusing it after. Stage 2 is often asked nothing at all - the composer
    answered - and constructing a client writes a session file, so it is not
    built until something actually needs it."""
    client = None

    def get() -> OllamaClient:
        nonlocal client
        if client is None:
            client = OllamaClient(url, model, options=options)
        return client

    return get


def run_stage(client: OllamaClient, stage_name: str, prompt: str) -> str:
    logger.debug("%s prompt:\n%s", stage_name, prompt)
    reply = client.chat_once(prompt)
    logger.info("%s reply:\n%s", stage_name, reply)
    return reply


def run_sql(db_path: str, sql: str) -> dict:
    """Execute `sql` against a local DuckDB file, if the duckdb package is
    installed - its absence is logged and treated as a normal, expected
    outcome here rather than an error. Returns the outcome (status/error/
    row_count) so the caller can record it alongside the training example -
    "unavailable" means the SQL was never checked, not that it's wrong."""
    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb package not installed - skipping execution of:\n%s", sql)
        return {"status": "unavailable", "error": None, "row_count": None}

    started = time.perf_counter()
    try:
        connection = duckdb.connect(db_path)
        try:
            rows = connection.execute(sql).fetchall()
            columns = [d[0] for d in connection.description]
        finally:
            connection.close()
    except Exception as e:
        logger.warning("duckdb(%s) failed in %.2fs: %s", db_path, time.perf_counter() - started, e)
        return {"status": "failed", "error": str(e), "row_count": None}

    logger.info(
        "duckdb(%s) ok in %.2fs - %d row(s), columns=%s",
        db_path, time.perf_counter() - started, len(rows), columns,
    )
    for row in rows[:10]:
        print(row)
    return {"status": "success", "error": None, "row_count": len(rows)}


def compose_sql(intent: str, limit: int):
    """Build the SQL from the intent directly, or explain why it can't be.

    Returns (sql, None) on success and (None, reason) otherwise, so the caller
    can fall back to the model with the reason in the log."""
    try:
        return build_sql(json.loads(intent), limit=limit), None
    except json.JSONDecodeError as e:
        return None, f"stage 1 did not return JSON ({e})"
    except Unsupported as e:
        return None, f"intent shape not covered ({e})"


def log_training_example(
    path: str, model: str, prompt: str, completion: str, sql: str, db_result: dict,
    gold_sql: str = None, sql_source: str = "model"
) -> None:
    """Append one stage-2 (prompt, completion) pair to a JSONL file, for use
    later as fine-tuning data for the stage-2 model. Kept separate from the
    human-readable log: one self-contained record per line, with the exact
    prompt actually sent (schema and request already filled in) so it stays
    reproducible even after the templates change, plus whether the SQL it
    produced actually ran - a cheap signal for filtering good examples from
    bad ones once DuckDB is available to check against.

    db_status only says the SQL executed without error - it says nothing
    about whether the rows it returned actually answer the sentence. That
    judgment call needs a human to look at the output, so "human_correct" is
    left null here and is meant to be hand-filled in the JSONL afterward:
    true (answered it), false (ran but wrong/empty/irrelevant), or left null
    (not reviewed yet).

    gold_sql is what intent_to_sql.py composed for the same intent, when it
    could. That one is correct by construction, so it is the training target to
    fine-tune towards and the reference to score the model's completion
    against - the eval the db_status field cannot give on its own."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt": prompt,
        "completion": completion,
        "sql": sql,
        "sql_source": sql_source,
        "gold_sql": gold_sql,
        "db_status": db_result["status"],
        "db_error": db_result["error"],
        "row_count": db_result["row_count"],
        "human_correct": None,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
    logger.info("logged stage2 training example to %s (db_status=%s)", path, db_result["status"])


def full_run(args: argparse.Namespace) -> None:
    """Run the full sentence -> intent -> SQL pipeline once for args.sentence."""
    context1 = Path(args.context1).read_text()
    context2 = Path(args.context2).read_text()
    schema = Path(args.schema).read_text()
    sqlexamples = Path(args.sqlexamples).read_text()

    options = {"temperature": args.temperature, "seed": args.seed}
    prompt1 = _fill(context1, sentence=args.sentence)
    client1 = OllamaClient(args.url, args.model1, options=options)
    intent = _extract_intent_json(run_stage(client1, "stage1", prompt1))
    logger.info("stage1 intent (extracted):\n%s", intent)

    prompt2 = _fill(context2, answer=intent, schema=schema, examples=sqlexamples)
    stage2_once(args, intent, prompt2, _lazy_client(args.url, args.model2, options))


def stage2_once(args: argparse.Namespace, intent: str, prompt2: str, get_client,
                label: str = "") -> None:
    """Turn one intent into SQL, run it, and record the training example.

    What --sql selects:
        composer  compose from the intent; ask the model only for the shapes
                  the composer refuses
        model     ask the model, and nothing else
        both      compose and ask, run each, and record the composed query as
                  the training target beside the model's attempt

    The composer is the default because a filter it is handed cannot go
    missing, while the model has repeatedly returned SQL that ran, looked
    plausible and answered a different question.

    Shared by full_run and step2_train so a training record always holds the
    prompt the pipeline really sends - a record built from some other prompt is
    worse than no record, since fine-tuning on it teaches the wrong input.
    """
    gold, reason = (None, "not requested")
    if args.sql in ("composer", "both"):
        gold, reason = compose_sql(intent, args.limit)
        if gold is None:
            logger.info("%scomposer declined, using the model: %s", label, reason)

    completion, sql, source = None, gold, "composer"

    if gold is None or args.sql in ("model", "both"):
        completion = run_stage(get_client(), "stage2", prompt2)
        if gold is None:
            sql, source = _strip_sql_fence(completion), "model"

    logger.info("%sSQL (%s):\n%s", label, source, sql)
    db_result = run_sql(args.db, sql)

    if completion is not None:
        #only the model's own SQL belongs in the training log as a completion
        model_sql = _strip_sql_fence(completion)
        model_result = db_result if source == "model" else run_sql(args.db, model_sql)
        log_training_example(args.training_log, args.model2, prompt2, completion,
                             model_sql, model_result, gold_sql=gold, sql_source=source)


def step2_train(args: argparse.Namespace) -> None:
    """Run stage 2 (intent -> SQL) alone against the intent JSON files in
    args.training_folder, one by one, logging each to the same JSONL training
    log full_run() writes to - skips stage 1 entirely since each file already
    holds the intent stage 1 would have produced.

    --sql applies here as it does anywhere else, and --max-files cuts the pass
    short: a full folder is one model call per file, so a mistake in the
    prompts is cheaper to find over the first few than over all of them."""
    context2 = Path(args.context2).read_text()
    schema = Path(args.schema).read_text()
    sqlexamples = Path(args.sqlexamples).read_text()
    options = {"temperature": args.temperature, "seed": args.seed}
    get_client = _lazy_client(args.url, args.model2, options)

    training_dir = Path(args.training_folder)
    json_files = sorted(training_dir.glob("*.json"))
    if not json_files:
        logger.warning("no *.json files found in training folder %s", training_dir)
        return

    found = len(json_files)
    if args.max_files > 0:
        json_files = json_files[: args.max_files]
    logger.info("step2_train: %d of %d file(s) in %s, sql=%s",
                len(json_files), found, training_dir, args.sql)

    for json_file in json_files:
        logger.info("step2_train: %s", json_file.name)
        try:
            intent = _intent_text(json_file)
        except json.JSONDecodeError as e:
            #one unparseable file must not end a run of a hundred others
            logger.error("skipping %s: not JSON (%s)", json_file.name, e)
            continue

        prompt2 = _fill(context2, answer=intent, schema=schema, examples=sqlexamples)
        stage2_once(args, intent, prompt2, get_client, label=f"[{json_file.name}] ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentence -> intent -> SQL, two-stage Ollama pipeline, run against local DuckDB"
    )
    parser.add_argument(
        "--sentence",
        default="Invention in mathematics in 18 century in Germany",
        help="natural-language question to turn into SQL",
    )
    parser.add_argument("--context1", default=str(DEFAULT_CONTEXT1), help="stage 1 context/template file")
    parser.add_argument("--context2", default=str(DEFAULT_CONTEXT2), help="stage 2 context/template file")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA), help="DDL/description file for stage 2")
    parser.add_argument("--sqlexamples", default=str(DEFAULT_SQL_EXAMPLES), help="SQL examples for stage 2")
    parser.add_argument("--url", default="http://192.168.1.57:11434", help="Ollama server URL")
    parser.add_argument("--model1", default="llama3.1:8b", help="model for stage 1 (sentence -> intent)")
    parser.add_argument("--model2", default="Qwen2.5-Coder-7B-Instruct-Q4_K_M:latest", help="model for stage 2 (intent -> SQL)")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="sampling temperature for both models; 0 = greedy/deterministic, "
        "which keeps intent extraction and SQL stable run-to-run",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="sampling seed sent to Ollama. Temperature 0 alone did not make runs "
        "repeatable here - the same sentence answered with 9 rows and later with 0 "
        "on unchanged files - and without repeatability no prompt comparison means anything",
    )
    parser.add_argument(
        "--sql",
        choices=("composer", "model", "both"),
        default="composer",
        help="where the SQL comes from: 'composer' builds it from the intent in "
        "intent_to_sql.py and only asks the model for shapes it cannot express; "
        "'model' is the original stage-2 prompt; 'both' runs each and records the "
        "composed query as the training target next to the model's attempt",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="row limit the composer puts on the query",
    )
    parser.add_argument("--db", default="/home/denis/projects/wiki_data/run2/wiki.duckdb", help="local DuckDB file to run the SQL against")
    parser.add_argument(
        "--training-log",
        default="sentence_to_sql_stage2_training.jsonl",
        help="JSONL file to append stage 2 (prompt, completion, execution outcome) records to",
    )
    parser.add_argument(
        "--training-folder",
        default=None,
        help="folder of stage-1 intent *.json files; when set, runs step2_train "
        "(stage 2 only, one file at a time) instead of the full pipeline",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="stop after this many files of --training-folder (0 = all of them). "
        "A full folder is one model call per file, so this is how to cut a run "
        "short once the first few show something is wrong",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.training_folder:
        step2_train(args)
    else:
        full_run(args)


if __name__ == "__main__":
    main()
