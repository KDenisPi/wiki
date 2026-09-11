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

After a --training-folder run, --training-log is also turned straight into
an Unsloth-ready train/eval split (prepare_training_data.py's logic, held
out by variant and by TRAINVARIANTS.md filter-type category so eval never
memorizes a paraphrase or misses a whole category) - the same transform
that used to mean running that script by hand afterward. Written next to
--training-log as <log>_train.jsonl / <log>_eval.jsonl; pass --no-splits to
skip it, or --eval-frac/--split-seed to change the held-out share/draw.
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
from model_retry import (  # noqa: E402 - sibling module
    DEFAULT_RETRY_PENALTY,
    was_cut_off,
    with_cutoff_retry,
)

logger = logging.getLogger("sentence_to_sql")

EXAMPLES_DIR = Path(__file__).resolve().parent
#the prompt templates live beside this file, the schema and the example queries
#one level up with the rest of the project - they describe the database, not
#this pipeline, and the loaders and the C++ parser read them too
PROJECT_DIR = EXAMPLES_DIR.parent
DEFAULT_CONTEXT1 = EXAMPLES_DIR / "sentence_to_sql_stage1_context.txt"
DEFAULT_CONTEXT2 = EXAMPLES_DIR / "sentence_to_sql_stage2_context.txt"
DEFAULT_SCHEMA = PROJECT_DIR / "db_model.sql"
DEFAULT_SQL_EXAMPLES = PROJECT_DIR / "queries.sql"
DEFAULT_INTENTS_DIR = PROJECT_DIR / "training" / "training_intents"
DEFAULT_TRAINVARIANTS = PROJECT_DIR / "TRAINVARIANTS.md"

# prepare_training_data.py sits at the repo root beside them, so the path has
# to be on sys.path before it can be imported.
sys.path.insert(0, str(PROJECT_DIR))
from prepare_training_data import (  # noqa: E402 - after sys.path fixup
    convert as convert_training_log,
    write_jsonl,
)

#Consecutive step2_train failures that mean the run is not worth continuing.
#Above one, so a single bad file is skipped rather than fatal; well below a
#folder, so a server that went away is reported in seconds instead of after
#144 connection timeouts.
GIVE_UP_AFTER = 5



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


def _lazy_client(url: str, model: str, options: dict, timeout: float = 300.0):
    """A no-argument factory building one OllamaClient on first call and
    reusing it after. Stage 2 is often asked nothing at all - the composer
    answered - and constructing a client writes a session file, so it is not
    built until something actually needs it.

    The timeout is long because the fine-tuned model is slow when it is
    working and endless when it is not: OllamaClient's own 60s default cuts
    off answers that would have arrived. --max-tokens is what actually bounds
    the endless case."""
    client = None

    def get() -> OllamaClient:
        nonlocal client
        if client is None:
            client = OllamaClient(url, model, options=options, timeout=timeout)
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
        #read-only because this only ever SELECTs, and a read-write handle takes
        #an exclusive lock on the file - one pipeline run would otherwise fail
        #the moment a DuckDB CLI, compare_models.py or eval_stage1.py had the
        #same database open, and block them in turn
        connection = duckdb.connect(db_path, read_only=True)
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
        logger.info(row)
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


