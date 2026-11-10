"""Driver for the LAGraph demo binaries."""

import subprocess
import tempfile
import time
from pathlib import Path

from bench import parsers
from bench.parsers import Parsed

ROOT = Path(__file__).resolve().parents[3]
BIN = ROOT / "deps" / "bin"

SOURCES_HEADER = "%%MatrixMarket matrix array real general\n%\n{n} 1\n"


def write_sources(path: Path, sources: list[int]) -> None:
    """LAGraph reads 1-based source ids; one trial per row."""
    body = "\n".join(str(s + 1) for s in sources)
    path.write_text(SOURCES_HEADER.format(n=len(sources)) + body + "\n")


def build_command(algo: str, variant: str, mtx: Path, sources_file: Path | None, delta: int) -> list[str]:
    from config.experiment import LAGRAPH_BIN
    cmd = [str(BIN / LAGRAPH_BIN[(algo, variant)]), str(mtx)]
    if algo in ("bfs", "sssp"):
        cmd.append(str(sources_file))
    if algo == "sssp":
        cmd.append(str(delta))
    return cmd


def run(algo: str, variant: str, mtx: Path, source: int | None, iterations: int,
        delta: int, prefix: list[str], env: dict, timeout: float, log_path: Path) -> tuple[Parsed, dict]:
    """One process run. For bfs/sssp the source is repeated `iterations` times,
    so that a run yields `iterations` timed trials on the same source."""
    tmp = None
    if algo in ("bfs", "sssp"):
        tmp = Path(tempfile.mkstemp(suffix=".mtx", prefix="sources_")[1])
        write_sources(tmp, [source] * iterations)
    cmd = prefix + build_command(algo, variant, mtx, tmp, delta)
    started = time.monotonic()
    status, out, exit_note = "ok", "", None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        out = proc.stdout + "\n--- stderr ---\n" + proc.stderr
        if proc.returncode != 0:
            status = "error"
            exit_note = parsers.exit_reason(proc.returncode)
    except subprocess.TimeoutExpired as e:
        status = "timeout"
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    e2e_ms = (time.monotonic() - started) * 1000
    log_path.write_text(" ".join(cmd) + "\n\n" + out)
    parsed = parsers.parse_lagraph(algo, out, variant)
    if status == "error":
        oom = parsers.detect_oom(out)
        status, parsed.result_value = ("oom", oom) if oom else (status, exit_note)
    return parsed, {"status": status, "e2e_ms": e2e_ms, "cmd": cmd}
