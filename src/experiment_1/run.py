#!/usr/bin/env python3
"""Benchmark runner: builds the series, executes it and appends measurements.

Every finished process run is written to results/measurements.csv immediately,
so a series can be interrupted and resumed with --resume."""

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from bench import env as bench_env  # noqa: E402
from bench.drivers import lagraph as lagraph_driver  # noqa: E402
from bench.drivers import spla as spla_driver
from bench.schema import MEASUREMENTS, Row, append, done_cells  # noqa: E402

from config.datasets import DATASETS  # noqa: E402
from config.experiment import (  # noqa: E402
    ALGOS,
    CELL_TIMEOUT_S,
    ORDER_SEED,
    SCHEMA_VERSION,
    SSSP_DELTA,
    VARIANTS,
    iterations,
)

DATA = ROOT / "data"
PROPERTIES = DATA / "properties.json"
SOURCES_DIR = ROOT / "config" / "sources"
RAW = ROOT / "results" / "raw"


class Task:
    def __init__(self, algo, tool, backend, variant, dataset, source, iters, props,
                 bin_variant=None):
        self.algo, self.tool, self.backend, self.variant = algo, tool, backend, variant
        self.dataset, self.source, self.iters, self.props = dataset, source, iters, props
        # which binary to run; differs from `variant` when the series is labelled
        # (allcores, pocl) but still uses the default binaries
        self.bin_variant = bin_variant or variant

    @property
    def key(self):
        return (self.algo, self.tool, self.backend, self.variant, self.dataset,
                "" if self.source is None else str(self.source))

    def __str__(self):
        src = "" if self.source is None else f" src={self.source}"
        return (f"{self.algo:4s} {self.tool}-{self.backend} {self.variant:8s} "
                f"{self.dataset:18s} iters={self.iters}{src}")


def load_props() -> dict:
    if not PROPERTIES.exists():
        sys.exit("data/properties.json is missing - run scripts/data/inspect_graphs.py first")
    return json.loads(PROPERTIES.read_text())


def sources_for(dataset: str, n: int) -> list[int]:
    path = SOURCES_DIR / f"{dataset}.json"
    if not path.exists():
        sys.exit(f"{path} is missing - run scripts/data/pick_sources.py first")
    return json.loads(path.read_text())["sources"][:n]


def build_tasks(args, props: dict) -> list[Task]:
    tasks = []
    for ds in DATASETS:
        if args.dataset and ds.name not in args.dataset:
            continue
        if ds.name not in props:
            continue
        p = props[ds.name]
        iters = args.iters or iterations(p["n_edges"])
        for algo in args.algo:
            if ds.pr_only and algo != "pr":
                continue
            srcs = sources_for(ds.name, args.sources) if algo in ("bfs", "sssp") else [None]
            for tool, backend in [("lagraph", "cpu"), ("spla", "cpu"), ("spla", "gpu")]:
                if args.tool and tool not in args.tool:
                    continue
                if args.backend and backend not in args.backend:
                    continue
                variants = VARIANTS[algo] if tool == "lagraph" else ["default"]
                if args.series_variant:
                    # a labelled series (allcores, pocl) runs the default binaries only,
                    # otherwise two binaries would collapse into one cell key
                    variants = ["default"]
                for variant in variants:
                    if args.variant and variant not in args.variant:
                        continue
                    v = args.series_variant or variant
                    for src in srcs:
                        tasks.append(Task(algo, tool, backend, v, ds.name, src, iters, p,
                                          bin_variant=variant))
    random.Random(ORDER_SEED).shuffle(tasks)
    return tasks


def rows_for(task: Task, parsed, meta, run_id: str, log_rel: str) -> list[Row]:
    def row(trial, phase, time_ms, **kw):
        return Row(run_id=run_id, schema_version=SCHEMA_VERSION, algo=task.algo, tool=task.tool,
                   backend=task.backend, variant=task.variant, dataset=task.dataset,
                   n_vertices=task.props["n_vertices"], n_edges=task.props["n_edges"],
                   source_vertex=task.source, trial=trial, phase=phase, time_ms=time_ms,
                   iterations=parsed.iterations, result_value=kw.pop("result_value", parsed.result_value),
                   threads=parsed.threads, status=kw.pop("status", meta["status"]), raw_log=log_rel)

    rows = [row(0, "e2e", round(meta["e2e_ms"], 3))]
    if parsed.warmup_ms is not None:
        rows.append(row(0, "warmup", round(parsed.warmup_ms, 3)))
    for i, t in enumerate(parsed.trials_ms, start=1):
        rows.append(row(i, "steady", round(t, 3)))
    return rows