def _parsed_intent(intent: str):
    """The intent as an object, or None when stage 1 did not produce one.

    Distinguishes the two ways compose_sql declines. "intent shape not
    covered" means stage 1 worked and the composer cannot express what it
    said - the model can still read that intent and try. "stage 1 did not
    return JSON" means there is no intent at all, and the stage-2 prompt then
    carries an empty Request. Asked that, the model answers from the shape of
    its training data instead: for "List of all Beethoven symphonies" it
    returned a query for a person named John Doe, which ran, returned 29
    people, and looked like an answer."""
    try:
        parsed = json.loads(intent)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _compares_entities(intent: str) -> bool:
    """Whether the intent is a two-or-more-entity comparison.

    These get no fallback to the model. A comparison is a different shape from
    everything else here - two CTEs holding one entity each, and one row of
    facts about both - and the model does not hold it: over the 27 comparison
    cases its SQL failed to run 12 times, ten of those by reading a column off
    a CTE that never projected it (e1.qid, where e1 selects name, born, died).
    Seven of the ten were cases it had been fine-tuned on. It reaches for the
    list-query template that fits most of its training data, where i.qid is
    always in scope, and on this shape that template does not bind.

    The composer expresses every comparison it is offered except three or more
    entities, so the fallback only ever fires on the shape the model is worst
    at, and a wrong comparison that runs is harder to catch than none."""
    try:
        filters = (json.loads(intent) or {}).get("filters") or {}
    except (json.JSONDecodeError, AttributeError):
        return False
    return bool(filters.get("compare_entities"))


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

    #max_tokens is not optional for the tuned model. Uncapped it does not
    #always stop: on some prompts it starts a plausible query and then
    #enumerates 'P44', 'P45', 'P46' until the context is full, which reads
    #as a hung server rather than as a model that never finished.
    options = {"temperature": args.temperature, "seed": args.seed,
               "max_tokens": args.max_tokens}
    #Stage 1 gets its own, far larger cap. A reasoning model spends the budget
    #thinking before it writes anything, and those tokens count: qwen3.6 on
    #this prompt produced 3904 characters of reasoning and an EMPTY answer at
    #1024, and a correct intent at 4096. An empty stage-1 reply is worse than a
    #slow one - it looks like a model that cannot read the sentence.
    options1 = {**options, "max_tokens": args.max_tokens1}
    prompt1 = _fill(context1, sentence=args.sentence)
    client1 = OllamaClient(args.url, args.model1, options=options1,
                           timeout=args.request_timeout)
    intent = _extract_intent_json(run_stage(client1, "stage1", prompt1))
    logger.info("stage1 intent (extracted):\n%s", intent)

    prompt2 = _fill(context2, answer=intent, schema=schema, examples=sqlexamples)
    stage2_once(args, intent, prompt2, _lazy_client(args.url2, args.model2, options, args.request_timeout))


def _ask_stage2(get_client, prompt: str, frequency_penalty: float) -> dict:
    """One stage-2 call, in the shape model_retry.with_cutoff_retry expects.

    OllamaClient returns the reply text alone, but keeps the whole response on
    itself for its own log line - which is the only place finish_reason is to
    be had without a second request. Read defensively: a client that stopped
    recording it should cost a retry, not an AttributeError.

    The penalty is applied by swapping the client's options for the one call.
    They are spread into the request body as they stand at request time, and
    put back afterwards so the next call is unaffected."""
    client = get_client()
    saved = dict(client.options)
    if frequency_penalty:
        client.options = {**saved, "frequency_penalty": frequency_penalty}
    started = time.perf_counter()
    try:
        completion = run_stage(client, "stage2", prompt)
    finally:
        client.options = saved

    payload = getattr(client, "_last_metrics", None) or {}
    choices = payload.get("choices") or [{}]
    usage = payload.get("usage") or {}
    return {
        "completion": completion,
        "finish_reason": choices[0].get("finish_reason"),
        "completion_tokens": usage.get("completion_tokens"),
        "seconds": time.perf_counter() - started,
        "error": None,
    }


def stage2_once(args: argparse.Namespace, intent: str, prompt2: str, get_client,
                label: str = "") -> None:
    """Turn one intent into SQL, run it, and record the training example.

    What --sql selects:
        composer  compose from the intent; ask the model only for the shapes
                  the composer refuses, and not even then for a comparison
        model     ask the model, and nothing else
        both      compose and ask, run each, and record the composed query as
                  the training target beside the model's attempt

    The composer is the default because a filter it is handed cannot go
    missing, while the model has repeatedly returned SQL that ran, looked
    plausible and answered a different question.

    Comparisons are the one shape with no fallback: the question is answered by
    the composer or not at all. _compares_entities has the measurements.

    A model reply cut off at --max-tokens is asked for once more with a
    frequency penalty; model_retry explains why only that case gets a retry.

    Shared by full_run and step2_train so a training record always holds the
    prompt the pipeline really sends - a record built from some other prompt is
    worse than no record, since fine-tuning on it teaches the wrong input.
    """
    gold, reason = (None, "not requested")
    if args.sql in ("composer", "both"):
        gold, reason = compose_sql(intent, args.limit)
        if gold is None and args.sql == "composer" and _compares_entities(intent):
            #no SQL at all rather than the model's: see _compares_entities.
            #Only in "composer" mode - "model" and "both" are asked for on
            #purpose, and both exist to see what the model does with a prompt.
            logger.warning("%scomposer declined a comparison, and the model is not "
                           "asked for these: %s", label, reason)
            return
        if gold is None and _parsed_intent(intent) is None:
            #not a fallback case: there is no intent to hand on. See
            #_parsed_intent for what the model does when asked anyway.
            logger.error("%sstage 1 produced no intent, so stage 2 is not asked: %s",
                         label, reason)
            return
        if gold is None:
            logger.info("%scomposer declined, using the model: %s", label, reason)

    completion, sql, source = None, gold, "composer"

    if gold is None or args.sql in ("model", "both"):
        reply = with_cutoff_retry(
            lambda penalty: _ask_stage2(get_client, prompt2, penalty),
            retry_penalty=args.retry_penalty, label=label, log=logger)
        completion = reply["completion"]
        if was_cut_off(reply):
            #said plainly, because the SQL below will fail to parse and the
            #reason is worth knowing: the model never finished, it was stopped
            logger.warning("%sstage 2 hit the %d token cap - reply cut off",
                           label, args.max_tokens)
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


