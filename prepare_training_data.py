#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn an eval log from sentence_to_sql.py into an Unsloth SFT dataset,
split into train/eval by variant.

full_20260920.jsonl is one row per stage-2 run: `prompt` is the schema +
rules + intent request fed to the model, `completion`/`sql` is what the
local model (Qwen2.5-Coder-7B here, see the `model` field) answered, and
`gold_sql` is the correct query composed by agent/intent_to_sql.py's
composer (sql_source == "composer"). db_status/db_error/row_count grade
`sql`, not `gold_sql` - they are eval metadata about the old attempt, not
part of the training pair.

For fine-tuning we want the model to learn the *correct* answer, so the
target is gold_sql, not completion. Rows written by the composer's model
fallback (sql_source == "model") carry no gold_sql and are dropped.

The 144 rows are 48 hand-defined variants (see TRAINVARIANTS.md) x 3
near-duplicate paraphrases each - same filter shape, different entity
names. Each row's trailing `Request: {...}` intent JSON matches exactly
one file under training/training_intents/, whose name gives the variant
slug (e.g. "01_name_time_work"). A random row split would put paraphrases
of the same variant on both sides of train/eval, so eval would measure
memorization of a pattern rather than generalization to a new one. This
script instead holds out whole variants - every example of a held-out
variant goes to eval, none of its paraphrases leak into train.

TRAINVARIANTS.md further groups the 48 variants into 7 filter-type
categories (A: point lookup, B: person-descriptor retrieval, ...,
G: dense multi-filter stress cases). Picking held-out variants uniformly
at random over all 48 can - and with the default seed did - miss whole
categories (e.g. no time-window or dense-filter case in eval), which
would leave those failure modes unchecked. So the held-out set is drawn
per category instead: at least one variant from every category ends up
in eval.

Output: train/eval files, each one ShareGPT-style {"conversations": [...]}
row per kept example, ready for Unsloth's apply_chat_template / mapping UI
(prompt -> User, gold_sql -> Assistant).
"""

import argparse
import glob
import json
import os
import random
import re


def load_variant_lookup(intents_dir: str) -> dict:
    """Map a canonicalized intent JSON string to its variant slug, e.g.
    "01_name_time_work" for .../01_name_time_work_2.json."""
    lookup = {}
    for path in glob.glob(os.path.join(intents_dir, "*.json")):
        with open(path, "r") as fd:
            data = json.load(fd)
        base = os.path.basename(path)
        m = re.match(r"(\d+_[a-z0-9_]+?)_\d+\.json$", base)
        if not m:
            raise ValueError(f"unexpected intent filename: {base}")
        key = json.dumps(data["intent"], sort_keys=True)
        lookup[key] = m.group(1)
    return lookup


def load_variant_categories(trainvariants_path: str) -> dict:
    """Map a bare variant slug (e.g. "name_time_work", no "NN_" prefix) to
    its single-letter filter-type category, by parsing TRAINVARIANTS.md's
    "## X. ..." section headers and "N. `slug` - ..." list items."""
    cat = None
    categories = {}
    section_re = re.compile(r"^##\s+([A-Z])\.\s")
    item_re = re.compile(r"^\d+\.\s+`([a-z0-9_]+)`")
    with open(trainvariants_path, "r") as fd:
        for line in fd:
            m = section_re.match(line)
            if m:
                cat = m.group(1)
                continue
            m = item_re.match(line)
            if m and cat:
                categories[m.group(1)] = cat
    return categories


def extract_request(prompt: str) -> dict:
    """Pull the trailing `Request: {...}` intent JSON out of a stage-2 prompt."""
    marker = "Request:"
    idx = prompt.rfind(marker)
    if idx == -1:
        raise ValueError("no 'Request:' section in prompt")
    return json.loads(prompt[idx + len(marker):].strip())


def to_example(row: dict) -> dict:
    return {
        "conversations": [
            {"from": "human", "value": row["prompt"]},
            {"from": "gpt", "value": f"```sql\n{row['gold_sql']}\n```"},
        ]
    }


def convert(in_path: str, intents_dir: str, trainvariants_path: str, eval_frac: float, seed: int):
    variant_lookup = load_variant_lookup(intents_dir)
    variant_categories = load_variant_categories(trainvariants_path)

    kept_rows = []
    dropped = 0
    with open(in_path, "r") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)

            if row.get("sql_source") != "composer" or not row.get("gold_sql"):
                dropped += 1
                continue

            key = json.dumps(extract_request(row["prompt"]), sort_keys=True)
            variant = variant_lookup.get(key)
            if variant is None:
                raise ValueError("row's Request intent matches no file under " + intents_dir)
            kept_rows.append((variant, row))

    # Group variants by filter-type category so the held-out set is drawn
    # from every category, not just wherever a flat random sample lands.
    by_category = {}
    for variant in {v for v, _ in kept_rows}:
        bare_slug = variant.split("_", 1)[1]
        category = variant_categories.get(bare_slug)
        if category is None:
            raise ValueError(f"variant {variant!r} not listed in {trainvariants_path}")
        by_category.setdefault(category, []).append(variant)

    rng = random.Random(seed)
    eval_variants = set()
    for category, cat_variants in by_category.items():
        cat_variants = sorted(cat_variants)
        rng.shuffle(cat_variants)
        n_eval = max(1, round(len(cat_variants) * eval_frac))
        eval_variants.update(cat_variants[:n_eval])

    train_examples = [to_example(r) for v, r in kept_rows if v not in eval_variants]
    eval_examples = [to_example(r) for v, r in kept_rows if v in eval_variants]

    return train_examples, eval_examples, dropped, sorted(eval_variants)


def write_jsonl(path: str, examples: list) -> None:
    with open(path, "w") as fd:
        for ex in examples:
            fd.write(json.dumps(ex, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="full_20260920.jsonl")
    parser.add_argument("--intents-dir", default="training/training_intents",
                         help="directory of {sentence, intent} files that name each variant")
    parser.add_argument("--trainvariants", default="TRAINVARIANTS.md",
                         help="doc that groups variants into filter-type categories")
    parser.add_argument("--train-out", default="full_20260920_train.jsonl")
    parser.add_argument("--eval-out", default="full_20260920_eval.jsonl")
    parser.add_argument("--eval-frac", type=float, default=0.15,
                         help="fraction of each category's variants (not rows) held out for eval")
    parser.add_argument("--seed", type=int, default=0,
                         help="random seed for picking which variants are held out")
    args = parser.parse_args()

    train, ev, dropped, eval_variants = convert(
        args.input, args.intents_dir, args.trainvariants, args.eval_frac, args.seed
    )
    write_jsonl(args.train_out, train)
    write_jsonl(args.eval_out, ev)

    print(f"train: {len(train)} rows -> {args.train_out}")
    print(f"eval:  {len(ev)} rows -> {args.eval_out}  (variants: {', '.join(eval_variants)})")
    print(f"dropped: {dropped} rows (no composer gold_sql)")


if __name__ == "__main__":
    main()
