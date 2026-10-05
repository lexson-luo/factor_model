"""Limit framework (Section 1.1): limits on the exposures that matter, not just dollars.

Per strategy and date:
  * beta-adjusted net exposure (% of gross)
  * style factor exposures (std units per $ of gross)
  * industry net exposure (% of gross)
  * single-name concentration (% of gross) and position size vs ADV
  * predicted volatility (annualised, % of gross)
  * expected loss in a 3-sigma volatility or liquidity shock (time-series factors)
  * soft thresholds on slow (monitoring-layer) factor exposures
Status is OK below 80% utilisation, WARN from 80%, BREACH above 100%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .attribution import AttributionResult
from .config import LIMITS, TRADING_DAYS, LimitConfig
from .data_loader import EquityPanel


def _status(u: float) -> str:
    return "BREACH" if u > 1 else ("WARN" if u >= 0.8 else "OK")


def limit_history(att: AttributionResult, panels: dict, models: dict, risk: dict,
                  cfg: LimitConfig = LIMITS, shock_betas: dict | None = None) -> pd.DataFrame:
    """shock_betas: strategy -> rolling empirical 3-sigma shock P&L (diagnostics.rolling_shock_betas).
    The shock-loss limit uses the worse of the model-implied and the empirical estimate."""
    shock_betas = shock_betas or {}
    rows = []
    for s, b in att.books.items():
        fm, rm, p = models[b.market], risk[b.market], panels[b.market]
        g = fm.expo.groups
        style = [f for f in fm.factor_returns.columns if g[f] == "style"]
        inds = [f for f in fm.factor_returns.columns if g[f] == "industry"]
        vol_lim = cfg.predicted_vol_annual_pct_gmv.get(s, cfg.predicted_vol_annual_pct_gmv["default"])
        ex = att.exposures[att.exposures.strategy == s].pivot(index="date", columns="factor", values="exposure_pct_gmv")
        adv_sh = p.adv_shares if isinstance(p, EquityPanel) else None
        for date, e in ex.iterrows():
            t = b.dates.get_loc(date)
            h = b.h.values[t]
            gmv = np.abs(h).sum()
            if gmv <= 0:
                continue
            checks = {"beta_adj_net": (abs(e.get("beta_adj_net", 0)), cfg.beta_adj_net_pct_gross)}
            for f in style:
                checks[f"style:{f}"] = (abs(e.get(f, 0)), cfg.style_exposure_abs)
            ind_max = max((abs(e.get(f, 0)) for f in inds), default=0)
            checks["industry_net_max"] = (ind_max, cfg.industry_net_pct_gross)
            name_lim = cfg.max_name_pct_gross.get(s, cfg.max_name_pct_gross["default"])
            checks["max_name"] = (np.abs(h).max() / gmv, name_lim)
            if adv_sh is not None:
                n = np.abs(b.shares_eod.values[t - 1]) if t > 0 else np.zeros_like(h)
                a = adv_sh.values[t]
                pa = np.where(a > 0, n / a, 0)
                checks["max_pct_adv"] = (np.nanmax(pa), cfg.max_pct_adv)
            if np.isfinite(rm.F[t]).all():
                pr = rm.portfolio(t, h)
                checks["predicted_vol"] = (pr.total_vol * np.sqrt(TRADING_DAYS) / gmv, vol_lim)
                # expected loss given a 3-sigma market-wide volatility / liquidity shock (model-implied)
                for k in ("vol_shock", "liq_shock"):
                    if k in rm.factors:
                        j = rm.factors.index(k)
                        exp_pnl = 3 * (rm.F[t][j] @ pr.exposures.values) / np.sqrt(rm.F[t][j, j])
                        emp = shock_betas.get(s)
                        emp_pnl = emp[k].get(date, np.nan) if emp is not None and k in emp else np.nan
                        loss = max(-exp_pnl, -np.nan_to_num(emp_pnl), 0.0)
                        checks[f"shock_loss:{k}"] = (loss / gmv, cfg.shock_loss_pct_gmv)
            for f in [c for c in e.index if str(c).startswith("slow:")]:
                checks[f] = (abs(e[f]), cfg.soft_slow_factor_abs)
            for k, (v, lim) in checks.items():
                rows.append({"date": date, "strategy": s, "limit": k, "value": v, "limit_value": lim,
                             "utilisation": v / lim, "soft": k.startswith("slow:")})
    df = pd.DataFrame(rows)
    df["status"] = df.utilisation.map(_status)
    return df


def current_status(hist: pd.DataFrame) -> pd.DataFrame:
    last = hist.groupby("strategy").date.transform("max")
    cur = hist[hist.date == last].copy()
    return cur.sort_values(["strategy", "utilisation"], ascending=[True, False])


def breach_log(hist: pd.DataFrame) -> pd.DataFrame:
    h = hist[(hist.status == "BREACH") & ~hist.soft].sort_values("date")
    if h.empty:
        return h
    h = h.copy()
    h["new_episode"] = h.groupby(["strategy", "limit"]).date.diff().dt.days.fillna(999) > 5
    ep = h[h.new_episode]
    dur = h.groupby(["strategy", "limit"]).size().rename("total_breach_days")
    return ep.merge(dur, on=["strategy", "limit"])[["date", "strategy", "limit", "value", "limit_value",
                                                     "utilisation", "total_breach_days"]]
