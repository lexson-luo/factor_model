"""Stress testing (Sections 1.1 and 2.3).

Four complementary tests, all applied to *current* holdings:

1. Hypothetical factor scenarios from ``config.HYPOTHETICAL_SCENARIOS``, shocks
   in units of today's forecast factor vol (portable across regimes), or
   absolute returns ("abs:-0.10").  Slow-factor shocks use the monitoring layer.
2. Historical factor replay: estimated factor returns of embedded stress days.
3. Model-free replay: actual stock-level returns of a past stress day applied
   to today's holdings (the most robust test - needs no model).
4. Liquidity stress: days to liquidate at a participation cap and the cost of
   doing so with stressed spreads.
5. Internal crowding (crowding level 3): firm-wide positions against ADV, teams
   on the same side, and the cost if every team had to exit at once.
Shocks on factors that the crowding monitor flags as crowded are scaled up.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .attribution import AttributionResult
from .config import HYPOTHETICAL_SCENARIOS
from .data_loader import EquityPanel


def _current(att: AttributionResult, s: str):
    b = att.books[s]
    last = b.shares_eod.index[b.shares_eod.abs().sum(axis=1) > 0][-1]
    t = b.dates.get_loc(last)
    if b.market == "CRYPTO":
        h = (b.shares_eod.iloc[t] * b.mark.iloc[t]).values
    else:
        h = (b.shares_eod.iloc[t] * b.mark.iloc[t] * b.usd.iloc[t]).fillna(0).values
    return b, t, np.nan_to_num(h)


def hypothetical_scenarios(att: AttributionResult, models: dict, risk: dict,
                           scenarios: dict = HYPOTHETICAL_SCENARIOS, crowding_mult: dict | None = None) -> pd.DataFrame:
    """crowding_mult: model -> {factor: multiplier >= 1} from the factor-crowding monitor;
    sigma-unit shocks on crowded factors are scaled up (Section 2.2, crowding level 2)."""
    crowding_mult = crowding_mult or {}
    rows = []
    for s, b in att.books.items():
        bk, t, h = _current(att, s)
        fm, rm = models[b.market], risk[b.market]
        tt = min(t + 1, len(fm.expo.dates) - 1)       # exposures for the next session
        X = np.nan_to_num(fm.expo.X[tt])
        x = pd.Series(X.T @ h, index=fm.factor_returns.columns)
        vol = rm.factor_vol(tt)
        xs = None
        if fm.X_slow_perp is not None:
            xs = pd.Series(np.nan_to_num(fm.expo.X_slow[tt]).T @ h, index=fm.expo.slow_factors)
            slow_vol = fm.slow_returns.iloc[-250:].std()
        cm = crowding_mult.get(b.market, {})
        for name, sc in scenarios.items():
            pnl = 0.0
            pnl_c = 0.0
            for key, shock in sc["shocks"].items():
                is_abs = isinstance(shock, str) and shock.startswith("abs:")
                val = float(shock[4:]) if is_abs else float(shock)
                target_model = None
                fac = key
                if ":" in key:
                    target_model, fac = key.split(":", 1)
                if target_model == "slow":
                    if xs is not None and fac in xs:
                        move = xs[fac] * (val if is_abs else val * slow_vol[fac])
                        pnl += move
                        pnl_c += move
                    continue
                if target_model == "crypto" and b.market != "CRYPTO":
                    continue
                if target_model is None and b.market == "CRYPTO" and fac == "market":
                    continue
                if target_model == "crypto":
                    fac = fac if fac == "market" else f"sec_{fac}"
                if fac not in x:
                    continue
                move = x[fac] * (val if is_abs else val * vol[fac])
                pnl += move
                pnl_c += move * (1.0 if is_abs else cm.get(fac, 1.0))
            # multi-day episodes: the shock is applied on each day (directional, not diversifying)
            rows.append({"strategy": s, "scenario": name, "pnl_usd": pnl * sc.get("days", 1),
                         "pnl_usd_crowding_scaled": pnl_c * sc.get("days", 1), "gmv_usd": np.abs(h).sum()})
    df = pd.DataFrame(rows)
    df["pnl_pct_gmv"] = df.pnl_usd / df.gmv_usd
    return df


def historical_factor_replay(att: AttributionResult, models: dict, episodes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for s, b in att.books.items():
        bk, t, h = _current(att, s)
        fm = models[b.market]
        tt = min(t + 1, len(fm.expo.dates) - 1)
        x = np.nan_to_num(fm.expo.X[tt]).T @ h
        for ep in episodes[episodes.market == b.market].itertuples():
            k = fm.factor_returns.index.searchsorted(ep.date)
            if k >= len(fm.factor_returns):
                continue
            f = np.nan_to_num(fm.factor_returns.iloc[k].values)
            rows.append({"strategy": s, "episode": ep.episode, "date": fm.factor_returns.index[k].date(),
                         "pnl_usd": float(x @ f), "gmv_usd": np.abs(h).sum()})
    return pd.DataFrame(rows)


def stock_level_replay(att: AttributionResult, panels: dict, models: dict, episodes: pd.DataFrame) -> pd.DataFrame:
    """Model-free: apply the actual return of each stock on the stress day to today's position.
    Names not trading then fall back to their factor-implied return."""
    rows = []
    for s, b in att.books.items():
        bk, t, h = _current(att, s)
        p, fm = panels[b.market], models[b.market]
        ret = p.ret if isinstance(p, EquityPanel) else p.ret
        for ep in episodes[episodes.market == b.market].itertuples():
            k = ret.index.searchsorted(ep.date)
            if k >= len(ret):
                continue
            r = ret.iloc[k].values
            implied = np.nan_to_num(fm.expo.X[k]) @ np.nan_to_num(fm.factor_returns.iloc[k].values)
            r_used = np.where(np.isfinite(r), r, implied)
            rows.append({"strategy": s, "episode": ep.episode, "date": ret.index[k].date(),
                         "pnl_usd": float(np.sum(h * r_used)),
                         "coverage_pct": float(np.sum(np.abs(h) * np.isfinite(r)) / max(np.abs(h).sum(), 1))})
    return pd.DataFrame(rows)


def liquidity_stress(att: AttributionResult, panels: dict, participation: float = 0.2,
                     spread_mult: float = 3.0, impact_coef: float = 0.3) -> pd.DataFrame:
    rows = []
    for s, b in att.books.items():
        bk, t, h = _current(att, s)
        p = panels[b.market]
        if isinstance(p, EquityPanel):
            adv = p.adv_usd.iloc[min(t + 1, len(p.dates) - 1)].values
            spread = p.spread_bps.iloc[t].values / 1e4
            vol = p.ret.iloc[max(0, t - 20):t + 1].std().values
        else:
            adv = p.volume_usd.iloc[max(0, t - 14):t + 1].mean().values
            spread = np.full(len(h), 5e-4)
            vol = p.ret.iloc[max(0, t - 20):t + 1].std().values
        held = np.abs(h) > 0
        adv = np.where(np.isfinite(adv) & (adv > 0), adv, np.nan)
        days = np.abs(h) / (participation * adv)
        part = np.minimum(np.abs(h) / adv, 1)
        cost = np.abs(h) * (spread_mult * np.nan_to_num(spread) / 2 + impact_coef * np.nan_to_num(vol) * np.sqrt(np.nan_to_num(part)))
        gmv = np.abs(h).sum()
        rows.append({"strategy": s, "gmv_usd": gmv,
                     "pct_gmv_liquid_1d": np.abs(h)[held & (days <= 1)].sum() / gmv,
                     "pct_gmv_over_5d": np.abs(h)[held & (days > 5)].sum() / gmv,
                     "max_days_to_liquidate": np.nanmax(days[held]) if held.any() else 0.0,
                     "stressed_liquidation_cost_usd": np.nansum(cost[held]),
                     "stressed_cost_bps_gmv": np.nansum(cost[held]) / gmv * 1e4})
    return pd.DataFrame(rows)


def internal_crowding(att: AttributionResult, panels: dict, teams: dict, participation: float = 0.2,
                      impact_coef: float = 0.3, top: int = 15) -> dict:
    """Crowding level 3: the firm crowding itself.  Firm-wide position per stock against ADV,
    number of teams on the same side, and the cost if every team had to exit at once (same-side
    flows compete, no internal crossing) versus each team exiting alone."""
    summary, names = [], []
    for mkt in sorted({b.market for b in att.books.values()}):
        books = {s: b for s, b in att.books.items() if b.market == mkt}
        p = panels[mkt]
        if len(books) < 2 or not isinstance(p, EquityPanel):
            continue
        last = min(b.shares_eod.index[b.shares_eod.abs().sum(1) > 0][-1] for b in books.values())
        t = p.dates.get_loc(last)
        px = np.nan_to_num((p.close.iloc[t] * p.usd_per_local.iloc[t]).values)
        Q = pd.DataFrame({s: b.shares_eod.iloc[t].values for s, b in books.items()}, index=p.tickers).fillna(0)
        adv = p.adv_shares.iloc[min(t + 1, len(p.dates) - 1)].values
        adv = np.where(np.isfinite(adv) & (adv > 0), adv, np.nan)
        vol = p.ret.iloc[max(0, t - 20):t + 1].std().values
        hs = p.spread_bps.iloc[t].values / 2e4
        longs, shorts = Q.clip(lower=0).sum(1).values, (-Q.clip(upper=0)).sum(1).values
        net = Q.sum(1).values
        def cost(q):
            q = np.abs(q)
            return np.nansum(q * px * (np.nan_to_num(hs) + impact_coef * np.nan_to_num(vol) * np.sqrt(np.nan_to_num(q / adv))))
        standalone = sum(cost(Q[s].values) for s in books)
        joint = cost(longs) + cost(shorts)
        team_of = pd.Series(teams)
        n_long = (Q > 0).T.groupby(team_of.reindex(Q.columns).values).any().sum().values
        n_short = (Q < 0).T.groupby(team_of.reindex(Q.columns).values).any().sum().values
        same_side = np.maximum(n_long, n_short)
        gross_firm = np.abs(Q.values * px[:, None]).sum()
        dtu = np.abs(net) / (participation * adv)
        held = np.abs(Q.values).sum(1) > 0
        summary.append({"market": mkt, "as_of": last.date(), "firm_gross_usd": gross_firm,
                        "names_held": int(held.sum()), "names_2plus_teams_same_side": int((same_side >= 2).sum()),
                        "gross_in_shared_names_pct": np.abs(Q.values * px[:, None])[same_side >= 2].sum() / gross_firm,
                        "max_firm_days_to_unwind": np.nanmax(dtu[held]),
                        "standalone_exit_cost_usd": standalone, "joint_exit_cost_usd": joint,
                        "crowding_premium_usd": joint - standalone})
        df = pd.DataFrame({"market": mkt, "ticker": p.tickers, "firm_net_usd": net * px,
                           "firm_gross_usd": np.abs(Q.values).sum(1) * px, "pct_adv": np.abs(net) / adv,
                           "days_to_unwind": dtu, "teams_same_side": same_side,
                           "strategies": [",".join(c for c in Q.columns if Q.loc[tk, c] != 0) for tk in p.tickers]})
        names.append(df[held].sort_values("days_to_unwind", ascending=False).head(top))
    return {"summary": pd.DataFrame(summary), "top_names": pd.concat(names) if names else pd.DataFrame()}
