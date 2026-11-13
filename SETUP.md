# Setting up on another computer

What the project needs outside this repository, and how to check that a new
machine has all of it. Measured on 2026-11-12 against the run7 database.

## What to copy

| What | Size | Needed for |
|---|---|---|
| this repo (`git clone https://github.com/KDenisPi/wiki.git`) | 89 MB | everything |
| `AI_agents` repo (`git clone https://github.com/KDenisPi/AI_agents.git`) | 18 MB | everything - `OllamaClient` lives there |
| `wiki_data/run7/wiki.duckdb` | 2.1 GB | asking questions |
| `wiki_data/classes/` | 40 MB | rebuilding the database |
| `wiki_data/properties.json` | 1.4 MB | rebuilding the database |
| run7 CSVs: Attributes, DataEvents, ItemsExt, ItemClasses, ItemSites, values | 5.6 GB | rebuilding the database without re-reading the dump |

To ask questions, copy only the database file. `ItemsExtNotUsed.csv` (9.2 GB) is not read by
`load_duckdb.py` and does not need copying. Neither do run3-run6, `attempt/` and
`fstep/` (about 85 GB together).

Copy the database while nothing has it open for writing - there must be no
`wiki.duckdb.wal` beside it. The file is already compressed; zipping it saves
little.

    rsync -ah --progress /home/denis/projects/wiki_data/run7/wiki.duckdb \
        newhost:/home/denis/projects/wiki_data/run7/

## Directory layout

Keep the same paths if you can: `/home/denis/projects/wiki`,
`/home/denis/projects/AI_agents` and `/home/denis/projects/wiki_data/run7/wiki.duckdb`.

- `agent/*.py` find `OllamaClient` at `../../AI_agents` relative to `agent/`,
  so the two repos must sit side by side. There is no option for this one.
- Every agent tool defaults to `/home/denis/projects/wiki_data/run7/wiki.duckdb`
  (`sentence_to_sql.py`, `compare_models.py`, `eval_stage1.py`,
  `intent_to_sql.py`, `resolve_names.py`). Elsewhere, pass `--db` -
  `intent_to_sql.py` takes it as its first argument (`--db <path>`).
- The rebuild scripts (`run_wpars.sh`, `rerun_extract.sh`, `load_duckdb.py`,
  `build_class_closure.py`) default to the same tree. The shell scripts take
  their paths from environment variables (`WPARS`, `DUMP`, `PROPS`, `CONFIG`).

## Python

Python 3.11 with two packages, nothing more:

    python3.11 -m venv /home/denis/projects/venv-duckdb2
    /home/denis/projects/venv-duckdb2/bin/pip install duckdb==2.0.0 requests

`requests` is needed even with no network question in sight: `OllamaClient`
imports it, and every agent script imports `OllamaClient`.

### DuckDB version

The database must be opened with the same DuckDB major version on every
machine that writes it.

- 2.0 opens files written by 1.x and does not convert them, so the agent works
  on run7 as it is. It opens the database read-only anyway.
- A file **created** by 2.0 - any `load_duckdb.py` rebuild - uses storage
  version 69, which 1.x cannot open. Upgrade every machine before copying one.
- 2.0 turns off the arrow lambda (`w -> ...`). The stage 2 training data
  (`20260922*.jsonl`) still teaches it, so the model writes it.
  `connect_db` in `agent/sentence_to_sql.py` switches it back on with
  `SET lambda_syntax = 'enable_single_arrow'`. **DuckDB 2.1 removes that
  setting**: before upgrading to 2.1, regenerate the training data with
  `lambda w:` and retrain stage 2. The composer's own SQL already uses
  `lambda w:`.

## Model servers

Nothing runs a model locally. The pipeline calls two servers, both on
`192.168.1.57` by default:

| Stage | Option | Default server | Default model |
|---|---|---|---|
| step 0 grammar | `--url`, `--model-grammar` | Ollama `:11434` | `llama3.1:8b` |
| stage 1 intent | `--url`, `--model1` | Ollama `:11434` | `llama3.1:8b` |
| stage 2 SQL | `--url2`, `--model2` | llama-server `:1235` | `/home/denis/projects/models/qwen2.5-coder-7b-instruct.Q4_K_M.gguf` |

llama-server names a model by the `.gguf` path it was started with, so
`--model2` is a path on the **server**, not on this machine. Under Ollama the
untuned one is `Qwen2.5-Coder-7B-Instruct-Q4_K_M:latest`.

Check that the new machine reaches them:

    python agent/sentence_to_sql.py --list-models

## Checking the new machine

1. The composer self-check - 28 checks against the database, about 4-5 minutes
   on 12 cores. It must end with `all checks passed`:

       /home/denis/projects/venv-duckdb2/bin/python agent/intent_to_sql.py

   On run7 the output from DuckDB 2.0.0 is identical to the output from 1.5.5.

2. One question end to end (needs the model servers):

       /home/denis/projects/venv-duckdb2/bin/python agent/sentence_to_sql.py \
           --sentence "When was Beethowen born?" --training-log /tmp/t.jsonl

   It should log `SQL (composer)`, then `duckdb(...) ok`, then an `answer:` line.

DuckDB spills large queries to a temp directory and may use up to 25 GiB there
by default - leave that much free on the disk with the database.

## Rebuilding the database (optional)

Only needed for a new extract. The full parse reads the 2 TB dump
(`/mnt/nfs/wiki/wikidata-20250922-all.json`) and runs for hours.

- `wpars` (C++) needs CMake 3.12+ and rapidjson, which is vendored and not
  tracked: `git clone https://github.com/Tencent/rapidjson.git thparty/rapidjson`.
  Build into `build/` (`run_wpars.sh` looks for `build/wpars`).
- `rerun_extract.sh` runs the whole sequence: parse, `resolve_values.py`,
  `load_duckdb.py`. From existing CSVs, only the last step is needed:

      python load_duckdb.py --data-dir <run dir> --db <run dir>/wiki.duckdb

  It reads `wiki_data/classes/` and `wiki_data/properties.json` by default
  (`--config-dir`, `--properties`).