def _split_output_paths(training_log: str) -> tuple:
    path = Path(training_log)
    return (str(path.with_name(f"{path.stem}_train.jsonl")),
            str(path.with_name(f"{path.stem}_eval.jsonl")))


def write_training_splits(args: argparse.Namespace) -> None:
    """Turn args.training_log straight into the Unsloth-ready train/eval split
    that used to mean running prepare_training_data.py by hand after every
    step2_train batch. Safe to call here specifically because every intent in
    a --training-folder run comes from args.intents_dir, so its Request always
    matches a variant there - the same is not true of an ad hoc full_run
    sentence, which is why this is only wired into step2_train.

    A splitting failure must not make an otherwise-successful run look
    failed - the JSONL log itself is already complete and usable by hand -
    so any error here is logged and swallowed rather than raised."""
    if args.no_splits:
        return
    train_path, eval_path = _split_output_paths(args.training_log)
    try:
        train, ev, dropped, eval_variants = convert_training_log(
            args.training_log, args.intents_dir, args.trainvariants,
            args.eval_frac, args.split_seed
        )
        write_jsonl(train_path, train)
        write_jsonl(eval_path, ev)
    except Exception as e:
        logger.warning("could not build train/eval splits from %s: %s", args.training_log, e)
        return
    logger.info(
        "train/eval splits: %d train -> %s, %d eval -> %s "
        "(dropped %d with no gold_sql; eval variants: %s)",
        len(train), train_path, len(ev), eval_path, dropped, ", ".join(eval_variants),
    )


