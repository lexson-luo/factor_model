"""Global linking layer (Sections 3.2 'Linking local models' and 3.4).

Each local model (US, CN, CRYPTO) keeps its own factor covariance.  The global
layer only estimates the *cross-model* correlations:

1. Local factor returns are aligned on the firm reporting calendar (business
   days): returns between two reporting dates are summed, so CN holidays and
   crypto weekends roll into the next reporting day.
2. Cross correlations are estimated with an EWMA Newey-West adjustment
   (Gamma_0 + Gamma_1 + Gamma_1'), which corrects the downward bias caused by
   non-synchronous closes (CN closes before the US opens; crypto trades 24/7).
3. Diagonal blocks come from the local risk models; off-diagonal blocks are
   cross correlations times local volatilities; the result is repaired to be
   positive semi-definite.
4. A currency factor (CNY vs USD) captures FX risk on non-USD holdings.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import MODEL, ModelConfig
from .risk_model import RiskModel


def _psd(M: np.ndarray, floor: float = 1e-12) -> np.ndarray:
    M = 0.5 * (M + M.T)
    d, U = np.linalg.eigh(M)
    return (U * np.clip(d, floor, None)) @ U.T


@dataclass
class FirmRisk:
    date: pd.Timestamp
    total_vol: float
    standalone_vol: pd.Series         # by model block (incl. its specific risk)
    contribution: pd.Series           # Euler contribution by block
    factor_contrib: pd.Series         # by global factor
    diversification: float            # sum of standalone - total
    block_corr: pd.DataFrame


class GlobalRiskLayer:
    def __init__(self, risk_models: dict, factor_returns: dict, usd_per_cny: pd.Series,
                 calendar: pd.DatetimeIndex, cfg: ModelConfig = MODEL):
        self.rms, self.cfg = risk_models, cfg
        self.calendar = calendar
        self.blocks = {}
        cols, aligned = [], []
        for name, fr in factor_returns.items():
            c = fr.fillna(0).cumsum()
            a = c.reindex(c.index.union(calendar)).ffill().reindex(calendar).diff()
            a.columns = [f"{name}:{f}" for f in fr.columns]
            self.blocks[name] = list(a.columns)
            aligned.append(a)
        fx = np.log(usd_per_cny).reindex(usd_per_cny.index.union(calendar)).ffill().reindex(calendar).diff()
        aligned.append(fx.rename("FX:CNY").to_frame())
        self.blocks["FX"] = ["FX:CNY"]
        self.returns = pd.concat(aligned, axis=1).fillna(0.0)
        self.factors = list(self.returns.columns)

    def lead_lag(self) -> pd.DataFrame:
        r = self.returns
        rows = []
        pairs = [("US:market", "CN:market"), ("US:market", "CRYPTO:market"), ("CRYPTO:market", "US:crypto_beta"),
                 ("US:crypto_beta", "CRYPTO:market")]
        for a, b in pairs:
            if a in r and b in r:
                rows.append({"leader": a, "follower": b, "corr_same_day": r[a].corr(r[b]),
                             "corr_leader_lag1": r[a].shift(1).corr(r[b])})
        return pd.DataFrame(rows)

    def build(self):
        cfg = self.cfg
        R = self.returns.values
        T, K = R.shape
        lam = 0.5 ** (1 / cfg.corr_halflife)
        G0 = np.zeros((K, K)); G1 = np.zeros((K, K)); w = 0.0
        self.G = np.full((T, K, K), np.nan)
        fx_var = 0.0; fx_w = 0.0
        lv = 0.5 ** (1 / cfg.vol_halflife)
        ifx = self.factors.index("FX:CNY")
        for t in range(T):
            if t > cfg.cov_min_obs:
                S = (G0 + G1 + G1.T) / w
                sd = np.sqrt(np.clip(np.diag(S), 1e-14, None))
                C = S / np.outer(sd, sd)
                vol = np.zeros(K)
                M = np.zeros((K, K))
                for name, cols in self.blocks.items():
                    ii = [self.factors.index(c) for c in cols]
                    if name == "FX":
                        vol[ii] = np.sqrt(fx_var / max(fx_w, 1e-12))
                        M[np.ix_(ii, ii)] = vol[ii] ** 2
                        continue
                    rm: RiskModel = self.rms[name]
                    k = rm.dates.searchsorted(self.calendar[t], "right") - 1
                    Floc = rm.F[k] if k >= 0 else None
                    if Floc is None or not np.isfinite(Floc).all():
                        Floc = np.diag(np.diag(S)[ii])
                    M[np.ix_(ii, ii)] = Floc
                    vol[ii] = np.sqrt(np.clip(np.diag(Floc), 0, None))
                cross = C * np.outer(vol, vol)
                for name, cols in self.blocks.items():
                    ii = [self.factors.index(c) for c in cols]
                    cross[np.ix_(ii, ii)] = M[np.ix_(ii, ii)]
                self.G[t] = _psd(cross)
            rt = R[t]
            rp = R[t - 1] if t > 0 else np.zeros(K)
            G0 = lam * G0 + (1 - lam) * np.outer(rt, rt)
            G1 = lam * G1 + (1 - lam) * np.outer(rt, rp)
            w = lam * w + (1 - lam)
            fx_var = lv * fx_var + (1 - lv) * rt[ifx] ** 2; fx_w = lv * fx_w + (1 - lv)
        return self

    def firm_risk(self, t: int, x_by_model: dict, spec_var_by_model: dict) -> FirmRisk:
        """x_by_model: model -> pd.Series of USD exposures (local factor names); FX handled via 'FX'."""
        x = np.zeros(len(self.factors))
        for name, ex in x_by_model.items():
            for f, v in ex.items():
                key = f"{name}:{f}" if name != "FX" else f
                if key in self.factors:
                    x[self.factors.index(key)] += v
        G = self.G[t]
        Gx = G @ x
        spec_total = sum(spec_var_by_model.values())
        var = float(x @ Gx) + spec_total
        tot = np.sqrt(max(var, 1e-18))
        fc = pd.Series(x * Gx / tot, index=self.factors)
        contrib, standalone, xb = {}, {}, {}
        for name, cols in self.blocks.items():
            ii = [self.factors.index(c) for c in cols]
            sv = spec_var_by_model.get(name, 0.0)
            contrib[name] = fc.iloc[ii].sum() + sv / tot
            xi = np.zeros_like(x); xi[ii] = x[ii]
            xb[name] = xi
            standalone[name] = np.sqrt(max(xi @ G @ xi + sv, 0))
        names = list(self.blocks)
        bc = pd.DataFrame(np.eye(len(names)), index=names, columns=names)
        for a in names:
            for b in names:
                if a != b and standalone[a] > 0 and standalone[b] > 0:
                    bc.loc[a, b] = (xb[a] @ G @ xb[b]) / (standalone[a] * standalone[b])
        sa = pd.Series(standalone)
        return FirmRisk(date=self.calendar[t], total_vol=tot, standalone_vol=sa, contribution=pd.Series(contrib),
                        factor_contrib=fc, diversification=sa.sum() - tot, block_corr=bc)
