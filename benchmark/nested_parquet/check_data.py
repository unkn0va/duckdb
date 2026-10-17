#!/usr/bin/env python3
"""Check that the data folder of the benchmark is complete and intact, against data_manifest.tsv (next to this script):
every file it lists must exist with the listed size and - with --full - the listed SHA-256 checksum.

The manifest lists the parquet files of the paper's archive (nested-parquet-datasets/...) and the files that
prepare_data.sh generates for the selectivity experiment (selectivity_random/..., selectivity_sorted/...; the generated
files are byte-identical only when written with pyarrow 26.0.0).

Usage: check_data.py <data folder> [--full] [--only <prefix>]
  --full           also compare SHA-256 checksums (reads all ~17 GB; a few minutes)
  --only <prefix>  check only the files whose path starts with <prefix> (e.g. nested-parquet-datasets/)
Exit status: 0 if all files are fine, 1 otherwise.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__)
        return 2
    data_dir, full = args[0], "--full" in args
    only = args[args.index("--only") + 1] if "--only" in args else ""
    problems, checked = [], 0
    with open(os.path.join(HERE, "data_manifest.tsv")) as manifest:
        for line in manifest:
            if line.startswith("#") or not line.strip():
                continue
            path, size, checksum = line.rstrip("\n").split("\t")
            if not path.startswith(only):
                continue
            checked += 1
            full_path = os.path.join(data_dir, path)
            if not os.path.isfile(full_path):
                problems.append(f"MISSING     {path}")
                continue
            actual_size = os.path.getsize(full_path)
            if actual_size != int(size):
                problems.append(f"WRONG SIZE  {path}: {actual_size} bytes, expected {size}")
                continue
            if full:
                print(f"  checksum {path}", flush=True)
                if sha256(full_path) != checksum:
                    problems.append(f"WRONG SHA256 {path}")
    if problems:
        print("\n" + "!" * 78)
        print(f"!!! DATA CHECK FAILED: {len(problems)} of {checked} files are missing or damaged")
        print("!" * 78)
        for problem in problems:
            print("  " + problem)
        print("See SERVER.md, 'Common problems'.")
        return 1
    what = "sizes and SHA-256 checksums" if full else "sizes (add --full to also compare checksums)"
    print(f"OK: all {checked} files present, {what} match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