def step2_train(args: argparse.Namespace) -> None:
    """Run stage 2 (intent -> SQL) alone against the intent JSON files in
    args.training_folder, one by one, logging each to the same JSONL training
    log full_run() writes to - skips stage 1 entirely since each file already
    holds the intent stage 1 would have produced.

    --sql applies here as it does anywhere else, and --max-files cuts the pass
    short: a full folder is one model call per file, so a mistake in the
    prompts is cheaper to find over the first few than over all of them.

    A file that fails is skipped, not fatal - a folder is an hour's work and a
    single timeout should not throw away what came before it. GIVE_UP_AFTER in
    a row ends the run, because that is the server rather than the files."""
    context2 = Path(args.context2).read_text()
    schema = Path(args.schema).read_text()
    sqlexamples = Path(args.sqlexamples).read_text()
    #max_tokens is not optional for the tuned model. Uncapped it does not
    #always stop: on some prompts it starts a plausible query and then
    #enumerates 'P44', 'P45', 'P46' until the context is full, which reads
    #as a hung server rather than as a model that never finished.
    options = {"temperature": args.temperature, "seed": args.seed,
               "max_tokens": args.max_tokens}
    get_client = _lazy_client(args.url2, args.model2, options, args.request_timeout)

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

    done = failed = in_a_row = 0
    for json_file in json_files:
        logger.info("step2_train: %s", json_file.name)
        try:
            intent = _intent_text(json_file)
        except json.JSONDecodeError as e:
            #one unparseable file must not end a run of a hundred others
            logger.error("skipping %s: not JSON (%s)", json_file.name, e)
            failed += 1
            continue

        prompt2 = _fill(context2, answer=intent, schema=schema, examples=sqlexamples)
        try:
            stage2_once(args, intent, prompt2, get_client, label=f"[{json_file.name}] ")
        except Exception as e:
            #same rule as an unparseable file, now that the model is involved:
            #one timeout an hour into a folder must not throw away the rest
            logger.error("skipping %s: %s", json_file.name, e)
            failed += 1
            in_a_row += 1
            if in_a_row >= GIVE_UP_AFTER:
                #a whole folder failing in a row is the server, not the files,
                #and grinding through the remainder only delays saying so
                logger.error("step2_train: %d file(s) in a row failed - stopping "
                             "with %d of %d done", in_a_row, done, len(json_files))
                break
            continue
        done += 1
        in_a_row = 0

    logger.info("step2_train: %d done, %d skipped, of %d file(s)",
                done, failed, len(json_files))
    write_training_splits(args)


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
    parser.add_argument("--url", default="http://192.168.1.57:11434",
                        help="server for stage 1. Stage 2 has its own, --url2")
    parser.add_argument("--url2", default="http://192.168.1.57:1235",
                        help="server for stage 2, which is a different one because the fine-tuned "
                        "model is served by llama-server rather than Ollama. Both speak the same "
                        "OpenAI /v1/chat/completions API, so only the address and the naming "
                        "differ. Pass the same value as --url to put both stages back on one server")
    parser.add_argument("--max-tokens1", type=int, default=4096,
                        help="cap on a stage-1 reply. Far above --max-tokens because a reasoning "
                        "model spends the budget thinking first and those tokens count: qwen3.6 "
                        "on a stage-1 prompt wrote 3904 characters of reasoning and an empty "
                        "answer at 1024, and a correct intent at 4096")
    parser.add_argument("--max-tokens", type=int, default=1024,
                        help="cap on a model reply, so one that never emits end-of-text is cut off "
                        "in seconds instead of generating until the context is full. 1024 is well "
                        "clear of anything legitimate: the longest correct stage-2 answer measured "
                        "is 678 tokens")
    parser.add_argument("--retry-penalty", type=float, default=DEFAULT_RETRY_PENALTY,
                        help="frequency penalty for a second attempt, made only when a reply was "
                        "cut off at --max-tokens. Set to 0 to switch the retry off and keep "
                        "whatever the first attempt produced")
    parser.add_argument("--request-timeout", type=float, default=300.0,
                        help="seconds to wait for one model reply, over OllamaClient's own 60s "
                        "default - the tuned model takes longer than that on real prompts")
    parser.add_argument(
        "--intents-dir",
        default=str(DEFAULT_INTENTS_DIR),
        help="directory of {sentence, intent} files that names each variant; used, after a "
        "--training-folder run, to build the Unsloth train/eval split from --training-log",
    )
    parser.add_argument(
        "--trainvariants",
        default=str(DEFAULT_TRAINVARIANTS),
        help="doc grouping variants into filter-type categories, for the train/eval split",
    )
    parser.add_argument(
        "--eval-frac",
        type=float,
        default=0.15,
        help="fraction of each filter-type category's variants held out for eval",
    )
    parser.add_argument(
        "--split-seed",
        type=int,
        default=0,
        help="random seed for picking which variants are held out for eval",
    )
    parser.add_argument(
        "--no-splits",
        action="store_true",
        help="after a --training-folder run, skip building the *_train.jsonl/*_eval.jsonl "
        "split beside --training-log",
    )
    parser.add_argument("--model1", default="llama3.1:8b", help="model for stage 1 (sentence -> intent)")
    parser.add_argument("--model2",
                        default="/home/denis/projects/models/qwen2.5-coder-7b-instruct.Q4_K_M.gguf",
                        help="model for stage 2 (intent -> SQL). llama-server names a model by the "
                        ".gguf path it was started with, Ollama by its tag, so this changes with "
                        "--url2 - the Ollama name for the untuned one is "
                        "Qwen2.5-Coder-7B-Instruct-Q4_K_M:latest")
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
        "intent_to_sql.py and only asks the model for shapes it cannot express - "
        "except a comparison of named entities, which the composer answers or "
        "nobody does; 'model' is the original stage-2 prompt; 'both' runs each and "
        "records the composed query as the training target next to the model's attempt",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="row limit the composer puts on the query",
    )
    parser.add_argument("--db", default="/home/denis/projects/wiki_data/run4/wiki.duckdb", help="local DuckDB file to run the SQL against")
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
