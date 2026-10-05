"""Generate the synthetic raw datasets into ./data (see factor_framework/synthetic_data.py)."""
import argparse
import time

from factor_framework.synthetic_data import SimConfig, generate

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=SimConfig.seed)
    ap.add_argument("--n-us", type=int, default=SimConfig.n_us)
    ap.add_argument("--n-cn", type=int, default=SimConfig.n_cn)
    args = ap.parse_args()
    t0 = time.time()
    generate(SimConfig(seed=args.seed, n_us=args.n_us, n_cn=args.n_cn))
    print(f"elapsed {time.time() - t0:.1f}s")
