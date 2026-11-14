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

Python 3.11 or newer with two packages, nothing more. The venv on gx10-3ec8
is Python 3.12.3:

    python3 -m venv /home/denis/projects/venv-duckdb2
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
- 2.0 turns off the arrow lambda (`w -> ...`), and 2.1 removes it. Nothing
  here writes it any more: the composer uses `lambda w:`, and so does the
  stage 2 model served since 2026-11-13, retrained on it (below). `connect_db`
  in `agent/sentence_to_sql.py` no longer switches the arrow back on, so an
  arrow from the model fails with `Deprecated lambda arrow (->) detected`
  instead of working until 2.1.

### Retraining stage 2

Done on 2026-11-12 to move the model to `lambda w:`, and served since
2026-11-13; this is how to repeat it. The August model, which writes the
arrow, is kept in `/home/denis/projects/models/stage2_arrow/` for rollback.

**Data.** `20260922_train.jsonl` (113 rows) and `20260922_eval.jsonl` (25)
are the exact files the August Unsloth Studio job trained on;
`20260922.jsonl` (144) is the log they came from. `fix_training_lambdas.py`
rewrote the target SQL in all three to `lambda w:` and left every prompt
and row as it was. It has DuckDB parse each query in both spellings and
writes nothing unless the two are the same query; run again, it says
`nothing to rewrite`. `prepare_training_data.py` cannot regenerate these
files: the intents under `training/training_intents` have changed since
the log was written.

**Train** - about 30 minutes. `train_stage2.py` replays the August job's
settings (QLoRA r=16 on `unsloth/qwen2.5-coder-7b-instruct-bnb-4bit`,
30 steps) through Studio's own training worker, so it needs Studio's
interpreter:

    ~/.unsloth/studio/unsloth_studio/bin/python train_stage2.py --name <name>

The adapter lands in `~/.unsloth/studio/outputs/<name>`. The 2026-11-12 run
ended at eval loss 0.053, against 0.054 in August.

The GB10's GPU shares system memory, and CUDA counts only `MemFree` as
free - not the page cache, which Ollama's model files fill. With too little
free, loading the model fails with `Some modules are dispatched on the CPU
or the disk`, so `train_stage2.py` stops first if under 12 GiB is free.
Drop the cache (`sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'`) and
check that `MemFree` in `/proc/meminfo` actually rose, or unload an Ollama
model that can be spared (`ollama stop <model>`).

**Export** - about 4 minutes - to the Q4_K_M `.gguf` llama-server serves:

    ~/.local/bin/unsloth export ~/.unsloth/studio/outputs/<name> \
        /home/denis/projects/models/<new dir> -f gguf -q q4_k_m

**Compare** before switching. Serve the new `.gguf` on a spare port (`:1236`,
otherwise the same command as `:1235` below) and run it against the served
model, first on the log the training rows came from:

    M=/home/denis/projects/models
    /home/denis/projects/venv-duckdb2/bin/python agent/compare_models.py \
        --cases 20260922.jsonl --splits 20260922_train.jsonl 20260922_eval.jsonl \
        --tuned-url http://127.0.0.1:1236 \
        --tuned-model $M/<new dir>/qwen2.5-coder-7b-instruct.Q4_K_M.gguf \
        --base-url http://192.168.1.57:1235 \
        --base-model $M/qwen2.5-coder-7b-instruct.Q4_K_M.gguf

then again without `--cases` and `--splits`, on the 144 intents under
`training/training_intents`. Each pass takes about an hour. On 2026-11-12
the two models were right on 85 of 282 cases each, and the new one wrote no
arrow.

**Switch.** Stop `:1235`, move the old `.gguf` aside, put the new one at the
path `:1235` serves (so the `--model2` default stays right), start `:1235`
again and run the checks under "Checking the new machine".

## Model servers

The pipeline runs no model itself. It calls two servers, both on
`192.168.1.57` by default - gx10-3ec8, the machine the project has run on
since 2026-11-12:

| Stage | Option | Default server | Default model |
|---|---|---|---|
| step 0 grammar | `--url`, `--model-grammar` | Ollama `:11434` | `llama3.1:8b` |
| stage 1 intent | `--url`, `--model1` | Ollama `:11434` | `llama3.1:8b` |
| stage 2 SQL | `--url2`, `--model2` | llama-server `:1235` | `/home/denis/projects/models/qwen2.5-coder-7b-instruct.Q4_K_M.gguf` |

llama-server names a model by the `.gguf` path it was started with, so
`--model2` is a path on the **server**, not on this machine. Under Ollama the
untuned one is `Qwen2.5-Coder-7B-Instruct-Q4_K_M:latest`.

Ollama runs as a systemd service. The `:1235` llama-server does not - after a
reboot, start it again from the llama.cpp checkout:

    cd ~/projects/llama.cpp
    setsid ./build/bin/llama-server \
        -m /home/denis/projects/models/qwen2.5-coder-7b-instruct.Q4_K_M.gguf \
        -ngl 99 --host 0.0.0.0 --port 1235 -fa on \
        --cache-type-k q8_0 --cache-type-v q8_0 > logs/llama.log 2>&1 &

Check that the new machine reaches them:

    python agent/sentence_to_sql.py --list-models

## Checking the new machine

1. The composer self-check - 28 checks against the database, about 1 minute
   on gx10-3ec8's 20 cores, 4-5 minutes on 12. It must end with
   `all checks passed`:

       /home/denis/projects/venv-duckdb2/bin/python agent/intent_to_sql.py

   On run7 the output from DuckDB 2.0.0 is identical to the output from 1.5.5.

2. One question end to end (needs the model servers):

       /home/denis/projects/venv-duckdb2/bin/python agent/sentence_to_sql.py \
           --sentence "When was Beethowen born?" --training-log /tmp/t.jsonl

   It should log `SQL (composer)`, then `duckdb(...) ok`, then an `answer:` line.

DuckDB spills large queries to a temp directory and may use up to 25 GiB there
by default - leave that much free on the disk with the database.

## The wiki service (for MCP and the kiosk)

`agent/wiki_service.py` serves the same pipeline over HTTP on `:8200`, for
AI_agents' MCP proxy at `:8000/wiki` and its kiosk. It uses only the venv
above - Python's own HTTP server, no new packages. The module docstring has
the endpoints; in short:

| Endpoint | Does | MCP tool |
|---|---|---|
| `POST /sentence {"question"}` | step 0 only | `wiki_sentence` |
| `POST /intent {"question"}` | step 0, stage 1, the leader-word fill, names - no SQL | `wiki_intent` |
| `POST /query <intent>` | names, then stage 2 | `wiki_query` |
| `POST /ask {"question"}` | all of it | `wiki_ask` |
| `GET /tools` | the four tools' names, descriptions and input schemas | |
| `GET /health` | `{"status": "ok"}` when the database is there | |

At most 50 rows come back (`row_count` is the total) and two questions run at
once (`--max-rows`, `--concurrency`). Unlike the command line it writes no
training log unless `--training-log` is passed.

Run it as a service (needs sudo):

    sudo cp wiki-server.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now wiki-server
    curl -s localhost:8200/health
    curl -s localhost:8200/ask -d '{"question": "When was Beethowen born?"}'

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