def execute(task: Task, run_id: str, timeout: float, platform: int = 0,
            spla_build: str = "") -> list[Row]:
    prefix, environ = bench_env.run_env(task.variant)
    log_dir = RAW / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    name = "_".join(str(x) for x in task.key if x != "") + ".log"
    log = log_dir / name
    mtx = DATA / task.dataset / f"{task.dataset}.mtx"
    if task.tool == "lagraph":
        parsed, meta = lagraph_driver.run(task.algo, task.bin_variant, mtx, task.source, task.iters,
                                          SSSP_DELTA, prefix, environ, timeout, log)
    else:
        parsed, meta = spla_driver.run(task.algo, task.backend, mtx, task.source, task.iters,
                                       prefix, environ, timeout, log, platform=platform,
                                       build=spla_build)
        if task.algo == "pr" and meta["status"] == "ok":
            parsed.iterations = probe_pr_iterations(task, prefix, environ, timeout, log_dir,
                                                    platform)
    return rows_for(task, parsed, meta, run_id, str(log.relative_to(ROOT)))


def probe_pr_iterations(task: Task, prefix, environ, timeout: float, log_dir: Path,
                        platform: int = 0) -> int | None:
    """The release build of Spla prints nothing per iteration, so the iteration
    count comes from one extra run of the diagnostic build (not timed)."""
    mtx = DATA / task.dataset / f"{task.dataset}.mtx"
    log = log_dir / f"pr_{task.backend}_{task.dataset}_iterations.log"
    try:
        parsed, meta = spla_driver.run("pr", task.backend, mtx, None, 1, prefix, environ,
                                       timeout, log, platform=platform, diag=True)
    except Exception as exc:  # a probe must never fail the measurement
        print(f"    (iteration probe failed: {exc})")
        return None
    return parsed.iterations if meta["status"] == "ok" else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--algo", nargs="*", default=ALGOS, choices=ALGOS)
    ap.add_argument("--tool", nargs="*", choices=["lagraph", "spla"])
    ap.add_argument("--backend", nargs="*", choices=["cpu", "gpu"])
    ap.add_argument("--dataset", nargs="*", choices=[d.name for d in DATASETS])
    ap.add_argument("--variant", nargs="*", help="filter on the tool variant (default/parent/nosort)")
    ap.add_argument("--series-variant", help="label rows with this variant, e.g. allcores or pocl")
    ap.add_argument("--sources", type=int, default=8, help="how many source vertices for bfs/sssp")
    ap.add_argument("--iters", type=int,
                    help="override the per-size-class iteration count (used by the POCL series, "
                         "where one iteration can take a minute)")
    ap.add_argument("--timeout", type=float, default=CELL_TIMEOUT_S)
    ap.add_argument("--platform", type=int, default=0,
                    help="OpenCL platform for Spla (0 = NVIDIA here, 1 = POCL)")
    ap.add_argument("--spla-build", default="", choices=["", "anydev"],
                    help="use the patched Spla build that accepts non-GPU OpenCL devices")
    ap.add_argument("--cooldown", type=float, default=0, help="seconds to sleep between runs")
    ap.add_argument("--limit", type=int, help="run at most N cells")
    ap.add_argument("--resume", action="store_true", help="skip cells already in measurements.csv")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()

    props = load_props()
    tasks = build_tasks(args, props)
    if args.resume:
        done = done_cells()
        tasks = [t for t in tasks if t.key not in done]
    if args.limit:
        tasks = tasks[:args.limit]

    print(f"run_id={args.run_id}  cells={len(tasks)}  measurements={MEASUREMENTS}")
    if args.dry_run:
        for t in tasks:
            print("  ", t)
        return

    bench_env.snapshot(args.run_id, {"n_cells": len(tasks), "argv": sys.argv[1:]})
    started = time.monotonic()
    for i, task in enumerate(tasks, 1):
        t0 = time.monotonic()
        rows = execute(task, args.run_id, args.timeout, args.platform, args.spla_build)
        append(rows)
        status = rows[0].status
        steady = [r.time_ms for r in rows if r.phase == "steady"]
        median = sorted(steady)[len(steady) // 2] if steady else None
        print(f"[{i}/{len(tasks)}] {task} -> {status} "
              f"steady_median={median if median is None else round(median, 2)}ms "
              f"({time.monotonic() - t0:.1f}s)", flush=True)
        if args.cooldown:
            time.sleep(args.cooldown)
    print(f"done in {(time.monotonic() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
