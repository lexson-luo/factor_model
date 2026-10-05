"""Run the full factor risk framework end to end and write reports to ./output.

    python generate_data.py     # once: create synthetic raw data in ./data
    python run_framework.py
"""
import argparse
import time
from pathlib import Path

from factor_framework.config import DATA_DIR, OUTPUT_DIR
from factor_framework.pipeline import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DATA_DIR)
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = ap.parse_args()
    if not (args.data / "trading/positions_eod.csv.gz").exists():
        from factor_framework.synthetic_data import SimConfig, generate
        generate(SimConfig(out_dir=args.data))
    t0 = time.time()
    run(args.data, args.out)
    print(f"done in {time.time() - t0:.0f}s -> {args.out}")
