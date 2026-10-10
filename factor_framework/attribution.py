"""Layer 5 - P&L attribution (Section 3.5).

    Total P&L = Factor P&L + Residual P&L + FX P&L + Intraday trading P&L
                - Execution costs (delay + impact + commissions/fees)
                + Financing + Borrow + Funding

* Factor P&L     : start-of-day exposures (X_t^T h_{t-1}) times factor returns.
* Residual P&L   : holdings times specific returns; split further into the
                   slow-factor (monitoring layer) part and remaining specific.
* Basis P&L      : gap between the return the book earns and the return the
                   factor model is estimated on (crypto: primary-venue perp
                   marks vs venue-A spot, i.e. basis and venue moves; zero for
                   equities).
* FX P&L         : currency move on local-currency holdings.
* Trading P&L    : fills marked from the *decision* price to the close, i.e. the
                   P&L of trades executed at the price when the decision was made.
* Delay cost     : arrival - decision (signal-to-order latency / overnight gap).
* Impact cost    : fill - arrival (spread + market impact).
* Financing / borrow / funding are taken from prime-broker / venue statements.

The decomposition is exact by construction; the only gap to the official
books is booking differences, which are monitored as ``unexplained``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data_loader import CryptoPanel, EquityPanel, TradingData
from .estimation import FactorModel

COMPONENTS = ["factor", "slow_factor", "specific", "basis", "fx", "trading", "delay_cost", "impact_cost",
              "commissions", "financing", "borrow", "funding"]


@dataclass
class StrategyBook:
    """Aligned start-of-day holdings and returns for one strategy."""
    strategy: str
    market: str
    dates: pd.DatetimeIndex
    tickers: pd.Index
    shares_eod: pd.DataFrame
    h: pd.DataFrame               # start-of-day holdings, USD (EOD t-1 marked at t-1)
    ret: pd.DataFrame             # local return used for P&L
    usd: pd.Series                # USD per local unit
    mark: pd.DataFrame            # local close used to mark trades
    model_ret: pd.DataFrame       # return the factor model is estimated on (crypto: venue-A spot)


@dataclass
class AttributionResult:
    daily: pd.DataFrame           # index (date, strategy): components + totals
    factor_pnl: pd.DataFrame      # long: date, strategy, factor, group, pnl
    exposures: pd.DataFrame       # long: date, strategy, factor, exposure_usd, exposure_pct_gmv
    books: dict

    def by_reporting_day(self) -> pd.DataFrame:
        """Firm view on business days: weekend crypto P&L rolls into Monday."""
        d = self.daily.reset_index()
        d["report_date"] = d["date"] + pd.offsets.BDay(0)
        num = d.select_dtypes("number").columns
        return d.groupby(["report_date", "strategy"])[list(num)].sum()


class PnLAttributor:
    def __init__(self, panels: dict, models: dict, trading: TradingData):
        self.panels, self.models, self.td = panels, models, trading

    # ---------------- holdings ---------------- #
    def book(self, strategy: str) -> StrategyBook:
        mkt = self.td.market_of(strategy)
        p = self.panels[mkt]
        if isinstance(p, EquityPanel):
            sh = self.td.positions_wide(strategy, p.dates, p.tickers)
            prev = sh.shift(1).fillna(0.0)
            h = prev * p.close.shift(1).fillna(0) * p.usd_per_local.shift(1).values[:, None]
            ret = p.ret.fillna(0.0)
            return StrategyBook(strategy, mkt, p.dates, p.tickers, sh, h.fillna(0.0), ret, p.usd_per_local,
                                p.close, ret)
        assert isinstance(p, CryptoPanel)
        sh = self.td.positions_wide(strategy, p.dates, p.symbols)
        venue = p.ref["primary_venue"]
        mark = pd.DataFrame({s: p.perp[venue[s]][s] for s in p.symbols})
        prev = sh.shift(1).fillna(0.0)
        h = prev * mark.shift(1).fillna(0)
        ret = mark.pct_change().fillna(0.0)
        # the model is estimated on venue-A spot; where spot is missing, fall back to the book return
        model_ret = p.ret.reindex(index=p.dates, columns=p.symbols).where(lambda x: x.notna(), ret)
        return StrategyBook(strategy, mkt, p.dates, p.symbols, sh, h, ret, pd.Series(1.0, index=p.dates), mark,
                            model_ret)

    # ---------------- attribution ---------------- #
    def attribute(self, strategy: str):
        b = self.book(strategy)
        fm: FactorModel = self.models[b.market]
        e = fm.expo
        h = b.h.values
        r = b.ret.values
        usd = b.usd.values
        fx_ratio = np.r_[1.0, usd[1:] / usd[:-1]]
        hold = (h * r).sum(axis=1)
        fx = (h * (1 + r)).sum(axis=1) * (fx_ratio - 1)
        X = e.X
        valid = np.all(np.isfinite(X), 2)
        hv = np.where(valid, h, 0.0)
        x = np.einsum("tnk,tn->tk", np.nan_to_num(X), hv)          # USD exposures
        f = np.nan_to_num(fm.factor_returns.values)
        fpnl = x * f
        factor = fpnl.sum(axis=1)
        residual = hold - factor
        if fm.X_slow_perp is not None:
            xs = np.einsum("tnk,tn->tk", np.nan_to_num(fm.X_slow_perp), hv)
            slow = (xs * np.nan_to_num(fm.slow_returns.values)).sum(axis=1)
        else:
            xs, slow = None, np.zeros(len(b.dates))
        basis = (h * (r - b.model_ret.values)).sum(axis=1)       # book return vs model return
        specific = residual - slow - basis
        # holdings in currency -> FX applied after local return, expressed in USD at t
        fx_usd = fx

        # trades
        fl = self.td.fills[self.td.fills.strategy == strategy]
        di = b.dates.get_indexer(fl.date)
        ti = b.tickers.get_indexer(fl.ticker)
        ok = (di >= 0) & (ti >= 0)
        fl, di, ti = fl[ok], di[ok], ti[ok]
        u = usd[di]
        close = b.mark.values[di, ti]
        q = fl.quantity.values
        comp = {
            "trading": q * (close - fl.decision_price.values) * u,
            "delay_cost": -q * (fl.arrival_price.values - fl.decision_price.values) * u,
            "impact_cost": -q * (fl.price.values - fl.arrival_price.values) * u,
            "commissions": -(fl.commission.values + fl.fees.values) * u,
        }
        T = len(b.dates)
        agg = {k: np.bincount(di, weights=v, minlength=T) for k, v in comp.items()}
        fin = self.td.financing[self.td.financing.strategy == strategy].set_index("date").reindex(b.dates).fillna(0)
        off = self.td.official_pnl[self.td.official_pnl.strategy == strategy].set_index("date").reindex(b.dates)

        df = pd.DataFrame({
            "factor": factor, "slow_factor": slow, "specific": specific, "basis": basis, "fx": fx_usd,
            "trading": agg["trading"], "delay_cost": agg["delay_cost"], "impact_cost": agg["impact_cost"],
            "commissions": agg["commissions"], "financing": fin.financing_usd.values,
            "borrow": fin.borrow_usd.values, "funding": fin.funding_usd.values,
        }, index=b.dates)
        df["hold_pnl"] = hold
        df["total_attributed"] = df[COMPONENTS].sum(axis=1)
        df["official"] = off.pnl_usd.values
        df["unexplained"] = df["official"] - df["total_attributed"]
        gmv = np.abs(h).sum(axis=1)
        df["gmv_sod"] = gmv
        df["gmv_eod"] = off.gmv_usd.values
        df["traded_usd"] = np.bincount(di, weights=np.abs(q * fl.price.values * u), minlength=T)
        live = off.pnl_usd.notna().values
        df = df[live]
        df["strategy"] = strategy
        df["team"] = self.td.team_of(strategy)
        df["market"] = b.market

        # long-format factor P&L and exposures
        names = list(fm.factor_returns.columns)
        fp = pd.DataFrame(fpnl, index=b.dates, columns=names)[live]
        ex = pd.DataFrame(x, index=b.dates, columns=names)[live]
        if xs is not None:
            fp = pd.concat([fp, pd.DataFrame(xs * np.nan_to_num(fm.slow_returns.values), index=b.dates,
                                             columns=[f"slow:{c}" for c in fm.slow_returns.columns])[live]], axis=1)
            ex = pd.concat([ex, pd.DataFrame(xs, index=b.dates,
                                             columns=[f"slow:{c}" for c in fm.slow_returns.columns])[live]], axis=1)
        beta = e.beta_pred.reindex(index=b.dates, columns=b.tickers).fillna(1.0).values
        ex["beta_adj_net"] = (h * beta).sum(axis=1)[live]
        ex["net"] = h.sum(axis=1)[live]
        ex["gross"] = gmv[live]
        return df, fp, ex, b

    def run(self, strategies: list | None = None) -> AttributionResult:
        strategies = strategies or list(self.td.strategies.strategy)
        daily, fpl, exl, books = [], [], [], {}
        for s in strategies:
            df, fp, ex, b = self.attribute(s)
            daily.append(df.reset_index(names="date"))
            fm = self.models[b.market]
            groups = {**fm.expo.groups, **{f"slow:{c}": "slow" for c in fm.expo.slow_factors}}
            fpl.append(fp.reset_index(names="date").melt("date", var_name="factor", value_name="pnl")
                       .assign(strategy=s, model=b.market, group=lambda d: d.factor.map(groups)))
            gm = ex["gross"].replace(0, np.nan)
            el = ex.reset_index(names="date").melt("date", var_name="factor", value_name="exposure_usd")
            el["exposure_pct_gmv"] = el.exposure_usd.values / np.tile(gm.values, ex.shape[1])
            el["strategy"] = s
            el["model"] = b.market
            exl.append(el)
            books[s] = b
        daily = pd.concat(daily).set_index(["date", "strategy"]).sort_index()
        return AttributionResult(daily=daily, factor_pnl=pd.concat(fpl, ignore_index=True),
                                 exposures=pd.concat(exl, ignore_index=True), books=books)


# --------------------------------------------------------------------------- #
# Reconciliation, linking, cross-checks
# --------------------------------------------------------------------------- #
def reconciliation(daily: pd.DataFrame, abs_tol: float = 1000.0, bps_tol: float = 0.5) -> pd.DataFrame:
    d = daily.copy()
    d["tolerance"] = np.maximum(abs_tol, d.gmv_sod.fillna(0) * bps_tol / 1e4)
    d["break"] = d.unexplained.abs() > d.tolerance
    return d[["official", "total_attributed", "unexplained", "tolerance", "break"]]


def carino_link(component_returns: pd.DataFrame, total: pd.Series) -> pd.Series:
    """Carino (1999) linking: multi-period component returns that add to the compounded total."""
    R = (1 + total).prod() - 1
    k_total = np.log1p(R) / R if R != 0 else 1.0
    k_t = np.where(total != 0, np.log1p(total) / total.replace(0, np.nan), 1.0)
    k_t = pd.Series(np.nan_to_num(k_t, nan=1.0), index=total.index)
    return component_returns.mul(k_t / k_total, axis=0).sum()


def exposure_change_decomposition(expo: FactorModel, book: StrategyBook) -> pd.DataFrame:
    """Split day-on-day change in exposures into position-driven and exposure-drift parts."""
    X = np.nan_to_num(expo.expo.X)
    h = book.h.values
    names = list(expo.factor_returns.columns)
    pos = np.einsum("tnk,tn->tk", X[1:], h[1:] - h[:-1])
    drift = np.einsum("tnk,tn->tk", X[1:] - X[:-1], h[:-1])
    idx = book.dates[1:]
    return pd.concat({"position": pd.DataFrame(pos, idx, names), "drift": pd.DataFrame(drift, idx, names)}, axis=1)


def returns_based_crosscheck(daily: pd.DataFrame, exposures: pd.DataFrame, factor_returns: pd.DataFrame,
                             strategy: str, factors: list, window: int = 126) -> pd.DataFrame:
    """Sharpe (1992)-style regression of strategy returns on factor returns vs holdings exposures."""
    d = daily.xs(strategy, level="strategy")
    ret = (d.total_attributed / d.gmv_sod.replace(0, np.nan)).dropna()
    fr = factor_returns.reindex(ret.index)[factors].fillna(0)
    ex = exposures[(exposures.strategy == strategy) & exposures.factor.isin(factors)]
    hold = ex.pivot(index="date", columns="factor", values="exposure_pct_gmv").reindex(ret.index)[factors]
    rows = []
    for end in range(window, len(ret), 21):
        y = ret.iloc[end - window:end].values
        A = np.column_stack([np.ones(window), fr.iloc[end - window:end].values])
        b, *_ = np.linalg.lstsq(A, y, rcond=None)
        h_avg = hold.iloc[end - window:end].mean()
        for j, f in enumerate(factors):
            rows.append({"date": ret.index[end - 1], "factor": f, "returns_based": b[j + 1],
                         "holdings_based": h_avg[f]})
    return pd.DataFrame(rows)
