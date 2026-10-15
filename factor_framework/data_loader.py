"""Layer 1 - Data.

Loads raw files, adjusts for corporate actions, aligns every dataset point in
time and returns clean wide (date x security) panels.  Nothing downstream
touches raw files.

Conventions
-----------
* Returns are total returns in local currency: (P_t * split_t + D_t) / P_{t-1} - 1.
* Overnight return uses the open; intraday = (1 + total) / (1 + overnight) - 1.
* Anything published with a lag (short interest, fundamentals) is indexed by
  its *publication* date and forward filled, never by the period it describes.
* FX: ``usd_per_local`` converts local-currency amounts to USD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CRYPTO_SECTORS, DATA_DIR, MARKETS, MarketSpec


def _pivot(df: pd.DataFrame, col: str, dates, tickers, index="date", columns="ticker") -> pd.DataFrame:
    return df.pivot(index=index, columns=columns, values=col).reindex(index=dates, columns=tickers)


# --------------------------------------------------------------------------- #
@dataclass
class EquityPanel:
    market: str
    spec: MarketSpec
    dates: pd.DatetimeIndex
    tickers: pd.Index
    ref: pd.DataFrame
    open: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    spread_bps: pd.DataFrame
    halted: pd.DataFrame
    listed: pd.DataFrame
    split: pd.DataFrame
    dividend: pd.DataFrame
    ret: pd.DataFrame
    ret_on: pd.DataFrame
    ret_id: pd.DataFrame
    shares: pd.DataFrame
    usd_per_local: pd.Series
    mcap_usd: pd.DataFrame
    dollar_vol_usd: pd.DataFrame
    adv_usd: pd.DataFrame          # 20d average, known at t (uses data to t-1)
    adv_shares: pd.DataFrame
    short_interest_pct: pd.DataFrame
    days_to_cover: pd.DataFrame
    borrow_fee_bps: pd.DataFrame
    earnings: pd.DataFrame
    index_event: pd.DataFrame
    book_equity: pd.DataFrame
    net_income: pd.DataFrame
    revenue: pd.DataFrame
    limit_flag: pd.DataFrame
    borrow_avail_pct: pd.DataFrame = None     # shares available to borrow / shares outstanding
    utilisation: pd.DataFrame = None          # securities-lending utilisation (0-1)
    corporate_action: pd.DataFrame = None     # ex-date flags (splits, dividends)
    index_member: pd.DataFrame = None
    option_expiry: pd.Series = None           # monthly index option / futures expiry days
    retail_share: pd.DataFrame = None         # retail-identified share of volume
    etf_own_pct: pd.DataFrame = None          # ETF ownership / shares outstanding (point in time)
    hf_own_pct: pd.DataFrame = None           # 13F hedge-fund ownership (point in time)
    shocks: pd.DataFrame = None               # observed time-series shock series g
    macro_events: pd.DataFrame = None         # scheduled macro announcements for this market
    macro_day: pd.Series = None
    futures: pd.DataFrame = None              # index futures open / close
    vol_index: pd.Series = None
    agg_spread_bps: pd.Series = None
    depth: pd.Series = None
    data_issues: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def sectors(self) -> pd.Series:
        return self.ref["sector"]


@dataclass
class CryptoPanel:
    dates: pd.DatetimeIndex
    symbols: pd.Index
    ref: pd.DataFrame
    spot: pd.DataFrame             # index price (VENUE_A spot)
    perp: dict                     # venue -> wide perp close
    funding: pd.DataFrame          # daily funding rate (sum of 3 x 8h)
    basis: pd.DataFrame
    volume_usd: pd.DataFrame
    oi_usd: pd.DataFrame
    ret: pd.DataFrame              # spot index returns
    perp_ret: dict                 # venue -> perp returns
    unlock: pd.DataFrame
    mcap_proxy: pd.DataFrame

    @property
    def sectors(self) -> pd.Series:
        return self.ref["sector"]


@dataclass
class TradingData:
    strategies: pd.DataFrame
    positions: pd.DataFrame
    fills: pd.DataFrame
    financing: pd.DataFrame
    official_pnl: pd.DataFrame
    releases: pd.DataFrame

    def market_of(self, strategy: str) -> str:
        return self.strategies.set_index("strategy").loc[strategy, "market"]

    def team_of(self, strategy: str) -> str:
        return self.strategies.set_index("strategy").loc[strategy, "team"]

    def positions_wide(self, strategy: str, dates, tickers) -> pd.DataFrame:
        p = self.positions[self.positions.strategy == strategy]
        w = p.pivot_table(index="date", columns="ticker", values="quantity", aggfunc="sum")
        return w.reindex(index=dates, columns=tickers).fillna(0.0)


# --------------------------------------------------------------------------- #
def load_macro(data_dir: Path = DATA_DIR):
    fx = pd.read_csv(data_dir / "macro/fx_rates.csv", parse_dates=["date"])
    rates = pd.read_csv(data_dir / "macro/short_rates.csv", parse_dates=["date"])
    return fx, rates


def aligned_log_change(level: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """Log change of a series between consecutive session dates (moves on non-trading days
    roll into the next session)."""
    lv = np.log(level.dropna())
    return lv.reindex(lv.index.union(dates)).ffill().reindex(dates).diff()


def local_level_change(x: pd.Series, min_obs: int = 60) -> pd.Series:
    """Daily change in the filtered level of a series observed with transient noise.

    Model: x_t = level_t + noise_t, level a random walk.  Then dx is MA(1) with lag-1
    autocorrelation rho in (-1/2, 0], and the steady-state Kalman filter is exponential
    smoothing with gain K = 1 + theta, theta the invertible MA(1) root of rho.  The output
    (the filtered level change, i.e. K times the innovation) is serially uncorrelated, whereas
    the raw difference carries -noise_{t-1} into every day.  rho is estimated on an expanding
    window ending the previous day (point in time); no smoothing before ``min_obs``.  rho is
    floored at -0.4 (K >= 0.5, at least half the weight on today's observation): MA(1)
    estimates near the non-invertible -0.5 are unstable, and a quiet start of sample would
    otherwise over-smooth - lagging the shock - for a long time after."""
    v = x.values.astype(float)
    out = np.full(len(v), np.nan)
    lvl = x_prev = dx_prev = np.nan
    s1 = s2 = s11 = 0.0                   # sums of dx, dx^2, dx_t * dx_{t-1}
    m = m1 = 0
    for t in range(len(v)):
        if not np.isfinite(v[t]):
            continue
        if not np.isfinite(lvl):
            lvl = x_prev = v[t]
            continue
        K = 1.0
        if m >= min_obs:
            mu = s1 / m
            var = s2 / m - mu ** 2
            rho = (s11 / m1 - mu ** 2) / var if var > 0 and m1 else 0.0
            rho = min(max(rho, -0.4), 0.0)
            if rho < 0:
                K = 1.0 + (1 - np.sqrt(1 - 4 * rho ** 2)) / (2 * rho)
        new = lvl + K * (v[t] - lvl)
        out[t] = new - lvl
        lvl = new
        dx = v[t] - x_prev                # update moments after use: K_t uses data to t-1
        s1 += dx; s2 += dx * dx; m += 1
        if np.isfinite(dx_prev):
            s11 += dx * dx_prev; m1 += 1
        x_prev, dx_prev = v[t], dx
    return pd.Series(out, index=x.index)


def prior_session_return(us_fut_lr: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """For an Asian session on date t: sum of US session returns closing between the previous
    local close and today's open (US dates d with prev_date <= d < t)."""
    c = us_fut_lr.fillna(0).cumsum()
    idx = c.index
    def before(d):
        k = idx.searchsorted(d, "left") - 1
        return c.iloc[k] if k >= 0 else 0.0
    vals = [np.nan] + [before(dates[t]) - before(dates[t - 1]) for t in range(1, len(dates))]
    return pd.Series(vals, index=dates)


def load_equity_panel(market: str, data_dir: Path = DATA_DIR) -> EquityPanel:
    spec = MARKETS[market]
    ref = pd.read_csv(data_dir / "reference/securities.csv", parse_dates=["list_date", "delist_date"])
    ref = ref[ref.market == market].set_index("ticker")
    ref["theme_tag"] = ref["theme_tag"].fillna("")
    px = pd.read_csv(data_dir / f"market/prices_daily_{market}.csv.gz", parse_dates=["date"])
    dates = pd.DatetimeIndex(sorted(px.date.unique()))
    tickers = pd.Index(sorted(ref.index))
    ref = ref.loc[tickers]

    w = {c: _pivot(px, c, dates, tickers) for c in ["open", "close", "volume", "spread_bps", "halted"]}
    listed = w["close"].notna()
    halted = w["halted"].fillna(0).astype(bool)

    ca = pd.read_csv(data_dir / "reference/corporate_actions.csv", parse_dates=["ex_date"])
    ca = ca[ca.ticker.isin(tickers)]
    split = pd.DataFrame(1.0, index=dates, columns=tickers)
    div = pd.DataFrame(0.0, index=dates, columns=tickers)
    for r in ca.itertuples():
        if r.ex_date not in split.index:
            continue
        if r.action == "SPLIT":
            split.at[r.ex_date, r.ticker] = r.ratio
        elif r.action == "CASH_DIVIDEND":
            div.at[r.ex_date, r.ticker] += r.amount

    close, opn = w["close"], w["open"]
    prev = close.shift(1)
    ret = (close * split + div) / prev - 1
    ret_on = (opn * split + div) / prev - 1
    ret_id = (1 + ret) / (1 + ret_on) - 1
    # suspended days carry no information: exclude from estimation
    for df in (ret, ret_on, ret_id):
        df[halted] = np.nan

    # data quality: large moves with no corporate action are flagged, not dropped
    issues = []
    big = (ret.abs() > 0.4) & (split == 1)
    for d, t in zip(*np.where(big.values)):
        issues.append({"date": dates[d], "ticker": tickers[t], "issue": "abs return > 40% without corporate action",
                       "value": float(ret.iat[d, t])})
    stale = (w["volume"] == 0) & ~halted
    for d, t in zip(*np.where(stale.values)):
        issues.append({"date": dates[d], "ticker": tickers[t], "issue": "zero volume but not flagged halted",
                       "value": 0.0})

    # FX: local units per USD -> USD per local unit
    fx, rates = load_macro(data_dir)
    if spec.fx_pair:
        q = fx[fx.pair == spec.fx_pair].set_index("date")["rate"].reindex(dates, method="ffill")
        usd_per_local = 1.0 / q
    else:
        usd_per_local = pd.Series(1.0, index=dates)

    shares = pd.DataFrame(np.tile(ref["shares_outstanding"].values, (len(dates), 1)),
                          index=dates, columns=tickers) * split.cumprod()
    mcap_usd = (close * shares).mul(usd_per_local, axis=0)
    dollar_vol_usd = (close * w["volume"]).mul(usd_per_local, axis=0)
    adv_usd = dollar_vol_usd.rolling(20, min_periods=5).mean().shift(1)
    adv_shares = w["volume"].rolling(20, min_periods=5).mean().shift(1)

    # short interest: point in time by publication date
    si = pd.read_csv(data_dir / "alt/short_interest.csv.gz", parse_dates=["settlement_date", "publication_date"])
    si = si[si.ticker.isin(tickers)].sort_values("publication_date")
    si_w = si.pivot_table(index="publication_date", columns="ticker", values="short_interest_shares", aggfunc="last")
    si_w = si_w.reindex(dates.union(si_w.index)).ffill().reindex(dates).reindex(columns=tickers)
    short_interest_pct = (si_w / shares).fillna(0.0)
    days_to_cover = (si_w / adv_shares).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    fees = pd.read_csv(data_dir / "alt/borrow_fees.csv.gz", parse_dates=["date"])
    fees = fees[fees.ticker.isin(tickers)]
    borrow_fee = _pivot(fees, "fee_bps", dates, tickers)

    # events: known in advance (earnings calendar and index changes are announced)
    ev = pd.read_csv(data_dir / "reference/earnings_calendar.csv", parse_dates=["event_date", "fiscal_period_end"])
    ev = ev[ev.ticker.isin(tickers)]
    earnings = pd.DataFrame(False, index=dates, columns=tickers)
    for r in ev.itertuples():
        if r.event_date in earnings.index:
            earnings.at[r.event_date, r.ticker] = True
    ic = pd.read_csv(data_dir / "reference/index_changes.csv", parse_dates=["effective_date"])
    ic = ic[ic.market == market]
    index_event = pd.DataFrame(0.0, index=dates, columns=tickers)
    for r in ic.itertuples():
        if r.effective_date in index_event.index:
            index_event.at[r.effective_date, r.ticker] = 1.0 if r.change == "ADD" else -1.0

    # fundamentals: point in time by report date
    fu = pd.read_csv(data_dir / "fundamentals/fundamentals_quarterly.csv", parse_dates=["report_date", "fiscal_period_end"])
    fu = fu[fu.ticker.isin(tickers)].sort_values("report_date")
    def pit(col):
        p = fu.pivot_table(index="report_date", columns="ticker", values=col, aggfunc="last")
        return p.reindex(dates.union(p.index)).ffill().reindex(dates).reindex(columns=tickers)
    book = pit("book_equity").mul(usd_per_local, axis=0)
    ni = pit("net_income_q").mul(usd_per_local, axis=0)
    rev = pit("revenue_q").mul(usd_per_local, axis=0)

    # price-limit hits (China): close at the limit relative to previous close
    if spec.price_limit:
        resume = halted.shift(1, fill_value=False) & ~halted
        lim = spec.price_limit * 0.98
        limit_flag = ((ret >= lim).astype(float) - (ret <= -lim).astype(float)).where(~resume, 0.0).fillna(0.0)
    else:
        limit_flag = pd.DataFrame(0.0, index=dates, columns=tickers)

    # ---- securities lending: availability and utilisation (prime-broker data, daily) ----
    borrow_avail = (_pivot(fees, "available_shares", dates, tickers) / shares) if "available_shares" in fees else None
    utilisation = (_pivot(fees, "utilization_pct", dates, tickers) / 100) if "utilization_pct" in fees else None

    # ---- corporate-action ex-dates, index membership, option expiry ----
    corp = (split != 1) | (div > 0)
    member = pd.DataFrame(np.tile(ref["index_member_at_start"].values.astype(float), (len(dates), 1)),
                          index=dates, columns=tickers)
    for r in ic.sort_values("effective_date").itertuples():
        if r.ticker in member.columns:
            member.loc[member.index >= r.effective_date, r.ticker] = 1.0 if r.change == "ADD" else 0.0
    cal = pd.read_csv(data_dir / "reference/market_calendar.csv", parse_dates=["date"])
    cal = cal[cal.market == market].set_index("date")
    option_expiry = cal["is_option_expiry"].reindex(dates).fillna(False).astype(bool)

    # ---- flow and ownership data (point in time by publication date) ----
    def optional(path):
        return pd.read_csv(data_dir / path, parse_dates=True) if (data_dir / path).exists() else None
    retail_share = etf_own = hf_own = None
    rf = optional("alt/retail_flow.csv.gz")
    if rf is not None:
        rf["date"] = pd.to_datetime(rf["date"])
        retail_share = _pivot(rf[rf.ticker.isin(tickers)], "retail_share", dates, tickers)
    eo = optional("alt/etf_ownership.csv.gz")
    if eo is not None:
        eo["publication_date"] = pd.to_datetime(eo["publication_date"])
        p_ = eo[eo.ticker.isin(tickers)].pivot_table(index="publication_date", columns="ticker",
                                                     values="etf_shares_held", aggfunc="last")
        etf_own = p_.reindex(dates.union(p_.index)).ffill().reindex(dates).reindex(columns=tickers) / shares
    hf = optional("alt/hf_ownership_13f.csv")
    if hf is not None:
        hf["filing_date"] = pd.to_datetime(hf["filing_date"])
        p_ = hf[hf.ticker.isin(tickers)].pivot_table(index="filing_date", columns="ticker",
                                                     values="hf_shares_held", aggfunc="last")
        if len(p_):
            hf_own = p_.reindex(dates.union(p_.index)).ffill().reindex(dates).reindex(columns=tickers) / shares

    # ---- market-wide series and observed time-series shocks g ----
    macro_events = futures = vol_idx = depth = None
    shocks = pd.DataFrame(index=dates)
    mc = optional("reference/macro_calendar.csv")
    if mc is not None:
        mc["date"] = pd.to_datetime(mc["date"])
        macro_events = mc[mc.market == market].reset_index(drop=True)
    macro_day = pd.Series(dates.isin(macro_events.date) if macro_events is not None else False, index=dates)
    w_cap = mcap_usd.shift(1).where(~halted & w["spread_bps"].notna())
    agg_spread = (w["spread_bps"] * w_cap).sum(axis=1) / w_cap.sum(axis=1)
    vi = optional("macro/vol_index.csv")
    if vi is not None and spec.vol_index:
        vi["date"] = pd.to_datetime(vi["date"])
        vol_idx = vi[vi["index"] == spec.vol_index].set_index("date")["close"].reindex(dates)
        shocks["vol_shock"] = np.log(vol_idx).diff()
    md = optional("macro/market_depth.csv")
    if md is not None:
        md["date"] = pd.to_datetime(md["date"])
        depth = md[md.market == market].set_index("date")["top5_depth_local"].reindex(dates)
        # both levels carry day-to-day measurement noise; differencing it gives a strongly
        # negatively autocorrelated shock, so take the change in the filtered level instead
        shocks["liq_shock"] = local_level_change(0.5 * np.log(agg_spread) - 0.5 * np.log(depth))
    if spec.fx_series:
        shocks["fx"] = aligned_log_change(fx[fx.pair == spec.fx_series].set_index("date")["rate"], dates)
    rfut = optional("macro/rates_futures.csv")
    if rfut is not None and spec.rates_future:
        rfut["date"] = pd.to_datetime(rfut["date"])
        shocks["rates"] = aligned_log_change(rfut[rfut.contract == spec.rates_future].set_index("date")["close"], dates)
    fut = optional("market/index_futures_daily.csv")
    if fut is not None:
        fut["date"] = pd.to_datetime(fut["date"])
        futures = fut[fut.market == market].set_index("date")[["open", "close"]].reindex(dates)
        if "us_session" in spec.ts_factors:
            us_f = fut[fut.market == "US"].set_index("date")["close"]
            shocks["us_session"] = prior_session_return(np.log(us_f).diff(), dates)
    shocks = shocks[[c for c in spec.ts_factors if c in shocks]]

    return EquityPanel(
        market=market, spec=spec, dates=dates, tickers=tickers, ref=ref, open=opn, close=close,
        volume=w["volume"], spread_bps=w["spread_bps"], halted=halted, listed=listed, split=split,
        dividend=div, ret=ret, ret_on=ret_on, ret_id=ret_id, shares=shares, usd_per_local=usd_per_local,
        mcap_usd=mcap_usd, dollar_vol_usd=dollar_vol_usd, adv_usd=adv_usd, adv_shares=adv_shares,
        short_interest_pct=short_interest_pct, days_to_cover=days_to_cover, borrow_fee_bps=borrow_fee,
        earnings=earnings, index_event=index_event, book_equity=book, net_income=ni, revenue=rev,
        limit_flag=limit_flag, borrow_avail_pct=borrow_avail, utilisation=utilisation,
        corporate_action=corp, index_member=member, option_expiry=option_expiry, retail_share=retail_share,
        etf_own_pct=etf_own, hf_own_pct=hf_own, shocks=shocks, macro_events=macro_events, macro_day=macro_day,
        futures=futures, vol_index=vol_idx, agg_spread_bps=agg_spread, depth=depth,
        data_issues=pd.DataFrame(issues),
    )


def load_crypto_panel(data_dir: Path = DATA_DIR) -> CryptoPanel:
    cd = pd.read_csv(data_dir / "crypto/crypto_daily.csv.gz", parse_dates=["date"])
    ref = pd.read_csv(data_dir / "crypto/crypto_reference.csv").set_index("symbol")
    dates = pd.DatetimeIndex(sorted(cd.date.unique()))
    symbols = pd.Index(ref.index)
    a = cd[cd.venue == "VENUE_A"]
    spot = _pivot(a, "spot_close", dates, symbols, columns="symbol")
    perp = {v: _pivot(cd[cd.venue == v], "perp_close", dates, symbols, columns="symbol")
            for v in cd.venue.unique()}
    funding = _pivot(a, "funding_rate_daily", dates, symbols, columns="symbol")
    vol = cd.groupby(["date", "symbol"]).volume_usd.sum().unstack().reindex(index=dates, columns=symbols)
    oi = cd.groupby(["date", "symbol"]).open_interest_usd.sum().unstack().reindex(index=dates, columns=symbols)
    un = pd.read_csv(data_dir / "crypto/token_unlocks.csv", parse_dates=["unlock_date"])
    unlock = pd.DataFrame(0.0, index=dates, columns=symbols)
    for r in un.itertuples():
        if r.unlock_date in unlock.index:
            unlock.at[r.unlock_date, r.symbol] = 1.0
    # market-cap proxy: open interest scales with float value
    mcap_proxy = oi / 0.025
    return CryptoPanel(
        dates=dates, symbols=symbols, ref=ref, spot=spot, perp=perp, funding=funding,
        basis=perp["VENUE_A"] / spot - 1, volume_usd=vol, oi_usd=oi, ret=spot.pct_change(),
        perp_ret={v: p.pct_change() for v, p in perp.items()}, unlock=unlock, mcap_proxy=mcap_proxy,
    )


def load_trading(data_dir: Path = DATA_DIR) -> TradingData:
    strategies = pd.read_csv(data_dir / "trading/strategies.csv")
    positions = pd.read_csv(data_dir / "trading/positions_eod.csv.gz", parse_dates=["date"])
    positions["venue"] = positions["venue"].fillna("")
    fills = pd.read_csv(data_dir / "trading/fills.csv.gz", parse_dates=["date", "timestamp", "decision_time"])
    fin = pd.read_csv(data_dir / "trading/financing.csv", parse_dates=["date"])
    pnl = pd.read_csv(data_dir / "trading/official_pnl.csv", parse_dates=["date"])
    rel = pd.read_csv(data_dir / "trading/model_releases.csv", parse_dates=["release_date"])
    return TradingData(strategies, positions, fills, fin, pnl, rel)


def load_truth(data_dir: Path = DATA_DIR) -> dict:
    out = {}
    for m in ("US", "CN", "CRYPTO"):
        p = data_dir / f"truth/factor_returns_{m}.csv"
        if p.exists():
            out[m] = pd.read_csv(p, index_col=0, parse_dates=True)
    p = data_dir / "truth/stress_episodes.csv"
    out["stress"] = pd.read_csv(p, parse_dates=["date"]) if p.exists() else pd.DataFrame()
    for m in ("US", "CN"):
        p = data_dir / f"truth/regime_{m}.csv"
        if p.exists():
            out[f"regime_{m}"] = pd.read_csv(p, parse_dates=["date"]).set_index("date")["regime"]
        p = data_dir / f"truth/ts_loadings_{m}.csv"
        if p.exists():
            out[f"ts_loadings_{m}"] = pd.read_csv(p, index_col=0)
    return out


def load_bars(market: str = "US", data_dir: Path = DATA_DIR) -> pd.DataFrame:
    bars = pd.read_csv(data_dir / f"market/bars_{30}m_{market}.csv.gz", parse_dates=["bar_end"])
    bars["date"] = bars.bar_end.dt.normalize()
    return bars


def load_futures_bars(market: str = "US", data_dir: Path = DATA_DIR) -> pd.DataFrame | None:
    p = data_dir / f"market/index_futures_bars_30m_{market}.csv"
    if not p.exists():
        return None
    fb = pd.read_csv(p, parse_dates=["bar_end"])
    fb["date"] = fb.bar_end.dt.normalize()
    return fb
