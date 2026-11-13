#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fine-tune the stage 2 model (intent -> DuckDB SQL) the way Unsloth Studio did.

The served stage 2 model came out of one Unsloth Studio job on 2026-08-22
(job_20260822_203942_c78351b1). This replays that job's settings instead of
clicking them back into the Studio form: CONFIG below is the job's stored
config, and it goes to the same worker function Studio runs, in a spawned
child process just as Studio starts it. Only the datasets and the output
folder differ.

    QLoRA on unsloth/qwen2.5-coder-7b-instruct-bnb-4bit, r=16, alpha=16,
    all seven projections, lr 2e-4 linear, 5 warmup steps, batch 2 x 4,
    30 steps (2 epochs over 113 rows), seed 3407, loss on completions only,
    eval loss on the held-out split every 3 steps. About 31 minutes here.

It needs Studio's own interpreter, since it imports Studio's backend:

    ~/.unsloth/studio/unsloth_studio/bin/python train_stage2.py

The adapter lands under ~/.unsloth/studio/outputs/, where Studio and
`unsloth export` find it. Turn it into the .gguf llama-server serves with:

    ~/.local/bin/unsloth export <output dir> <export dir> -f gguf -q q4_k_m

Studio's worker is its internal API, not a published one. If an Unsloth
upgrade breaks this script, run the same settings in the Studio UI instead -
they are all in CONFIG.
"""

import argparse
import multiprocessing as mp
import queue
import sys
import sysconfig
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# The 2026-08-22 job's config_json from ~/.unsloth/studio/studio.db, minus what
# Studio fills in at run time (the GPU auto-selection and provenance notes) and
# the dataset paths, which main() sets.
CONFIG = {
    "model_name": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "actual_model_repo_id": "unsloth/qwen2.5-coder-7b-instruct-bnb-4bit",
    "model_snapshot_path": str(Path.home() / ".cache/huggingface/hub"
                               "/models--unsloth--qwen2.5-coder-7b-instruct-bnb-4bit"
                               "/snapshots/4858886f896bd05db823557fc5cbc4ac28342af7"),
    "training_type": "LoRA/QLoRA",
    "load_in_4bit": True,
    "max_seq_length": 32768,
    "hf_dataset": "",
    "format_type": "auto",
    "eval_steps": 0.1,
    "num_epochs": 0,
    "max_steps": 30,
    "save_steps": 30,
    "learning_rate": "0.0002",
    "batch_size": 2,
    "gradient_accumulation_steps": 4,
    "warmup_steps": 5,
    "weight_decay": 0.001,
    "random_seed": 3407,
    "packing": False,
    "optim": "adamw_8bit",
    "lr_scheduler_type": "linear",
    "use_lora": True,
    "lora_r": 16,
    "lora_alpha": 16,
    "lora_dropout": 0.0,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj",
                       "gate_proj", "up_proj", "down_proj"],
    "gradient_checkpointing": "unsloth",
    "use_rslora": False,
    "use_loftq": False,
    "use_dora": False,
    "train_on_completions": True,
    "finetune_vision_layers": True,
    "finetune_language_layers": True,
    "finetune_attention_modules": True,
    "finetune_mlp_modules": True,
    "enable_wandb": False,
    "enable_tensorboard": False,
    "trust_remote_code": False,
    "device_backend": "cuda",
    "resolved_gpu_ids": [0],
}


def check_free_memory(needed_gib: float = 12.0) -> None:
    """Stop early when the GPU will look full although it is not.

    The GB10's GPU shares system memory, and CUDA reports only MemFree as free -
    page cache does not count, although the kernel would hand it over. With the
    cache full (Ollama's model files alone fill it), CUDA sees a few GiB,
    transformers decides the 5.8 GB of 4-bit weights will not fit, and the load
    fails 20 s in with "Some modules are dispatched on the CPU or the disk".
    That load-time check is the one that needs MemFree; what training allocates
    after it is taken from reclaimable cache as it goes."""
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        meminfo[key] = int(value.split()[0]) / 2**20
    free, available = meminfo.get("MemFree", 0), meminfo.get("MemAvailable", 0)
    if free < needed_gib:
        hint = ("\n  most of it is page cache - drop it, then run this again:\n"
                "    sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'"
                if available >= needed_gib else "")
        sys.exit(f"only {free:.1f} GiB free for the GPU ({available:.1f} GiB available), "
                 f"training wants {needed_gib:.0f}{hint}")
    print(f"memory: {free:.1f} GiB free, {available:.1f} GiB available", flush=True)


def studio_backend() -> Path:
    backend = Path(sysconfig.get_paths()["purelib"]) / "studio" / "backend"
    if not (backend / "core" / "training" / "worker.py").exists():
        sys.exit(f"Unsloth Studio's backend is not in {backend.parent.parent} - run this with "
                 "~/.unsloth/studio/unsloth_studio/bin/python")
    return backend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--train", default="20260922_train.jsonl",
                        help="ShareGPT JSONL to train on (default: %(default)s)")
    parser.add_argument("--eval", default="20260922_eval.jsonl",
                        help="held-out ShareGPT JSONL for the eval loss (default: %(default)s)")
    parser.add_argument("--name", default=None,
                        help="output folder under ~/.unsloth/studio/outputs "
                             "(default: Qwen_Qwen2.5-Coder-7B-Instruct_stage2_<unix time>)")
    args = parser.parse_args()

    config = dict(CONFIG)
    for key, name in (("local_datasets", args.train), ("local_eval_datasets", args.eval)):
        path = Path(name) if Path(name).is_absolute() else PROJECT_DIR / name
        if not path.is_file():
            sys.exit(f"no such dataset: {path}")
        config[key] = [str(path)]
    config["output_dir"] = args.name or f"Qwen_Qwen2.5-Coder-7B-Instruct_stage2_{int(time.time())}"

    check_free_memory()
    sys.path.insert(0, str(studio_backend()))
    #what Studio's server does at start-up: point Unsloth's compile cache and the
    #llama.cpp it exports with at ~/.unsloth/studio, or the worker writes
    #unsloth_compiled_cache/ into the current directory - this repo
    from utils.paths.storage_roots import setup_cache_env
    setup_cache_env()
    from utils.hf_cache_settings import child_environment_for_spawn, get_hf_cache_paths
    from utils.native_path_leases import (native_path_secret_removed_for_child_start,
                                          run_without_native_path_secret)

    ctx = mp.get_context("spawn")
    cache_env = get_hf_cache_paths().child_env({})
    with child_environment_for_spawn(cache_env), native_path_secret_removed_for_child_start():
        events, stop = ctx.Queue(), ctx.Queue()
        worker = ctx.Process(
            target=run_without_native_path_secret,
            args=("core.training.worker", "run_training_process", cache_env),
            kwargs={"event_queue": events, "stop_queue": stop, "config": config},
            daemon=True,
        )
        worker.start()

    started = time.time()
    output_dir, result = None, None
    last_status = None
    try:
        while result is None:
            try:
                event = events.get(timeout=5)
            except queue.Empty:
                if not worker.is_alive():
                    result = f"worker exited with code {worker.exitcode} without a result"
                continue
            kind = event.get("type")
            if kind == "status" and event.get("message") != last_status:
                last_status = event["message"]
                print(f"[{time.time() - started:6.0f}s] {last_status}", flush=True)
            elif kind == "progress" and event.get("step"):
                line = (f"step {event['step']}/{event.get('total_steps')}"
                        f"  epoch {event.get('epoch') or 0:.2f}")
                if event.get("loss") is not None:
                    line += f"  loss {event['loss']:.4f}"
                if event.get("eval_loss") is not None:
                    line += f"  eval_loss {event['eval_loss']:.4f}"
                print(f"[{time.time() - started:6.0f}s] {line}", flush=True)
            elif kind == "warning":
                print(f"warning: {event.get('message')}", flush=True)
            elif kind == "output_dir":
                output_dir = event["output_dir"]
                print(f"output: {output_dir}", flush=True)
            elif kind == "error":
                result = event.get("error") or "unknown error"
                if event.get("stack"):
                    print(event["stack"], file=sys.stderr)
            elif kind == "complete":
                result = "ok" if event.get("output_dir") else "stopped without saving"
                output_dir = event.get("output_dir") or output_dir
    except KeyboardInterrupt:
        print("stopping - the worker saves what it has", flush=True)
        stop.put({"type": "stop", "save": True})
        worker.join(timeout=600)
        return 130
    worker.join(timeout=120)

    minutes = (time.time() - started) / 60
    if result != "ok":
        print(f"training failed after {minutes:.0f} min: {result}", file=sys.stderr)
        return 1
    print(f"training done in {minutes:.0f} min: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
