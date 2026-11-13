#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rewrite the arrow lambdas in the stage 2 training data as `lambda w:`.

DuckDB 2.0 turns the single-arrow lambda (w -> ...) off by default and 2.1
removes it. The composer writes `lambda w:` since commit 131dff5, but the
training data was composed before that, so the tuned model learned the arrow
and still writes it. connect_db in agent/sentence_to_sql.py switches the arrow
back on for now; this is the real fix, and stage 2 has to be retrained on the
result before DuckDB 2.1.

The files are rewritten in place, not regenerated. prepare_training_data.py
can no longer rebuild the split: the intents under training/training_intents
have changed since 20260922.jsonl was written, and its rows match none of
them. Rewriting in place keeps every row and the train/eval split exactly as
they were, so the retrained model differs from the old one in the lambda and
nothing else.

Only the SQL is touched - `gold_sql` in the eval log, the "gpt" turn in the
ShareGPT splits. The prompts carry arrows too ("null -> return the matching
entities"), but those are English, and the prompt has to stay the one the
model is served.

Running it twice changes nothing. Before anything is written, DuckDB parses
every rewritten query in both spellings, and the files are left alone unless
the two parse to the same query. That needs the duckdb package but no
database.

    python fix_training_lambdas.py
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

DEFAULT_FILES = ["20260922.jsonl", "20260922_train.jsonl", "20260922_eval.jsonl"]

ARROW = re.compile(r"\b([A-Za-z_]\w*) -> ")


def rewrite(sql: str) -> str:
    return ARROW.sub(r"lambda \1: ", sql)


def rewrite_row(row: dict, changed: list) -> dict:
    """Rewrite the SQL of one row, noting each (old, new) pair in `changed`."""
    if "gold_sql" in row and row["gold_sql"]:
        new = rewrite(row["gold_sql"])
        if new != row["gold_sql"]:
            changed.append((row["gold_sql"], new))
            row["gold_sql"] = new
    for turn in row.get("conversations", []):
        if turn.get("from") == "gpt":
            new = rewrite(turn["value"])
            if new != turn["value"]:
                changed.append((turn["value"], new))
                turn["value"] = new
    return row


def _tree(connection, sql: str):
    """The parsed query, minus where each part sits in the text and which
    spelling a lambda was written in - the two things this rewrite changes."""
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items()
                    if not k.startswith("query_location") and k != "syntax_type"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    #the "gpt" turns carry the SQL inside a ```sql fence
    sql = re.sub(r"^\s*```(?:sql)?\s*|\s*```\s*$", "", sql)
    tree = json.loads(connection.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    if tree.get("error"):
        raise ValueError(tree.get("error_message", "does not parse"))
    return strip(tree)


def verify(pairs: list) -> int:
    """Parse both spellings of each query; return how many differ.

    Running the two and comparing rows proves less and takes far longer: a
    query that ends in ORDER BY ... LIMIT may break a tie differently on each
    run, so two runs of the very same SQL can disagree. The parse tree cannot.
    """
    import duckdb
    connection = duckdb.connect()
    connection.execute("SET lambda_syntax = 'enable_single_arrow'")
    bad = 0
    for n, (old, new) in enumerate(pairs, 1):
        try:
            same = _tree(connection, old) == _tree(connection, new)
            problem = None if same else "parses to a different query"
        except ValueError as e:
            problem = str(e)
        if problem:
            bad += 1
            print(f"  query {n}: {problem}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="*", default=DEFAULT_FILES,
                        help="JSONL files to rewrite in place")
    args = parser.parse_args()

    results = {}
    for name in args.files:
        path = Path(name) if Path(name).is_absolute() else PROJECT_DIR / name
        changed = []
        lines = [json.dumps(rewrite_row(json.loads(line), changed))
                 for line in path.read_text().splitlines() if line]
        results[path] = (lines, changed)
        print(f"{path.name}: {len(changed)} query(s) to rewrite")

    #each distinct query once - the splits repeat the eval log's gold SQL
    pairs = list(dict.fromkeys(p for _, changed in results.values() for p in changed))
    if not pairs:
        print("nothing to rewrite")
        return 0
    bad = verify(pairs)
    if bad:
        print(f"{bad} of {len(pairs)} query(s) changed meaning - nothing written")
        return 1
    print(f"{len(pairs)} distinct query(s) parse the same in both spellings")

    for path, (lines, changed) in results.items():
        if changed:
            path.write_text("\n".join(lines) + "\n")
            print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
