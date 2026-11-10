"""Driver for the Spla example binaries (one backend per process run)."""

import subprocess
import time
from pathlib import Path

from bench import parsers
from bench.parsers import Parsed

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "deps" / "bin"


def build_command(algo: str, backend: str, mtx: Path, source: int | None, iterations: int,
                  platform: int = 0, diag: bool = False, build: str = "") -> list[str]:
    """`build` picks a non-stock binary: "diag" for the per-iteration diagnostics,
    "anydev" for the POCL series (see scripts/patches/spla_any_device.patch)."""
    from config.experiment import FRONT_FACTOR, PR_ALPHA, PR_EPS, PUSH_PULL
    suffix = "_diag" if diag else (f"_{build}" if build else "")
    exe = BIN / f"spla_{algo}{suffix}"
    cmd = [str(exe), f"--mtxpath={mtx}", f"--niters={iterations}",
           "--run-ref=false",                       # the naive reference is far too slow
           f"--run-cpu={'true' if backend == 'cpu' else 'false'}",
           f"--run-gpu={'true' if backend == 'gpu' else 'false'}",
           f"--push-pull={PUSH_PULL}", f"--front-factor={FRONT_FACTOR}",
           f"--platform={platform}"]
    if algo in ("bfs", "sssp"):
        cmd.append(f"--source={source}")
    if algo == "pr":
        cmd += [f"--alpha={PR_ALPHA}", f"--eps={PR_EPS}"]
    return cmd


def run(algo: str, backend: str, mtx: Path, source: int | None, iterations: int,
        prefix: list[str], env: dict, timeout: float, log_path: Path,
        platform: int = 0, diag: bool = False, run_ref: bool = False,
        build: str = "") -> tuple[Parsed, dict]:
    cmd = prefix + build_command(algo, backend, mtx, source, iterations, platform, diag, build)
    if run_ref:
        cmd = [c.replace("--run-ref=false", "--run-ref=true") for c in cmd]
    started = time.monotonic()
    status, out, exit_note = "ok", "", None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        out = proc.stdout + "\n--- stderr ---\n" + proc.stderr
        if proc.returncode != 0:
            status = "error"
            exit_note = parsers.exit_reason(proc.returncode)
    except subprocess.TimeoutExpired as e:
        raw = e.stdout or ("" if isinstance(e.stdout, str) else b"")
        status = "timeout"
        out = raw if isinstance(raw, str) else raw.decode(errors="replace")
    e2e_ms = (time.monotonic() - started) * 1000
    log_path.write_text(" ".join(cmd) + "\n\n" + out)
    parsed = parsers.parse_spla(out, backend)
    oom = parsers.detect_oom(out)
    if oom:
        status = "oom"
        parsed.result_value = oom
    elif status == "ok" and not parsed.trials_ms and parsed.warmup_ms is None:
        status = "error"
        parsed.result_value = "no timings in output"
    elif exit_note:
        parsed.result_value = exit_note
    return parsed, {"status": status, "e2e_ms": e2e_ms, "cmd": cmd}
