"""Intraday layer (Sections 2.2 'Additional factors for intraday strategies', 2.4, 3.4).

Uses 30-minute bars to

* define the intraday market factor from index-futures returns (futures lead the
  cash market and are the hedging instrument); each stock's exposure is its
  intraday beta, estimated with a lagged (Dimson) correction because concurrent
  30-minute betas are biased toward zero (Epps effect), shrunk toward the daily
  beta;
* estimate bar-level returns of the cross-sectional factors with the daily
  exposures X_t (overnight gap / opening auction = bar 0);
* add order-flow imbalance (buy minus sell volume) as an attribution-only factor -
  it is too close to an alpha signal for the daily risk model;
* normalise for intraday seasonality: bar risk forecasts scale the daily forecast
  by the U-shaped volatility profile;
* rebuild each strategy's position path from fills and attribute P&L bar by bar.

Summed over the day the intraday attribution reconciles to daily mark-to-market.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .attribution import AttributionResult
from .config import MODEL, ModelConfig
from .data_loader import EquityPanel, TradingData
from .estimation import FactorModel, _robust_clip, constrained_wls
from .risk_model import RiskModel


@dataclass
class IntradayResult:
    bar_factor_returns: pd.DataFrame      # MultiIndex (date, bar) x factors (+ index_futures, order_flow)
    vol_profile: pd.Series                # mean |bar return| by bar (U-shape)
    attribution: pd.DataFrame             # per (date, strategy)
    factor_detail: pd.DataFrame           # per (date, strategy, factor) intraday factor P&L
    r2: pd.Series
    betas: pd.DataFrame = field(default_factory=pd.DataFrame)          # daily / concurrent / Dimson / used
    epps_books: pd.DataFrame = field(default_factory=pd.DataFrame)     # strategy intraday beta by method
    seasonality_bias: pd.DataFrame = field(default_factory=pd.DataFrame)
    macro_bars: pd.DataFrame = field(default_factory=pd.DataFrame)


class IntradayModel:
    def __init__(self, panel: EquityPanel, fm: FactorModel, bars: pd.DataFrame, fut_bars: pd.DataFrame | None,
                 cfg: ModelConfig = MODEL):
        self.p, self.fm, self.cfg = panel, fm, cfg
        self.bars = bars[bars.ticker.isin(panel.tickers)].copy()
        h0, m0 = map(int, panel.spec.sessions[0][0].split(":"))
        self.h0m0 = h0 * 60 + m0
        mins = (self.bars.bar_end.dt.hour * 60 + self.bars.bar_end.dt.minute) - self.h0m0
        self.bars["bar"] = (mins // panel.spec.bar_minutes - 1).astype(int)
        self.dates = pd.DatetimeIndex(sorted(self.bars.date.unique()))
        self.nb = panel.spec.n_bars
        self.t_idx = fm.expo.dates.get_indexer(self.dates)
        self.fut_bars = fut_bars
        e = fm.expo
        self.names = [f for f in e.factors if e.groups[f] not in ("timeseries",)]
        self.kidx = e.idx(self.names)

    def _cube(self, col: str) -> np.ndarray:
        b = self.bars
        di = self.dates.get_indexer(b.date)
        ti = self.p.tickers.get_indexer(b.ticker)
        out = np.full((len(self.dates), len(self.p.tickers), self.nb), np.nan)
        out[di, ti, b.bar.values] = b[col].values
        return out

    # ---------------- futures and intraday betas ---------------- #
    def _futures(self):
        D, B = len(self.dates), self.nb
        fb = np.full((D, B), np.nan)
        if self.fut_bars is not None:
            f = self.fut_bars[self.fut_bars.date.isin(self.dates)].copy()
            mins = (f.bar_end.dt.hour * 60 + f.bar_end.dt.minute) - self.h0m0
            f["bar"] = (mins // self.p.spec.bar_minutes - 1).astype(int)
            fb[self.dates.get_indexer(f.date), f.bar.values] = (f.close / f.open - 1).values
        fut = self.p.futures.reindex(self.dates) if self.p.futures is not None else None
        prev_close = self.p.futures["close"].shift(1).reindex(self.dates) if fut is not None else None
        f_on = (fut["open"] / prev_close - 1).values if fut is not None else np.full(D, np.nan)
        return np.nan_to_num(fb), np.nan_to_num(f_on)

    def _intraday_betas(self, rb: np.ndarray, fb: np.ndarray):
        """Expanding-window concurrent and Dimson (lag 0 + lag 1) betas to futures bar returns,
        using only previous days; shrunk toward the daily predicted beta."""
        D, N, B = rb.shape
        lag = np.concatenate([np.zeros((D, 1)), fb[:, :-1]], 1)
        daily = self.fm.expo.beta_pred.reindex(index=self.dates, columns=self.p.tickers).fillna(1.0).values
        conc = np.full((D, N), np.nan); dims = np.full((D, N), np.nan); used = daily.copy()
        S00 = S01 = S11 = 0.0
        S0y = np.zeros(N); S1y = np.zeros(N)
        s = self.cfg.intraday_beta_shrink
        for d in range(D):
            if d >= 10:
                b_c = S0y / S00
                det = S00 * S11 - S01 ** 2
                b0 = (S11 * S0y - S01 * S1y) / det
                b1 = (S00 * S1y - S01 * S0y) / det
                conc[d], dims[d] = b_c, b0 + b1
                used[d] = s * dims[d] + (1 - s) * daily[d]
            y = np.nan_to_num(rb[d])
            S00 += fb[d] @ fb[d]; S01 += fb[d] @ lag[d]; S11 += lag[d] @ lag[d]
            S0y += y @ fb[d]; S1y += y @ lag[d]
        return conc, dims, used, daily

    def estimate(self):
        e = self.fm.expo
        names, kidx = self.names, self.kidx
        ind_idx = [j for j, f in enumerate(names) if e.groups[f] == "industry"]
        o, c = self._cube("open"), self._cube("close")
        buy, sell = self._cube("buy_volume"), self._cube("sell_volume")
        self.o, self.c = o, c
        rb = c / o - 1
        fb, f_on = self._futures()
        self.fb, self.f_on = fb, f_on
        conc, dims, used, daily = self._intraday_betas(rb, fb)
        self.beta_used, self.beta_daily, self.beta_conc, self.beta_dims = used, daily, conc, dims
        ofi = (buy - sell) / (buy + sell)
        D, N = len(self.dates), len(self.p.tickers)
        ron = self.p.ret_on.reindex(self.dates).values
        Rall = np.concatenate([ron[:, :, None], rb], axis=2)        # bar 0 = overnight / opening auction
        Fall = np.concatenate([f_on[:, None], fb], axis=1)
        self.R = Rall
        K = len(names) + 1                                           # + order_flow
        F = np.full((D, self.nb + 1, K), np.nan)
        OFz = np.zeros((D, N, self.nb + 1))
        r2 = []
        for d in range(D):
            t = self.t_idx[d]
            X0 = e.X[t][:, kidx]
            W = np.nan_to_num(e.reg_weight.values[t]); C = np.nan_to_num(e.cap.values[t]); E = e.estu.values[t]
            for b in range(self.nb + 1):
                beta = daily[d] if b == 0 else used[d]
                y = Rall[d, :, b] - beta * Fall[d, b]                 # remove the observed futures move
                if b > 0:
                    z = ofi[d, :, b - 1]
                    m = E & np.isfinite(z)
                    z = (z - np.nanmean(z[m])) / (np.nanstd(z[m]) + 1e-12) if m.sum() > 10 else np.zeros(N)
                    OFz[d, :, b] = np.nan_to_num(np.clip(z, -3, 3))
                X = np.column_stack([X0, OFz[d, :, b]])
                ok = E & np.isfinite(y) & np.all(np.isfinite(X), 1)
                if ok.sum() < 30:
                    continue
                Xo = X[ok]
                groups = [e.groups[f] for f in names] + ["intraday"]
                active = np.array([True if g == "market" else
                                   (np.count_nonzero(Xo[:, j]) >= 3 if g in ("industry", "event", "market_specific")
                                    else Xo[:, j].std() > 1e-8) for j, g in enumerate(groups)])
                ind_cap = np.zeros(K)
                for j in ind_idx:
                    ind_cap[j] = C[ok][Xo[:, j] > 0].sum()
                f, _, rr, _ = constrained_wls(_robust_clip(y[ok]), Xo, W[ok], ind_idx, ind_cap, active)
                F[d, b] = f
                r2.append(((self.dates[d], b), rr))
        self.F, self.OFz = F, OFz
        mi = pd.MultiIndex.from_product([self.dates, range(self.nb + 1)], names=["date", "bar"])
        bfr = pd.DataFrame(F.reshape(-1, K), index=mi, columns=names + ["order_flow"])
        bfr["index_futures"] = Fall.reshape(-1)
        self.season = np.nanmean(rb ** 2, axis=(0, 1))
        self.season = self.season / self.season.sum()
        # share of daily variance that falls in the session (rest is the overnight gap)
        r = self.p.ret.iloc[-250:].values; ro = self.p.ret_on.iloc[-250:].values
        self.session_share = float(1 - np.nanmean(ro ** 2) / np.nanmean(r ** 2))
        prof = pd.Series(np.nanmean(np.abs(rb), axis=(0, 1)), index=range(1, self.nb + 1), name="mean_abs_bar_return")
        betas = pd.DataFrame({"daily_beta": daily[-1], "concurrent_30m": conc[-1], "dimson_30m": dims[-1],
                              "intraday_used": used[-1]}, index=self.p.tickers)
        return bfr, prof, pd.Series(dict(r2)), betas

    # ---------------- macro release bars ---------------- #
    def macro_bar_stats(self) -> pd.DataFrame:
        ev = self.p.macro_events
        if ev is None or not len(ev):
            return pd.DataFrame()
        rows = []
        for r in ev[ev.date.isin(self.dates)].itertuples():
            hh, mm = map(int, r.time_local.split(":"))
            minute = hh * 60 + mm - self.h0m0
            b = 0 if minute < 0 else min(minute // self.p.spec.bar_minutes + 1, self.nb)
            d = self.dates.get_loc(r.date)
            fut = self.f_on[d] if b == 0 else self.fb[d, b - 1]
            same = self.f_on if b == 0 else self.fb[:, b - 1]
            others = np.delete(same, d)
            rows.append({"date": r.date.date(), "event": r.event, "release": r.time_local, "bar": b,
                         "abs_futures_move_bps": abs(fut) * 1e4,
                         "typical_same_bar_bps": np.mean(np.abs(others)) * 1e4})
        return pd.DataFrame(rows)

    # ---------------- attribution ---------------- #
    def attribute(self, td: TradingData, att: AttributionResult, strategies: list, rm: RiskModel | None = None):
        p, e = self.p, self.fm.expo
        names = self.names
        rows, frows, erows, zrows = [], [], [], []
        for s in strategies:
            book = att.books[s]
            sh = book.shares_eod
            fl = td.fills[(td.fills.strategy == s) & td.fills.date.isin(self.dates)].copy()
            mins = (fl.timestamp.dt.hour * 60 + fl.timestamp.dt.minute + fl.timestamp.dt.second / 60) - self.h0m0
            fl["bar"] = np.clip((mins // p.spec.bar_minutes).astype(int), 0, self.nb - 1) + 1
            fl["ti"] = p.tickers.get_indexer(fl.ticker)
            for d, date in enumerate(self.dates):
                t = self.t_idx[d]
                if t < 1:
                    continue
                X = np.nan_to_num(e.X[t][:, self.kidx])
                n = (sh.iloc[t - 1].values * p.split.iloc[t].values).astype(float)
                prev_close = p.close.iloc[t - 1].values / p.split.iloc[t].values
                h_on = np.nan_to_num(n * prev_close)
                r_on = np.nan_to_num(self.R[d, :, 0])
                on_tot = np.sum(h_on * r_on)
                f0 = np.nan_to_num(self.F[d, 0])
                on_fut = np.sum(h_on * self.beta_daily[d]) * self.f_on[d]
                on_fac_k = (X.T @ h_on) * f0[:-1]
                f_day = fl[fl.date == date]
                q_by_bar = np.zeros((self.nb + 2, len(p.tickers)))
                np.add.at(q_by_bar, (f_day.bar.values, f_day.ti.values), f_day.quantity.values)
                cum = n.copy()
                id_fac_k = np.zeros(len(names)); id_tot = id_fut = id_of = wb_trade = 0.0
                if rm is not None and np.isfinite(rm.F[t]).all():
                    Fm, sv = rm.F[t], np.nan_to_num(rm.spec_var[t], nan=0.03 ** 2)
                    Xr = np.nan_to_num(rm.X[t])
                peak = None
                for b in range(1, self.nb + 1):
                    ob, cb = np.nan_to_num(self.o[d, :, b - 1]), np.nan_to_num(self.c[d, :, b - 1])
                    hb = cum * ob
                    pnl_b = np.sum(cum * (cb - ob))
                    id_tot += pnl_b
                    fbk = np.nan_to_num(self.F[d, b])
                    id_fut += np.sum(hb * self.beta_used[d]) * self.fb[d, b - 1]
                    id_fac_k += (X.T @ hb) * fbk[:-1]
                    id_of += np.sum(hb * self.OFz[d, :, b]) * fbk[-1]
                    if rm is not None and np.abs(hb).sum() > 0 and np.isfinite(rm.F[t]).all():
                        x = Xr.T @ hb
                        day_var = x @ Fm @ x + np.sum(hb ** 2 * sv)
                        sess_var = day_var * self.session_share
                        zrows.append((s, b, pnl_b / np.sqrt(sess_var * self.season[b - 1]),
                                      pnl_b / np.sqrt(sess_var / self.nb)))
                    gross_b = np.abs(hb).sum()
                    if peak is None or gross_b > peak[0]:
                        peak = (gross_b, hb.copy())
                    fb_ = f_day[f_day.bar == b]
                    wb_trade += np.sum(fb_.quantity.values * (cb[fb_.ti.values] - fb_.price.values))
                    cum = cum + q_by_bar[b]
                daily = att.daily.loc[(date, s)] if (date, s) in att.daily.index else None
                ref = (daily.hold_pnl + daily.trading + daily.delay_cost + daily.impact_cost) if daily is not None else np.nan
                tot = on_tot + id_tot + wb_trade
                rows.append({"date": date, "strategy": s,
                             "overnight_futures": on_fut, "overnight_factor": on_fac_k.sum(),
                             "overnight_residual": on_tot - on_fut - on_fac_k.sum(),
                             "intraday_futures": id_fut, "intraday_factor": id_fac_k.sum(),
                             "intraday_order_flow": id_of,
                             "intraday_residual": id_tot - id_fut - id_fac_k.sum() - id_of,
                             "within_bar_trading": wb_trade, "intraday_total": tot, "daily_mtm": ref,
                             "reconciliation_diff": tot - ref})
                for k, f in enumerate(names):
                    frows.append((date, s, f, on_fac_k[k], id_fac_k[k]))
                if peak is not None and peak[0] > 0 and d >= 10:
                    hb = peak[1]
                    erows.append({"date": date, "strategy": s, "peak_gross": peak[0],
                                  "beta_concurrent": np.nansum(hb * self.beta_conc[d]) / peak[0],
                                  "beta_dimson": np.nansum(hb * self.beta_dims[d]) / peak[0],
                                  "beta_daily": np.sum(hb * self.beta_daily[d]) / peak[0]})
        fd = pd.DataFrame(frows, columns=["date", "strategy", "factor", "overnight_pnl", "intraday_pnl"])
        z = pd.DataFrame(zrows, columns=["strategy", "bar", "z_seasonal", "z_flat"])
        sb = z.groupby(["strategy", "bar"]).agg(bias_seasonal=("z_seasonal", "std"), bias_flat=("z_flat", "std"),
                                                n=("z_flat", "size")).reset_index() if len(z) else pd.DataFrame()
        return pd.DataFrame(rows).set_index(["date", "strategy"]), fd, pd.DataFrame(erows), sb

    def run(self, td: TradingData, att: AttributionResult, strategies: list, rm: RiskModel | None = None) -> IntradayResult:
        bfr, prof, r2, betas = self.estimate()
        a, fd, ep, sb = self.attribute(td, att, strategies, rm)
        return IntradayResult(bar_factor_returns=bfr, vol_profile=prof, attribution=a, factor_detail=fd, r2=r2,
                              betas=betas, epps_books=ep, seasonality_bias=sb, macro_bars=self.macro_bar_stats())
