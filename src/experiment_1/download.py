"""Download and unpack SuiteSparse datasets into data/<name>/<name>.mtx.

Idempotent: a dataset whose .mtx is already present and listed in
data/manifest.json is skipped. The archive size is checked against
Content-Length and its sha256 is recorded in the manifest."""

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from config.datasets import BY_NAME, DATASETS  # noqa: E402

DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def fetch(ds, manifest: dict) -> None:
    out_dir = DATA / ds.name
    mtx = out_dir / f"{ds.name}.mtx"
    if mtx.exists() and ds.name in manifest:
        print(f"[skip] {ds.name}")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    tar_path = DATA / f"{ds.name}.tar.gz"
    with requests.get(ds.url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        sha = hashlib.sha256()
        got = 0
        with open(tar_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc=ds.name) as bar:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                sha.update(chunk)
                got += len(chunk)
                bar.update(len(chunk))
    if total and got != total:
        raise RuntimeError(f"{ds.name}: size mismatch {got} != {total}")
    member = f"{ds.name}/{ds.name}.mtx"
    with tarfile.open(tar_path) as tf:
        src = tf.extractfile(member)
        with open(mtx, "wb") as dst:
            while chunk := src.read(1 << 24):
                dst.write(chunk)
    tar_path.unlink()
    manifest[ds.name] = {"url": ds.url, "archive_bytes": got, "archive_sha256": sha.hexdigest(),
                         "mtx_bytes": mtx.stat().st_size}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="subset of datasets (default: all)")
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    manifest = load_manifest()
    for ds in [BY_NAME[n] for n in args.names] or DATASETS:
        fetch(ds, manifest)


if __name__ == "__main__":
    main()
