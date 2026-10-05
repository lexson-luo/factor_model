"""Synthetic-but-realistic raw data for the factor framework.

The generator produces exactly the *raw* datasets a middle-office risk team
would receive from the firm's systems and vendors (Section 3.3 of the case):

    reference/   securities master, corporate actions, index changes,
                 earnings calendar, market calendar
    market/      daily OHLCV + spreads (raw, unadjusted), 30-minute bars (US)
    fundamentals point-in-time quarterly statements
    alt/         short interest (with publication lag), daily borrow fees
    crypto/      spot + perpetual prices per venue, funding, open interest,
                 token unlock calendar
    macro/       FX and short rates
    trading/     strategy registry, model releases, EOD positions, fills with
                 decision/arrival prices, prime-broker financing, official P&L
    truth/       the latent factor returns used to simulate the data (only for
                 validating that the in-house model recovers them)

Returns are simulated from a latent factor structure that deliberately
contains things the core model must *discover*: a hidden thematic factor,
volatility regimes, crowding shocks, cross-market lead/lag and crypto
spill-over into crypto-linked equities.  Raw prices carry splits, dividends,
suspensions, IPOs and delistings so the data layer has real hygiene work to do.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CN, CRYPTO_SECTORS, CRYPTO_VENUES, DATA_DIR, US, MarketSpec


# --------------------------------------------------------------------------- #
# Simulation settings
# --------------------------------------------------------------------------- #
@dataclass
class SimConfig:
    start: str = "2024-01-02"
    end: str = "2026-09-30"
    trading_start: str = "2024-07-01"     # strategies go live (history before = warm-up)
    n_us: int = 300
    n_cn: int = 160
    n_crypto: int = 40
    intraday_days: int = 60               # days of 30-minute bars kept for the US
    gmv_scale: float = 1.0
    seed: int = 7
    out_dir: Path = field(default_factory=lambda: DATA_DIR)


# Embedded stress episodes (shocks in units of the factor's daily vol)
STRESS_EPISODES = [
    {"name": "Global carry-trade unwind", "date": "2024-08-05", "days": 1, "regime_days": 12,
     "spec_mult": 1.8,
     "US": {"market": -3.5, "crowding": 2.0, "liquidity": -2.0, "theme": -3.0, "volatility": -2.0},
     "CN": {"market": -1.5},
     "CRYPTO": {"btc": -3.5, "alt": -2.5}},
    {"name": "Quant deleveraging", "date": "2025-03-11", "days": 3, "regime_days": 8,
     "spec_mult": 1.5,
     "US": {"st_reversal": -4.0, "crowding": 3.0, "theme": -2.0, "liquidity": -1.5},
     "CN": {"st_reversal": -1.5}},
    {"name": "Tariff shock / CN limit-down cascade", "date": "2025-04-07", "days": 1,
     "regime_days": 6, "spec_mult": 1.5,
     "US": {"market": -3.0, "beta": -1.0}, "CN": {"market": -5.0, "st_reversal": -2.0},
     "CRYPTO": {"btc": -2.0}},
    {"name": "Crypto liquidation cascade", "date": "2025-10-10", "days": 1, "regime_days": 5,
     "spec_mult": 2.0, "US": {"crypto_amp": 1.0},
     "CRYPTO": {"btc": -3.0, "alt": -4.5, "funding": -3.0}},
    {"name": "Momentum/value rotation", "date": "2025-11-10", "days": 1, "regime_days": 3,
     "spec_mult": 1.2,
     "US": {"value": 5.0, "momentum_12_1": -5.0, "volatility": 2.0, "size": 1.5},
     "CN": {"value": 3.0, "momentum_12_1": -3.0}},
    {"name": "Retail short squeeze", "date": "2026-01-27", "days": 2, "regime_days": 5,
     "spec_mult": 1.6,
     "US": {"crowding": 5.0, "volatility": 2.5, "st_reversal": -1.5, "retail_attention": 4.0}},
]
VENUE_INCIDENT = {"date": "2025-07-14", "venue": "VENUE_B", "dislocation": -0.04}

# daily vol, daily mean, overnight share of variance
EQUITY_FACTOR_PARAMS = {
    "size": (0.0025, 0.0000, 0.4),
    "liquidity": (0.0020, -0.0001, 0.4),
    "volatility": (0.0035, -0.0001, 0.4),
    "st_reversal": (0.0030, 0.0004, 0.3),
    "st_momentum": (0.0020, 0.0001, 0.0),
    "overnight_gap": (0.0018, -0.0002, 1.0),
    "crowding": (0.0025, -0.0002, 0.4),
    "earnings": (0.0040, 0.0010, 0.8),
    "index_rebalance": (0.0080, 0.0020, 0.5),
    "value": (0.0015, 0.0000, 0.4),
    "momentum_12_1": (0.0020, 0.0001, 0.4),
    "earnings_yield": (0.0, 0.0, 0.4),
    "quality": (0.0, 0.0, 0.4),
    "long_term_reversal": (0.0, 0.0, 0.4),
    "theme": (0.0090, 0.0004, 0.4),        # hidden: NOT in the core model
    "limit_hit": (0.0060, 0.0120, 0.5),    # CN only: limit-move continuation
    "option_expiry": (0.0030, 0.0000, 0.3),
    "corporate_action": (0.0, 0.0, 0.5),   # no common effect - should fail the selection test
    "in_play": (0.0060, 0.0010, 0.5),
    "etf_flow": (0.0020, 0.0000, 0.4),     # candidate: ETF / index-basket co-movement
    "retail_attention": (0.0015, -0.0001, 0.5),   # candidate: retail flow and attention
}
INDUSTRY_VOL = 0.006
MARKET_VOL = {"US": 0.009, "CN": 0.012}
MARKET_OVERNIGHT_SHARE = {"US": 0.40, "CN": 0.50}
VOL_INDEX_BASE = {"US": 16.0, "CN": 22.0}
DEPTH_BASE = {"US": 2.5e10, "CN": 3.0e10}
FUT_LEVEL0 = {"US": 4800.0, "CN": 3500.0}
# time-series sensitivities by sector (return per unit of shock), plus stock-level noise
TS_SECTOR_LOADINGS = {
    "US": {
        "fx": {"Technology": -0.8, "Semiconductors": -1.0, "Communication": -0.3, "Consumer Discretionary": -0.2,
               "Consumer Staples": -0.4, "Health Care": -0.3, "Financials": 0.2, "Industrials": -0.6,
               "Energy": -0.4, "Materials": -0.7, "Utilities": 0.2},
        "rates": {"Technology": 0.8, "Semiconductors": 0.6, "Communication": 0.5, "Consumer Discretionary": 0.2,
                  "Consumer Staples": 0.6, "Health Care": 0.3, "Financials": -1.2, "Industrials": 0.0,
                  "Energy": -0.5, "Materials": -0.3, "Utilities": 1.5},
        "us_session": {s: 0.0 for s in US.sectors},
    },
    "CN": {
        "fx": {"Banks": -0.3, "Non-bank Financials": -0.2, "Electronics": 1.0, "Computers": 0.3, "Pharma": 0.2,
               "Food & Beverage": 0.0, "Machinery": 0.8, "Autos": 0.6, "Chemicals": 0.5, "Real Estate": -1.2},
        "rates": {"Banks": -1.5, "Non-bank Financials": -0.8, "Electronics": 0.8, "Computers": 1.0, "Pharma": 1.0,
                  "Food & Beverage": 1.0, "Machinery": 0.0, "Autos": 0.0, "Chemicals": 0.0, "Real Estate": 3.0},
        "us_session": {"Banks": 0.10, "Non-bank Financials": 0.30, "Electronics": 0.50, "Computers": 0.45,
                       "Pharma": 0.25, "Food & Beverage": 0.15, "Machinery": 0.30, "Autos": 0.35,
                       "Chemicals": 0.30, "Real Estate": 0.15},
    },
}
TS_LOADING_NOISE = {"fx": 0.3, "rates": 0.4, "us_session": 0.1}

TEAMS = {
    "A1_US_STATARB": "TEAM_ALPHA", "A2_CN_STATARB": "TEAM_ALPHA",
    "B1_US_INTRADAY": "TEAM_BRAVO", "C1_US_EVENT": "TEAM_CHARLIE",
    "D1_US_CROWDING": "TEAM_DELTA", "E1_CRYPTO_CARRY": "TEAM_ECHO",
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def trading_calendar(spec: MarketSpec, start: str, end: str) -> pd.DatetimeIndex:
    bd = pd.bdate_range(start, end)
    return bd[~bd.isin(pd.to_datetime(list(spec.holidays)))]


def _z(x: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    x = np.where(np.isfinite(x), x, np.nan)
    if mask is not None:
        x = np.where(mask, x, np.nan)
    if np.all(np.isnan(x)):
        return np.zeros_like(x)
    mu, sd = np.nanmean(x), np.nanstd(x)
    z = (x - mu) / (sd if sd > 0 else 1.0)
    return np.nan_to_num(np.clip(z, -3, 3))


def _t_noise(rng, size, df=4):
    return rng.standard_t(df, size=size) / math.sqrt(df / (df - 2))


def _bridge(rng, target: np.ndarray, scale: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Discrete Brownian bridge: increments with variance scale^2*w_b summing to target."""
    eps = rng.standard_normal(target.shape + (len(w),)) * np.sqrt(w) * scale[..., None]
    return eps - w * eps.sum(-1, keepdims=True) + w * target[..., None]


def _u_shape(n_bars: int) -> np.ndarray:
    x = np.linspace(-1, 1, n_bars)
    w = 1 + 1.5 * x ** 2
    return w / w.sum()


def _nth_weekday(year, month, weekday=4, n=3):
    d = pd.Timestamp(year, month, 1)
    d += pd.Timedelta(days=(weekday - d.weekday()) % 7)
    return d + pd.Timedelta(weeks=n - 1)


def _snap(dates: pd.DatetimeIndex, d: pd.Timestamp, side="left") -> int | None:
    """Index of the trading date on/before (left) or on/after (right) d."""
    if side == "left":
        i = dates.searchsorted(d, "right") - 1
        return i if i >= 0 else None
    i = dates.searchsorted(d, "left")
    return i if i < len(dates) else None


def _minute_to_clock(spec_sessions, minute: np.ndarray) -> np.ndarray:
    """Trading-minute offset (0..session_minutes) -> seconds after midnight."""
    out = np.zeros_like(minute, dtype=float)
    remaining = minute.astype(float).copy()
    assigned = np.zeros(minute.shape, bool)
    for start, end in spec_sessions:
        h0, m0 = map(int, start.split(":"))
        h1, m1 = map(int, end.split(":"))
        length = (h1 * 60 + m1) - (h0 * 60 + m0)
        here = (~assigned) & (remaining <= length)
        out[here] = (h0 * 60 + m0 + remaining[here]) * 60
        assigned |= here
        remaining[~assigned] -= length
    out[~assigned] = out[~assigned]  # beyond session: unreachable by construction
    return out


# --------------------------------------------------------------------------- #
# Equity market simulation
# --------------------------------------------------------------------------- #
class EquitySim:
    """Simulates one local equity market on its own trading calendar."""

    def __init__(self, spec: MarketSpec, cfg: SimConfig, rng: np.random.Generator,
                 n: int, btc_lr_by_day: pd.Series, lead_factor: pd.Series | None,
                 macro: pd.DataFrame, mcal: pd.DataFrame):
        self.spec, self.cfg, self.rng, self.N = spec, cfg, rng, n
        self.dates = trading_calendar(spec, cfg.start, cfg.end)
        self.T = len(self.dates)
        m = mcal[mcal.market == spec.code]
        self.macro_day = self.dates.isin(pd.DatetimeIndex(m.date))
        self.fomc_min = {}
        h0, m0 = map(int, spec.sessions[0][0].split(":"))
        for r in m[m.event.str.contains("FOMC")].itertuples():
            hh, mm = map(int, r.time_local.split(":"))
            k = self.dates.get_indexer([r.date])[0]
            if k >= 0:
                self.fomc_min[k] = (hh * 60 + mm) - (h0 * 60 + m0)
        self._static()
        self._calendars()
        self._simulate(btc_lr_by_day, lead_factor, macro)
        self._raw_prices()
        self._paths()
        self._futures()

    # ---------------- static characteristics ---------------------------- #
    def _static(self):
        rng, N, spec = self.rng, self.N, self.spec
        S = len(spec.sectors)
        p = rng.dirichlet(np.full(S, 6.0))
        self.sector = rng.choice(S, N, p=p)
        prefix = "U" if spec.code == "US" else "C"
        if spec.code == "US":
            self.tickers = np.array([f"{prefix}{i:04d}" for i in range(N)])
            self.log_mcap0 = rng.normal(np.log(8e9), 1.15, N)
            price0 = np.exp(rng.normal(np.log(50), 0.9, N))
            self.turnover_base = np.exp(rng.normal(np.log(0.008), 0.45, N))
            self.si_mean = np.clip(np.exp(rng.normal(np.log(0.03), 0.75, N)), 0.002, 0.35)
            self.shortable = np.ones(N, bool)
            self.lendable = np.maximum(rng.uniform(0.15, 0.30, N), 1.6 * self.si_mean)
        else:
            codes = rng.choice(np.arange(600000, 604000), N // 2, replace=False)
            codes2 = rng.choice(np.arange(1, 3000), N - N // 2, replace=False)
            self.tickers = np.array([f"{c}.SH" for c in codes] + [f"{c:06d}.SZ" for c in codes2])
            self.log_mcap0 = rng.normal(np.log(4e10), 1.0, N)          # CNY
            price0 = np.exp(rng.normal(np.log(12), 0.9, N))
            self.turnover_base = np.exp(rng.normal(np.log(0.022), 0.5, N))
            self.shortable = rng.random(N) < 0.4                        # securities lending
            self.si_mean = np.where(self.shortable,
                                    np.clip(np.exp(rng.normal(np.log(0.006), 0.6, N)), 1e-4, 0.05), 0.0)
            self.lendable = np.where(self.shortable, np.maximum(rng.uniform(0.01, 0.05, N), 1.6 * self.si_mean), 0.0)
        self.price0 = price0
        self.shares0 = np.exp(self.log_mcap0) / price0
        sector_tilt = rng.normal(0, 0.15, S)
        self.beta_true = np.clip(1 + sector_tilt[self.sector] + rng.normal(0, 0.25, N), 0.3, 2.2)
        zsize = _z(self.log_mcap0)
        base = 0.016 - 0.004 * zsize + rng.normal(0, 0.004, N)
        self.spec_vol = np.clip(base * (1.3 if spec.code == "CN" else 1.0), 0.007, 0.045)
        # hidden theme (AI infrastructure) - US only, concentrated in tech/semis
        self.theme = np.zeros(N)
        if spec.code == "US":
            tech = np.isin(self.sector, [0, 1, 2])
            self.theme[(tech & (rng.random(N) < 0.35)) | (rng.random(N) < 0.02)] = 1.0
        # crypto-linked equities (exchanges, miners, treasury companies)
        self.crypto_link = np.zeros(N)
        if spec.code == "US":
            idx = rng.choice(np.where(np.isin(self.sector, [0, 6]))[0], 6, replace=False)
            self.crypto_link[idx] = rng.uniform(0.4, 1.2, 6)
        # time-series shock sensitivities (truth): sector pattern + stock noise
        sec_names = np.array(spec.sectors)[self.sector]
        self.ts_load = {}
        for k, table in TS_SECTOR_LOADINGS[spec.code].items():
            base_k = np.array([table[s] for s in sec_names])
            self.ts_load[k] = base_k + rng.normal(0, TS_LOADING_NOISE[k], N)
        zvol = _z(self.spec_vol)
        self.ts_load["vol_shock"] = -0.03 * zvol + rng.normal(0, 0.012, N)     # beyond market beta
        self.ts_load["liq_shock"] = 0.02 * zsize - 0.01 + rng.normal(0, 0.008, N)
        # intraday: share of the futures move a stock reflects within the same bar
        self.lam = np.clip(0.75 + 0.12 * zsize + rng.normal(0, 0.05, N), 0.4, 0.97)
        # ownership / flow characteristics
        self.retail_base = (np.clip(0.12 - 0.03 * zsize, 0.03, 0.30) if spec.code == "US"
                            else np.clip(0.55 - 0.08 * zsize, 0.25, 0.85))
        self.hf_own = np.clip(rng.uniform(0.02, 0.12, N) + 0.6 * self.si_mean, 0, 0.5)
        self.book0 = np.exp(self.log_mcap0) * np.exp(rng.normal(np.log(0.45), 0.6, N))
        self.roe = rng.normal(0.025, 0.012, N)            # quarterly
        self.margin = np.clip(rng.normal(0.12, 0.08, N), -0.1, 0.4)
        # listings and delistings (survivorship-free history)
        T = self.T
        self.list_idx = np.zeros(N, int)
        self.delist_idx = np.full(N, T + 10)     # survivors: beyond the sample
        late = rng.random(N) < 0.05
        self.list_idx[late] = rng.integers(20, int(T * 0.66), late.sum())
        gone = (~late) & (rng.random(N) < 0.03)
        self.delist_idx[gone] = rng.integers(int(T * 0.33), T - 5, gone.sum())
        t = np.arange(T)[:, None]
        self.alive = (t >= self.list_idx) & (t <= self.delist_idx)

    # ---------------- calendars: earnings, index, splits, divs, halts ---- #
    def _calendars(self):
        rng, N, T, dates, spec = self.rng, self.N, self.T, self.dates, self.spec
        years = sorted(set(dates.year))
        self.earn = np.zeros((T, N), bool)
        self.earn_rows = []
        if spec.code == "US":
            windows = [((1, 20), (2, 20), (12, 31), -1), ((4, 18), (5, 15), (3, 31), 0),
                       ((7, 18), (8, 15), (6, 30), 0), ((10, 18), (11, 15), (9, 30), 0)]
        else:
            windows = [((3, 20), (4, 28), (12, 31), -1), ((8, 10), (8, 29), (6, 30), 0),
                       ((10, 15), (10, 30), (9, 30), 0)]
        position = rng.random(N)
        for y in years:
            for (m0, d0), (m1, d1), (fm, fd), dy in windows:
                lo = _snap(dates, pd.Timestamp(y, m0, d0), "right")
                hi = _snap(dates, pd.Timestamp(y, m1, d1), "left")
                if lo is None or hi is None or hi <= lo:
                    continue
                fpe = pd.Timestamp(y + dy, fm, fd)
                for i in range(N):
                    k = lo + int(round(np.clip(position[i] + rng.normal(0, 0.08), 0, 1) * (hi - lo)))
                    if self.alive[k, i]:
                        self.earn[k, i] = True
                        self.earn_rows.append((self.tickers[i], dates[k], fpe, i, k))
        # index rebalances (third Friday of Mar/Jun/Sep/Dec) and monthly option expiries
        self.rebal_idx = []
        for y in years:
            for m in (3, 6, 9, 12):
                k = _snap(dates, _nth_weekday(y, m), "left")
                if k is not None and 10 < k < T:
                    self.rebal_idx.append(k)
        self.expiry_idx = sorted({_snap(dates, _nth_weekday(d.year, d.month), "left") for d in dates} - {None})
        self.index_event = np.zeros((T, N))
        rank = np.argsort(np.argsort(-self.log_mcap0))
        self.member = rank < int(0.6 * N)
        self.member0 = self.member.copy()
        self.index_rows = []
        # splits / bonus issues and dividends
        self.split = np.ones((T, N))
        self.div_flag = np.zeros((T, N), bool)
        self.div_yield = np.zeros(N)
        start = int(T * 0.15)
        n_split = 6 if spec.code == "US" else 4
        for i in rng.choice(N, n_split, replace=False):
            k = rng.integers(start, T - 5)
            if self.alive[k, i]:
                self.split[k, i] = rng.choice([2.0, 3.0, 4.0]) if spec.code == "US" else rng.choice([1.3, 1.5])
        payers = rng.random(N) < (0.45 if spec.code == "US" else 0.5)
        self.div_yield[payers] = rng.uniform(0.01, 0.045, payers.sum())
        for i in np.where(payers)[0]:
            if spec.code == "US":
                off = rng.integers(0, 3)
                for y in years:
                    for m in range(1 + off, 13, 3):
                        k = _snap(dates, pd.Timestamp(y, m, 12), "right")
                        if k is not None and self.alive[k, i] and self.split[k, i] == 1:
                            self.div_flag[k, i] = True
            else:
                for y in years:
                    k = _snap(dates, pd.Timestamp(y, 6, 15) + pd.Timedelta(days=int(rng.integers(0, 35))), "right")
                    if k is not None and self.alive[k, i] and self.split[k, i] == 1:
                        self.div_flag[k, i] = True
        # trading suspensions (CN multi-day; US single-day news halts)
        self.halted = np.zeros((T, N), bool)
        if spec.code == "CN":
            for i in rng.choice(N, 8, replace=False):
                k = rng.integers(60, T - 15)
                self.halted[k:k + rng.integers(3, 9), i] = True
        else:
            for i in rng.choice(N, 3, replace=False):
                self.halted[rng.integers(60, T - 5), i] = True
        self.halted &= self.alive
        # unscheduled news (the 'in-play' events): a jump with abnormal volume
        self.news = (rng.random((T, N)) < 0.008) & self.alive & ~self.halted & ~self.earn
        self.news[:5] = False

    # ---------------- the main day-by-day simulation --------------------- #
    def _simulate(self, btc_lr: pd.Series, lead: pd.Series | None, macro: pd.DataFrame):
        rng, N, T, spec, dates = self.rng, self.N, self.T, self.spec, self.dates
        S = len(spec.sectors)
        is_cn = spec.code == "CN"
        style_names = ["size", "liquidity", "volatility", "st_reversal", "st_momentum",
                       "overnight_gap", "crowding", "earnings", "index_rebalance", "option_expiry",
                       "corporate_action", "in_play", "value", "momentum_12_1", "earnings_yield",
                       "quality", "long_term_reversal", "theme", "limit_hit", "etf_flow", "retail_attention"]
        self.style_names = style_names
        fac_names = ["market"] + [f"ind_{s}" for s in spec.sectors] + style_names + ["crypto"]
        self.fac_names = fac_names
        K = len(fac_names)
        scale = 1.3 if is_cn else 1.0

        # external drivers aligned to this calendar (moves since the previous session)
        def aligned(level: pd.Series) -> np.ndarray:
            lv = np.log(level)
            return lv.reindex(lv.index.union(dates)).ffill().reindex(dates).diff().fillna(0.0).values
        btc_today = aligned(np.exp(btc_lr.cumsum()))
        fx_today = aligned(macro[spec.fx_series])
        rates_today = aligned(macro[spec.rates_future])
        lead_today = np.zeros(T)
        if lead is not None:
            c = lead.cumsum()
            before = lambda d: c[c.index < d].iloc[-1] if (c.index < d).any() else 0.0
            for t in range(1, T):
                lead_today[t] = before(dates[t]) - before(dates[t - 1])

        # stress shocks and regimes
        shock = [dict() for _ in range(T)]
        forced = np.zeros(T, bool)
        spec_mult_forced = np.ones(T)
        self.stress_rows = []
        for ep in STRESS_EPISODES:
            k = _snap(dates, pd.Timestamp(ep["date"]), "right")
            if k is None:
                continue
            for d in range(ep["days"]):
                if k + d < T:
                    shock[k + d] = ep.get(spec.code, {})
                    spec_mult_forced[k + d] = ep["spec_mult"] if ep.get(spec.code) else 1.0
            if ep.get(spec.code):
                forced[k:k + ep["regime_days"]] = True
                self.stress_rows.append((ep["name"], spec.code, dates[k]))
        regime = np.zeros(T, int)
        for t in range(1, T):
            p_stay = 0.90 if regime[t - 1] else 0.99
            regime[t] = regime[t - 1] if rng.random() < p_stay else 1 - regime[t - 1]
            if forced[t]:
                regime[t] = 1
        self.regime = regime
        mult = np.where(regime == 1, 1.6, 1.0)

        r = np.zeros((T, N)); r_on = np.zeros((T, N)); r_id = np.zeros((T, N))
        u_on = np.zeros((T, N)); u_id = np.zeros((T, N))
        turnover = np.zeros((T, N)); spread = np.zeros((T, N))
        si = np.zeros((T, N)); fee = np.zeros((T, N))
        logmcap = np.zeros((T, N)); book = np.zeros((T, N))
        limit_flag = np.zeros((T, N))
        etf = np.zeros((T, N)); retail = np.zeros((T, N))
        F_on = np.zeros((T, K)); F_id = np.zeros((T, K))
        self.Xgen = np.zeros((T, N, K), dtype=np.float32)
        V = np.zeros(T); L = np.zeros(T); depth = np.zeros(T); dv = np.zeros(T); dl = np.zeros(T)
        Z = {f: np.zeros((T, N)) for f in ["beta_true", "size", "liquidity", "volatility",
                                             "st_reversal", "st_momentum", "overnight_gap",
                                             "crowding", "value", "momentum_12_1", "theme"]}
        logmcap[0] = self.log_mcap0
        book[0] = self.book0
        si[0] = self.si_mean
        fee[0] = np.where(self.shortable, 25.0 if spec.code == "US" else 800.0, np.nan)
        turnover[0] = self.turnover_base
        spread[0] = 5.0
        member = self.member.copy()
        etf_target = np.where(member, rng.uniform(0.10, 0.22, N), rng.uniform(0.02, 0.07, N))
        etf[0] = etf_target
        retail[0] = self.retail_base
        pending = np.zeros(N)          # accumulated return during suspensions
        ind = np.zeros((N, S)); ind[np.arange(N), self.sector] = 1
        sig_m = MARKET_VOL[spec.code]
        h = sig_m ** 2
        omega, a_g, g_g, b_g = sig_m ** 2 * 0.03, 0.02, 0.06, 0.92      # GJR-GARCH(1,1)
        eps_prev = 0.0
        V[0] = VOL_INDEX_BASE[spec.code]; depth[0] = DEPTH_BASE[spec.code]
        earn_report = {k: [] for k in range(T)}
        for (_, _, _, i, k) in self.earn_rows:
            earn_report[k].append(i)
        on_share = MARKET_OVERNIGHT_SHARE[spec.code]
        idx = {f: j for j, f in enumerate(fac_names)}
        expiry = set(self.expiry_idx)
        rebal = set(self.rebal_idx)
        b = self.ts_load

        for t in range(1, T):
            alive = self.alive[t]
            # --- book value updates at report dates (point in time) ---
            book[t] = book[t - 1]
            rep = earn_report[t]
            if rep:
                book[t, rep] *= (1 + self.roe[rep] + rng.normal(0, 0.01, len(rep)))
            # index rebalance decided on mcap a week before effective date
            if t in rebal:
                rank = np.argsort(np.argsort(-np.where(alive, logmcap[max(0, t - 5)], -np.inf)))
                adds = np.where(~member & alive & (rank < int(0.55 * N)))[0]
                dels = np.where(member & ((rank > int(0.65 * N)) | ~alive))[0]
                self.index_event[t, adds] = 1.0
                self.index_event[t, dels] = -1.0
                member[adds] = True; member[dels] = False
                etf_target[adds] += 0.08; etf_target[dels] = np.maximum(etf_target[dels] - 0.08, 0.01)
                for i in adds:
                    self.index_rows.append((dates[t], self.tickers[i], "ADD"))
                for i in dels:
                    self.index_rows.append((dates[t], self.tickers[i], "DELETE"))
            # --- characteristic exposures known at the open of day t ---
            lo5 = max(0, t - 5); lo3 = max(0, t - 3); lo20 = max(0, t - 20)
            zs = {
                "size": _z(logmcap[t - 1], alive),
                "liquidity": _z(np.log(turnover[lo20:t].mean(0) + 1e-9), alive),
                "volatility": _z(r[lo20:t].std(0) if t > 2 else self.spec_vol, alive),
                "st_reversal": _z(-r[lo5:t].sum(0), alive),
                "st_momentum": _z(r_id[lo3:t].sum(0), alive),
                "overnight_gap": _z(r_on[lo5:t].sum(0), alive),
                "crowding": _z(si[t - 1], alive & (self.si_mean > 0)),
                "value": _z(np.log(book[t] / np.exp(logmcap[t - 1])), alive),
                "momentum_12_1": _z(r[max(0, t - 252):max(1, t - 21)].sum(0), alive) if t > 126 else np.zeros(N),
                "earnings_yield": _z(self.roe + rng.normal(0, 0.002, N) - (logmcap[t - 1] - np.log(book[t])) * 0.01, alive),
                "quality": _z(self.margin, alive),
                "long_term_reversal": _z(-r[max(0, t - 756):max(1, t - 252)].sum(0), alive) if t > 300 else np.zeros(N),
                "theme": self.theme,
                "earnings": self.earn[t].astype(float),
                "index_rebalance": self.index_event[t],
                "option_expiry": member.astype(float) if t in expiry else np.zeros(N),
                "corporate_action": ((self.split[t] != 1) | self.div_flag[t]).astype(float),
                "in_play": (self.news[t - 1] & alive).astype(float),
                "limit_hit": limit_flag[t - 1] if is_cn else np.zeros(N),
                "etf_flow": _z(etf[t - 1], alive),
                "retail_attention": _z(np.log(retail[t - 1] + 1e-6), alive),
            }
            for f in Z:
                Z[f][t] = self.beta_true if f == "beta_true" else zs[f]

            X = np.zeros((N, K))
            X[:, 0] = self.beta_true
            X[:, 1:1 + S] = ind
            for f in style_names:
                X[:, idx[f]] = zs[f]
            X[:, idx["crypto"]] = self.crypto_link
            self.Xgen[t] = X

            # --- market factor, implied vol and liquidity state ---
            sh = shock[t]
            m_t = mult[t]
            h = omega + (a_g + g_g * (eps_prev < 0)) * eps_prev ** 2 + b_g * h
            sig_t = math.sqrt(h) * m_t
            if "market" in sh:
                eps = sh["market"] * sig_t
            else:
                eps = sig_t * _t_noise(rng, None, 5) * (1.4 if self.macro_day[t] else 1.0)
            eps_prev = eps / m_t
            mkt = 0.0004 + eps
            h_next = omega + (a_g + g_g * (eps_prev < 0)) * eps_prev ** 2 + b_g * h
            V[t] = 100 * math.sqrt(252 * h_next) * m_t ** 0.7 * 1.15 * math.exp(0.03 * rng.standard_normal())
            dv[t] = math.log(V[t] / V[t - 1])
            jump = 0.3 if (sh and spec_mult_forced[t] >= 1.5) else 0.0
            L[t] = (0.94 * L[t - 1] + 0.06 * (0.35 if regime[t] else 0.0) + 0.035 * rng.standard_normal()
                    + jump + 0.08 * max(-eps / sig_t - 1.0, 0.0))
            dl[t] = L[t] - L[t - 1]
            depth[t] = DEPTH_BASE[spec.code] * math.exp(-1.3 * L[t] + 0.08 * rng.standard_normal())

            # --- other factor returns ---
            q = rng.standard_normal()                # common 'quant crowding' shock
            f_tot = np.zeros(K)
            f_tot[0] = mkt
            f_tot[1:1 + S] = rng.normal(0, INDUSTRY_VOL * scale * m_t ** 0.8, S)
            for f in style_names:
                vol, mu, _ = EQUITY_FACTOR_PARAMS[f]
                vol *= scale * m_t ** 0.8
                if f == "st_reversal":
                    if is_cn:
                        mu, vol = 0.0006, vol * 1.2
                    mu *= V[t - 1] / VOL_INDEX_BASE[spec.code]      # paid more for liquidity when vol is high
                if f == "etf_flow" and t in rebal:
                    vol *= 3.0
                zf = rng.standard_normal()
                if f == "st_reversal":
                    zf = math.sqrt(0.7) * zf + math.sqrt(0.3) * q
                elif f == "crowding":
                    zf = math.sqrt(0.7) * zf - math.sqrt(0.3) * q
                f_tot[idx[f]] = mu + vol * (sh[f] if f in sh else zf)
                # Nagel (2012): liquidity provision loses when liquidity evaporates
                if f == "st_reversal" and f not in sh:
                    f_tot[idx[f]] += vol * (-0.35 * dl[t] / 0.035 - 0.2 * dv[t] / 0.06)
                if f == "liquidity" and f not in sh:
                    f_tot[idx[f]] += vol * 0.3 * dl[t] / 0.035
            if "beta" in sh:
                f_tot[0] += sh["beta"] * 0.002
            f_tot[idx["crypto"]] = btc_today[t] * (1.0 + sh.get("crypto_amp", 0.0))
            # split into overnight / intraday
            phi = np.full(K, 0.4)
            phi[0] = on_share
            for f in style_names:
                phi[idx[f]] = EQUITY_FACTOR_PARAMS[f][2]
            phi[idx["crypto"]] = 0.6
            w_on = rng.normal(phi, 0.15).clip(0, 1)
            w_on[[idx["overnight_gap"]]] = 1.0
            w_on[[idx["st_momentum"]]] = 0.0
            f_on = f_tot * w_on
            f_id = f_tot - f_on
            F_on[t], F_id[t] = f_on, f_id

            # --- time-series shock contributions (r = Xf + Bg + u) ---
            ts = b["fx"] * fx_today[t] + b["rates"] * rates_today[t] + b["vol_shock"] * dv[t] + b["liq_shock"] * dl[t]
            ts_on = 0.4 * ts + (b["us_session"] * lead_today[t] if is_cn else 0.0)
            ts_id = 0.6 * ts

            # --- specific returns ---
            sv = self.spec_vol * math.sqrt(m_t) * spec_mult_forced[t]
            ev = self.earn[t]
            nw = self.news[t]
            ip = self.news[t - 1]
            sv = np.where(ev, sv * 3.0, np.where(nw, sv * 5.0, np.where(ip, sv * 2.2, sv)))
            phi_s = np.where(ev, 0.8, np.where(nw, 0.6, 0.35))
            e_on = _t_noise(rng, N) * sv * np.sqrt(phi_s)
            e_id = _t_noise(rng, N) * sv * np.sqrt(1 - phi_s)
            ro = X @ f_on + ts_on + e_on
            ri = X @ f_id + ts_id + e_id
            rt = (1 + ro) * (1 + ri) - 1
            # suspensions: no price change, accumulate and release on resumption
            hal = self.halted[t]
            resume = (~hal) & self.halted[t - 1]
            pending[hal] = (1 + pending[hal]) * (1 + rt[hal]) - 1
            rt[resume] = (1 + pending[resume]) * (1 + rt[resume]) - 1
            ro[resume] = (1 + pending[resume]) * (1 + ro[resume]) - 1
            pending[resume] = 0
            rt[hal] = 0; ro[hal] = 0
            # CN price limits (not applied on resumption day)
            if spec.price_limit:
                lim = spec.price_limit - 1e-4
                ro = np.where(resume, ro, np.clip(ro, -lim, lim))
                hit_up = (rt > lim) & ~resume
                hit_dn = (rt < -lim) & ~resume
                rt = np.where(hit_up, lim, np.where(hit_dn, -lim, rt))
                limit_flag[t] = hit_up.astype(float) - hit_dn.astype(float)
            ri = (1 + rt) / (1 + ro) - 1
            ri[hal] = 0
            r[t], r_on[t], r_id[t] = rt, ro, ri
            u_on[t], u_id[t] = e_on, e_id

            # --- liquidity, spreads, short interest, flows evolve ---
            logmcap[t] = logmcap[t - 1] + np.log1p(rt)
            zsize = _z(logmcap[t], alive)
            tov = (self.turnover_base * np.exp(0.35 * rng.standard_normal(N))
                   * (1 + 25 * np.abs(e_on + e_id)) * np.where(ev, 2.5, 1.0) * np.where(nw, 4.0, 1.0)
                   * np.where(self.index_event[t] != 0, 3.0, 1.0)
                   * np.where((t in expiry) & member, 1.8, 1.0) * m_t ** 0.5 * math.exp(0.5 * L[t]))
            tov[hal] = 0
            turnover[t] = tov
            base_spread = (3.0 if spec.code == "US" else 6.0) * np.exp(-0.45 * zsize)
            spread[t] = np.clip(base_spread * m_t ** 0.7 * math.exp(L[t]) * (1 + 15 * np.abs(rt))
                                * np.exp(0.15 * rng.standard_normal(N)), 0.8, 120)
            si[t] = np.clip(si[t - 1] + 0.02 * (self.si_mean - si[t - 1])
                            + 0.04 * si[t - 1] * rng.standard_normal(N)
                            - 0.3 * si[t - 1] * np.maximum(rt, 0) * (sh.get("crowding", 0) > 2),
                            0, 0.95 * self.lendable)
            si[t][~self.shortable] = 0
            util = np.where(self.lendable > 0, si[t] / np.maximum(self.lendable, 1e-9), 0)
            gc = 25.0 if spec.code == "US" else 800.0
            fee[t] = np.where(self.shortable,
                              gc + 4000 * np.maximum(si[t] - 0.08, 0) ** 1.3 * 10
                              + 1500 * np.maximum(util - 0.6, 0) ** 1.5 + np.abs(rng.normal(0, 3, N)), np.nan)
            etf[t] = np.clip(etf[t - 1] + 0.15 * (etf_target - etf[t - 1]) + rng.normal(0, 0.001, N), 0.005, 0.5)
            squeeze = sh.get("crowding", 0) > 3
            retail[t] = np.clip(self.retail_base * np.exp(0.25 * rng.standard_normal(N)) * (1 + 2.0 * nw)
                                * (1 + 1.5 * squeeze * (si[t - 1] > 0.08)), 0.01, 0.95)

        self.r, self.r_on, self.r_id = r, r_on, r_id
        self.u_on, self.u_id, self.u = u_on, u_id, u_on + u_id
        self.turnover, self.spread, self.si, self.fee = turnover, spread, si, fee
        self.logmcap, self.book, self.limit_flag = logmcap, book, limit_flag
        self.etf, self.retail = etf, retail
        self.F_on = pd.DataFrame(F_on, index=dates, columns=fac_names)
        self.F_id = pd.DataFrame(F_id, index=dates, columns=fac_names)
        self.Z = Z
        self.member_final = member
        self.vol_index, self.depth, self.liq_state = V, depth, L
        self.shocks = pd.DataFrame({"vol_shock": dv, "liq_shock": dl, "fx": fx_today, "rates": rates_today,
                                    "us_session": lead_today}, index=dates)

    # ---------------- raw (unadjusted) prices ---------------------------- #
    def _raw_prices(self):
        T, N, rng = self.T, self.N, self.rng
        close = np.zeros((T, N)); opn = np.zeros((T, N)); div = np.zeros((T, N))
        shares = np.zeros((T, N))
        close[0] = self.price0; opn[0] = self.price0; shares[0] = self.shares0
        for t in range(1, T):
            prev = close[t - 1]
            d = np.where(self.div_flag[t], prev * self.div_yield / (4 if self.spec.code == "US" else 1), 0.0)
            div[t] = d
            s = self.split[t]
            close[t] = (prev * (1 + self.r[t]) - d) / s
            opn[t] = (prev * (1 + self.r_on[t]) - d) / s
            shares[t] = shares[t - 1] * s
        tick = self.spec.tick_size
        self.close = np.round(close / tick) * tick
        self.close = np.maximum(self.close, tick)
        self.open = np.maximum(np.round(opn / tick) * tick, tick)
        self.div = np.round(div, 4)
        self.shares = shares
        # a quoted spread cannot be narrower than one tick (relative tick size)
        self.spread = np.maximum(self.spread, 1e4 * tick / np.vstack([self.close[:1], self.close[:-1]]))
        self.volume = np.round(self.turnover * shares / self.spec.lot_size) * self.spec.lot_size
        self.dollar_vol = self.volume * self.close
        self.adv = pd.DataFrame(self.dollar_vol).rolling(20, min_periods=5).mean().shift(1).bfill().values
        self.adv_sh = pd.DataFrame(self.volume).rolling(20, min_periods=5).mean().shift(1).bfill().values
        self.sigma_d = pd.DataFrame(self.r).rolling(20, min_periods=5).std().shift(1).bfill().fillna(0.02).values

    # ---------------- intraday price paths ------------------------------- #
    def _paths(self):
        """Intraday paths.  Index futures carry the market move first; each stock reflects only
        a share lam_i of it within the same bar and catches up in the next one (Epps effect).
        FOMC releases add a volatility burst in the bar containing the announcement."""
        rng, T, N = self.rng, self.T, self.N
        B = self.spec.n_bars
        w = _u_shape(B)
        W = np.tile(w, (T, 1))
        for t, minute in self.fomc_min.items():
            bb = int(np.clip(minute // self.spec.bar_minutes, 0, B - 1))
            W[t, bb] *= 4.0
        W /= W.sum(1, keepdims=True)
        target = np.log(self.close / self.open)
        mkt_lr = np.log1p(self.F_id["market"].values)
        e = rng.standard_normal((T, B)) * np.sqrt(W) * MARKET_VOL[self.spec.code] * 0.8
        m_bars = e - W * e.sum(1, keepdims=True) + W * mkt_lr[:, None]
        # other factors and time-series shocks diffuse through the day at the factor level, so
        # bars keep a cross-sectional factor structure (not a deterministic share of the daily move)
        Fid = self.F_id.values.copy()
        Fid[:, 0] = 0.0
        sc = Fid.std(0)
        ef = rng.standard_normal((T, B, Fid.shape[1])) * np.sqrt(W)[..., None] * sc
        f_bars = ef - W[..., None] * ef.sum(1, keepdims=True) + W[..., None] * Fid[:, None, :]
        fac = np.einsum("tik,tbk->tib", self.Xgen, f_bars.astype(np.float32))
        G = 0.6 * self.shocks[["fx", "rates", "vol_shock", "liq_shock"]].values
        eg = rng.standard_normal((T, B, 4)) * np.sqrt(W)[..., None] * G.std(0)
        g_bars = eg - W[..., None] * eg.sum(1, keepdims=True) + W[..., None] * G[:, None, :]
        Lts = np.column_stack([self.ts_load[k] for k in ("fx", "rates", "vol_shock", "liq_shock")])
        fac = fac + np.einsum("ik,tbk->tib", Lts, g_bars)
        lam = self.lam
        m_lag = np.concatenate([np.zeros((T, 1)), m_bars[:, :-1]], 1)
        bt = self.beta_true
        common = bt[None, :, None] * (lam[None, :, None] * m_bars[:, None, :]
                                      + (1 - lam)[None, :, None] * m_lag[:, None, :])
        common[:, :, -1] += (bt * (1 - lam))[None, :] * m_bars[:, -1][:, None]   # closing-auction catch-up
        idio_target = target - common.sum(-1) - fac.sum(-1)
        idio_scale = np.broadcast_to(self.spec_vol * 0.8, (T, N))
        idio = _bridge(rng, idio_target, idio_scale, w)
        lr = common + fac + idio
        path = np.empty((T, N, B + 1))
        path[:, :, 0] = self.open
        path[:, :, 1:] = self.open[..., None] * np.exp(np.cumsum(lr, -1))
        path[self.halted] = self.close[self.halted][:, None]
        self.path = path
        self.m_bars, self.idio_lr, self.bar_W = m_bars, idio, W
        del self.Xgen
        self.high = np.maximum(path.max(-1) * (1 + np.abs(rng.normal(0, 0.002, (T, N)))), self.close)
        self.low = np.minimum(path.min(-1) * (1 - np.abs(rng.normal(0, 0.002, (T, N)))), self.close)
        self.vwap = path[:, :, 1:].mean(-1)
        self.bar_w = w

    def _futures(self):
        """Index futures on the cap-weighted index of current members."""
        T, rng = self.T, self.rng
        mc = np.exp(self.logmcap)
        wts = np.vstack([mc[:1], mc[:-1]]) * self.alive * ~self.halted
        wts = wts / wts.sum(1, keepdims=True)
        idx_ret = (wts * self.r).sum(1)
        idx_on = (wts * self.r_on).sum(1)
        level = FUT_LEVEL0[self.spec.code] * np.cumprod(1 + idx_ret)
        basis = 1 + rng.normal(0.0005, 0.0003, T)
        self.fut_close = level * basis
        prev_level = np.r_[level[0], level[:-1]]
        self.fut_open = prev_level * (1 + idx_on) * (1 + rng.normal(0.0005, 0.0003, T))
        self.fut_lr = pd.Series(np.log(self.fut_close / np.r_[self.fut_close[0], self.fut_close[:-1]]), index=self.dates)
        # intraday futures path: market-factor bars plus an even drift so the close matches
        B = self.spec.n_bars
        drift = (np.log(self.fut_close / self.fut_open) - self.m_bars.sum(1)) / B
        self.fut_path = self.fut_open[:, None] * np.exp(np.concatenate(
            [np.zeros((T, 1)), np.cumsum(self.m_bars + drift[:, None], 1)], 1))

    def price_at(self, t: np.ndarray, i: np.ndarray, minute: np.ndarray) -> np.ndarray:
        b = np.clip(minute / self.spec.bar_minutes, 0, self.spec.n_bars - 1e-9)
        lo = np.floor(b).astype(int)
        frac = b - lo
        p0 = self.path[t, i, lo]
        p1 = self.path[t, i, lo + 1]
        return p0 + frac * (p1 - p0)


# --------------------------------------------------------------------------- #
# Crypto simulation (24/7, calendar days)
# --------------------------------------------------------------------------- #
CRYPTO_UNIVERSE = [
    ("BTC", "Store of Value"), ("ETH", "Smart Contract L1"), ("SOL", "Smart Contract L1"),
    ("BNB", "Exchange Token"), ("XRP", "Infrastructure"), ("ADA", "Smart Contract L1"),
    ("AVAX", "Smart Contract L1"), ("DOT", "Infrastructure"), ("LINK", "Infrastructure"),
    ("UNI", "DeFi"), ("AAVE", "DeFi"), ("MKR", "DeFi"), ("LDO", "DeFi"), ("ARB", "Infrastructure"),
    ("OP", "Infrastructure"), ("ATOM", "Infrastructure"), ("NEAR", "Smart Contract L1"),
    ("FIL", "Infrastructure"), ("DOGE", "Meme"), ("SHIB", "Meme"), ("PEPE", "Meme"),
    ("OKB", "Exchange Token"), ("CRV", "DeFi"), ("INJ", "DeFi"), ("TRX", "Smart Contract L1"),
    ("LTC", "Store of Value"), ("BCH", "Store of Value"), ("ETC", "Smart Contract L1"),
    ("XLM", "Infrastructure"), ("HBAR", "Infrastructure"), ("APT", "Smart Contract L1"),
    ("SUI", "Smart Contract L1"), ("SEI", "Smart Contract L1"), ("TIA", "Infrastructure"),
    ("RUNE", "DeFi"), ("GRT", "Infrastructure"), ("SNX", "DeFi"), ("CRO", "Exchange Token"),
    ("WIF", "Meme"), ("BONK", "Meme"),
]


class CryptoSim:
    def __init__(self, cfg: SimConfig, rng: np.random.Generator, n: int):
        self.cfg, self.rng = cfg, rng
        self.dates = pd.date_range(cfg.start, cfg.end, freq="D")
        uni = CRYPTO_UNIVERSE[:n]
        self.symbols = np.array([s for s, _ in uni])
        self.sector_names = [c for _, c in uni]
        self.sector = np.array([CRYPTO_SECTORS.index(c) for c in self.sector_names])
        self.N, self.T = len(uni), len(self.dates)
        self._simulate()

    def _simulate(self):
        rng, T, N, dates = self.rng, self.T, self.N, self.dates
        S = len(CRYPTO_SECTORS)
        is_btc = self.symbols == "BTC"
        rank = np.arange(N)
        self.log_mcap0 = np.log(1.2e12) - 0.22 * rank + rng.normal(0, 0.3, N)
        self.log_mcap0[is_btc] = np.log(1.2e12)
        self.beta_btc = np.where(is_btc, 1.0, np.clip(rng.normal(1.15, 0.25, N), 0.6, 1.8))
        self.beta_alt = np.where(is_btc, 0.0, np.clip(rng.normal(1.0, 0.3, N), 0.3, 1.8))
        self.spec_vol = np.where(is_btc, 0.004, np.clip(0.025 + 0.004 * rank / 3 + rng.normal(0, 0.006, N), 0.015, 0.07))
        self.venue = np.where(rng.random(N) < 0.3, "VENUE_B", "VENUE_A")
        self.venue[:2] = "VENUE_A"
        unlock = np.zeros((T, N), bool)
        cand = np.where(np.isin(self.sector, [2, 4, 1]) & ~is_btc)[0]
        for _ in range(40):
            unlock[rng.integers(30, T - 2), rng.choice(cand)] = True
        unlock[:, :2] = False
        self.unlock = unlock

        shock = [dict() for _ in range(T)]
        regime = np.zeros(T, int)
        forced = np.zeros(T, bool)
        smult = np.ones(T)
        for ep in STRESS_EPISODES:
            if "CRYPTO" not in ep:
                continue
            k = dates.searchsorted(pd.Timestamp(ep["date"]))
            if k < T:
                shock[k] = ep["CRYPTO"]
                smult[k] = ep["spec_mult"]
                forced[k:k + ep["regime_days"]] = True
        for t in range(1, T):
            p = 0.93 if regime[t - 1] else 0.985
            regime[t] = regime[t - 1] if rng.random() < p else 1 - regime[t - 1]
            regime[t] = 1 if forced[t] else regime[t]
        mult = np.where(regime == 1, 1.8, 1.0)
        self.regime = regime

        r = np.zeros((T, N)); u = np.zeros((T, N))
        funding = np.zeros((T, N)); basis = np.zeros((T, N)); vol_usd = np.zeros((T, N))
        logmcap = np.zeros((T, N)); logmcap[0] = self.log_mcap0
        fnames = ["btc", "alt"] + [f"sec_{s}" for s in CRYPTO_SECTORS] + ["size", "momentum", "funding", "token_unlock"]
        F = np.zeros((T, len(fnames)))
        h = 0.028 ** 2
        eps_prev = 0.0
        funding[0] = 0.0003
        for t in range(1, T):
            m = mult[t]; sh = shock[t]
            h = 0.028 ** 2 * 0.03 + 0.07 * eps_prev ** 2 + 0.90 * h
            sig = math.sqrt(h) * m
            eps = sh["btc"] * sig if "btc" in sh else sig * _t_noise(rng, None, 4)
            eps_prev = eps / m
            btc = 0.0012 + eps
            alt = (sh["alt"] * 0.018 * m) if "alt" in sh else rng.normal(0.0, 0.018 * m)
            secs = rng.normal(0, 0.012 * m, S)
            size_f = rng.normal(0, 0.006 * m)
            mom_f = rng.normal(0.0005, 0.008 * m)
            fund_f = (sh["funding"] * 0.005 * m) if "funding" in sh else rng.normal(-0.0003, 0.005 * m)
            unl_f = rng.normal(-0.02, 0.01)
            mom = _z(r[max(0, t - 7):t].sum(0))
            fz = _z(funding[t - 1])
            sz = _z(logmcap[t - 1])
            ret = (self.beta_btc * btc + self.beta_alt * alt + secs[self.sector] + size_f * sz
                   + mom_f * mom + fund_f * fz + unl_f * self.unlock[t])
            ret[is_btc] = btc
            e = _t_noise(rng, N, 3) * self.spec_vol * math.sqrt(m) * smult[t]
            e[is_btc] = 0.0
            rt = np.maximum(ret + e, -0.6)
            r[t] = rt; u[t] = e
            F[t] = [btc, alt, *secs, size_f, mom_f, fund_f, unl_f]
            logmcap[t] = logmcap[t - 1] + np.log1p(rt)
            funding[t] = np.clip(0.7 * funding[t - 1] + 0.3 * 0.0003
                                 + 0.004 * r[max(0, t - 3):t + 1].sum(0) * 0.3
                                 + rng.normal(0, 0.0002, N), -0.003, 0.004)
            basis[t] = funding[t] * 2.5 + rng.normal(0, 0.0004, N)
            vol_usd[t] = np.exp(logmcap[t]) * np.exp(rng.normal(np.log(0.03), 0.3, N)) * m
        self.r, self.u, self.funding, self.basis = r, u, funding, basis
        self.F = pd.DataFrame(F, index=dates, columns=fnames)
        self.logmcap = logmcap
        self.vol_usd = vol_usd
        p0 = np.exp(rng.normal(np.log(5), 1.5, N))
        p0[is_btc] = 43000.0
        p0[self.symbols == "ETH"] = 2300.0
        self.spot = p0 * np.cumprod(1 + r, 0)
        self.perp = self.spot * (1 + basis)
        self.adv = pd.DataFrame(vol_usd).rolling(14, min_periods=3).mean().shift(1).bfill().values
        self.sigma_d = pd.DataFrame(r).rolling(20, min_periods=5).std().shift(1).bfill().fillna(0.04).values
        # hourly bridge path for fills (perp)
        w = np.full(24, 1 / 24)
        prev = np.vstack([self.perp[:1], self.perp[:-1]])
        lr = _bridge(rng, np.log(self.perp / prev), np.broadcast_to(self.spec_vol + 0.02, (T, N)), w)
        path = np.empty((T, N, 25))
        path[:, :, 0] = prev
        path[:, :, 1:] = prev[..., None] * np.exp(np.cumsum(lr, -1))
        self.path = path

    @property
    def btc_log_returns(self) -> pd.Series:
        return pd.Series(np.log1p(self.r[:, 0]), index=self.dates)


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
def _cs_z(x, mask):
    out = np.full_like(x, np.nan, dtype=float)
    mask = mask & np.isfinite(x)
    if mask.sum() < 3:
        return out
    v = x[mask]
    out[mask] = (v - v.mean()) / (v.std() + 1e-12)
    return out


def _long_short(score, long_ok, short_ok, n_side):
    """Rank-weighted dollar-neutral weights (sum |w| = 1)."""
    w = np.zeros(len(score))
    s_long = np.where(long_ok & np.isfinite(score), score, -np.inf)
    s_short = np.where(short_ok & np.isfinite(score), score, np.inf)
    nl = min(n_side, int(np.isfinite(s_long).sum()))
    ns = min(n_side, int(np.isfinite(s_short).sum()))
    if nl < 2 or ns < 2:
        return w
    li = np.argsort(-s_long)[:nl]
    si = np.argsort(s_short)[:ns]
    common = np.intersect1d(li, si)
    li = np.setdiff1d(li, common); si = np.setdiff1d(si, common)
    wl = np.linspace(1.5, 0.5, len(li)); ws = np.linspace(1.5, 0.5, len(si))
    w[li] = 0.5 * wl / wl.sum()
    w[si] = -0.5 * ws / ws.sum()
    return w


@dataclass
class StrategyDef:
    name: str
    market: str
    gmv_usd: float
    n_side: int
    persistence: float
    alpha: float
    description: str
    holding: str


class StrategySimulator:
    """Turns black-box scores into EOD positions and child-order fills."""

    def __init__(self, sim: EquitySim, fx_local_per_usd: np.ndarray, start: pd.Timestamp, rng):
        self.sim, self.fx, self.rng = sim, fx_local_per_usd, rng
        self.t0 = int(sim.dates.searchsorted(start))
        self.orders = []

    def eligibility(self, t):
        s = self.sim
        age = t - s.list_idx
        ok = (s.alive[t] & s.alive[t - 1] & (age >= 20) & (s.delist_idx > t + 1)
              & ~s.halted[t] & (s.close[t - 1] > 1.0) & (s.adv[t] / self.fx[t] > 5e6))
        return ok

    def run_daily(self, sd: StrategyDef, score_fn):
        s = self.sim
        T, N = s.T, s.N
        lot = s.spec.lot_size
        shares = np.zeros((T, N))
        w_prev = np.zeros(N)
        for t in range(self.t0, T):
            prev_sh = shares[t - 1] * s.split[t]
            ok = self.eligibility(t)
            raw = score_fn(t, ok)
            z = _cs_z(raw, ok)
            if t + 1 < T:
                z = z + sd.alpha * _cs_z(s.u[t + 1], ok)
            target = _long_short(z, ok, ok & s.shortable, sd.n_side)
            w = (1 - sd.persistence) * target + sd.persistence * w_prev
            w[~ok] = 0.0
            nz = np.abs(w) > 0
            if nz.any():
                w[np.abs(w) < 0.2 * np.abs(w[nz]).mean()] = 0.0
            g = np.abs(w).sum()
            if g > 0:
                w /= g
            p_dec = s.close[t - 1] / s.split[t]
            sh = np.round(w * sd.gmv_usd * self.fx[t] / p_dec / lot) * lot
            sh[s.halted[t]] = prev_sh[s.halted[t]]
            shares[t] = sh
            w_prev = w
            qty = sh - prev_sh
            ii = np.where(qty != 0)[0]
            for i in ii:
                self.orders.append((sd.name, t, i, qty[i], 5.0, s.spec.session_minutes - 5.0,
                                    p_dec[i], -1.0))
        return shares

    def run_intraday(self, sd: StrategyDef, coef_fn, carry=0.15):
        s = self.sim
        T, N = s.T, s.N
        shares = np.zeros((T, N))
        open_sh = np.zeros((T, N))
        for t in range(self.t0, T):
            prev_sh = shares[t - 1] * s.split[t]
            ok = self.eligibility(t) & (s.adv[t] > 2e7)
            gap_coef = coef_fn(t)
            z = gap_coef * _cs_z(-s.r_on[t], ok) + 0.3 * _cs_z(s.Z["st_momentum"][t], ok) \
                + 0.4 * _cs_z(-s.Z["size"][t], ok)
            z = z + sd.alpha * _cs_z(s.u_id[t], ok) + 0.5 * self.rng.standard_normal(N)
            w = _long_short(z, ok, ok, sd.n_side)
            # the desk neutralises intraday beta with betas from concurrent 30-minute returns,
            # which understate the beta of slow-to-react (small) names - the Epps effect
            b_conc = s.beta_true * s.lam
            lo_, sh_ = (w * b_conc)[w > 0].sum(), -(w * b_conc)[w < 0].sum()
            if lo_ > 0 and sh_ > 0:
                w = np.where(w > 0, w * 2 * sh_ / (lo_ + sh_), w * 2 * lo_ / (lo_ + sh_))
            ti = np.full(N, t)
            p_dec_m = s.price_at(ti, np.arange(N), np.full(N, 10.0))
            n_open = np.round(w * sd.gmv_usd * self.fx[t] / p_dec_m)
            n_eod = np.round(carry * n_open)
            n_open[s.halted[t]] = prev_sh[s.halted[t]]
            n_eod[s.halted[t]] = prev_sh[s.halted[t]]
            open_sh[t] = n_open
            shares[t] = n_eod
            p_dec_a = s.price_at(ti, np.arange(N), np.full(N, 325.0))
            q1 = n_open - prev_sh
            q2 = n_eod - n_open
            for i in np.where(q1 != 0)[0]:
                self.orders.append((sd.name, t, i, q1[i], 15.0, 60.0, p_dec_m[i], 10.0))
            for i in np.where(q2 != 0)[0]:
                self.orders.append((sd.name, t, i, q2[i], 330.0, 385.0, p_dec_a[i], 325.0))
        return shares, open_sh

    def fills(self) -> pd.DataFrame:
        s, rng, spec = self.sim, self.rng, self.sim.spec
        if not self.orders:
            return pd.DataFrame()
        o = pd.DataFrame(self.orders, columns=["strategy", "t", "i", "qty", "m0", "m1", "dec_px", "dec_min"])
        t = o.t.values; i = o.i.values; qty = o.qty.values
        lot = spec.lot_size
        part = np.abs(qty) / np.maximum(s.adv_sh[t, i], 1)
        k = np.clip(np.ceil(part / 0.01), 1, 4).astype(int)
        lots = np.abs(qty) / lot
        k = np.minimum(k, np.maximum(lots, 1)).astype(int)
        rep = np.repeat(np.arange(len(o)), k)
        start = np.repeat(np.cumsum(k) - k, k)
        j = np.arange(len(rep)) - start
        kk = k[rep]
        base = np.floor(lots[rep] / kk)
        rem = lots[rep] - base * kk
        child = (base + (j < rem)) * lot * np.sign(qty[rep])
        m0, m1 = o.m0.values[rep], o.m1.values[rep]
        minute = m0 + (m1 - m0) * (j + rng.uniform(0.1, 0.9, len(rep))) / kk
        tt, ii = t[rep], i[rep]
        mid = s.price_at(tt, ii, minute)
        first = np.repeat(np.arange(len(o)), k)
        arrival = s.price_at(t, i, o.m0.values)[first]
        side = np.sign(child)
        half_spread = s.spread[tt, ii] / 2e4
        impact = 0.3 * s.sigma_d[tt, ii] * np.sqrt(part[rep]) * (j + 1) / kk
        px = mid * (1 + side * (half_spread + impact))
        px = np.round(px, 2 if spec.code == "US" else 2)
        notional = np.abs(child) * px
        commission = notional * spec.commission_bps / 1e4 + (0.1 / 1e4 * notional if spec.code == "CN" else 0)
        fees = np.where(side < 0, notional * spec.sell_tax_bps / 1e4, 0.0)
        secs = _minute_to_clock(spec.sessions, minute)
        dts = s.dates[tt] + pd.to_timedelta(np.round(secs), unit="s")
        dec_min = o.dec_min.values[rep]
        dec_secs = np.where(dec_min < 0, np.nan, _minute_to_clock(spec.sessions, np.maximum(dec_min, 0)))
        prev_close_time = s.dates[np.maximum(tt - 1, 0)] + pd.Timedelta(hours=16 if spec.code == "US" else 15)
        dec_ts = np.where(np.isnan(dec_secs), prev_close_time,
                          s.dates[tt] + pd.to_timedelta(np.nan_to_num(dec_secs), unit="s"))
        df = pd.DataFrame({
            "date": s.dates[tt], "timestamp": dts, "strategy": o.strategy.values[rep],
            "ticker": s.tickers[ii], "venue": "XNYS/XNAS" if spec.code == "US" else "XSHG/XSHE",
            "side": np.where(side > 0, "BUY", "SELL"), "quantity": child, "price": px,
            "decision_price": np.round(o.dec_px.values[rep], 4), "decision_time": pd.to_datetime(dec_ts),
            "arrival_price": np.round(arrival, 4), "commission": np.round(commission, 2),
            "fees": np.round(fees, 2), "currency": spec.currency,
            "tz": "America/New_York" if spec.code == "US" else "Asia/Shanghai",
        })
        df = df[df.quantity != 0]
        df["_t"], df["_i"] = tt[child != 0], ii[child != 0]
        return df


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def macro_calendar(cfg: SimConfig) -> pd.DataFrame:
    """Scheduled macro announcements with local release times (to the minute)."""
    rows = []
    years = range(pd.Timestamp(cfg.start).year, pd.Timestamp(cfg.end).year + 1)
    fomc = [(1, 4), (3, 3), (5, 1), (6, 3), (7, 4), (9, 3), (11, 1), (12, 2)]   # (month, nth Wednesday)
    for y in years:
        for m in range(1, 13):
            rows += [("US", _nth_weekday(y, m, 4, 1), "08:30", "Nonfarm payrolls"),
                     ("US", _nth_weekday(y, m, 2, 2), "08:30", "CPI"),
                     ("CN", pd.Timestamp(y, m, 10), "09:30", "CPI"),
                     ("CN", pd.Timestamp(y, m, 20), "09:00", "Loan prime rate"),
                     ("CN", pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0), "09:30", "Official PMI")]
        rows += [("US", _nth_weekday(y, m, 2, n), "14:00", "FOMC decision") for m, n in fomc]
    df = pd.DataFrame(rows, columns=["market", "date", "time_local", "event"])
    out = []
    for mkt, spec in (("US", US), ("CN", CN)):
        cal = trading_calendar(spec, cfg.start, cfg.end)
        d = df[df.market == mkt].copy()
        k = cal.searchsorted(d.date)
        d = d[k < len(cal)]
        d["date"] = cal[k[k < len(cal)]]
        out.append(d[d.date >= pd.Timestamp(cfg.start)])
    return pd.concat(out).sort_values(["date", "market"]).drop_duplicates(["market", "date", "event"]).reset_index(drop=True)


def _macro_series(cfg: SimConfig, rng, mcal: pd.DataFrame) -> pd.DataFrame:
    """Daily levels of the dollar index, USDCNY and 10y bond futures (calendar days)."""
    days = pd.date_range(cfg.start, cfg.end, freq="D")
    n = len(days)
    wk = (days.dayofweek < 5).astype(float)
    on_us = days.isin(pd.DatetimeIndex(mcal[mcal.market == "US"].date))
    on_cn = days.isin(pd.DatetimeIndex(mcal[mcal.market == "CN"].date))
    r = {"DXY": rng.standard_normal(n) * 0.004 * wk * np.where(on_us, 2.0, 1.0),
         "USDCNY": rng.standard_normal(n) * 0.0018 * wk * np.where(on_cn, 1.5, 1.0),
         "US_10Y_FUT": rng.standard_normal(n) * 0.0035 * wk * np.where(on_us, 2.5, 1.0),
         "CN_10Y_FUT": rng.standard_normal(n) * 0.0012 * wk * np.where(on_cn, 2.0, 1.0)}
    for d, moves in {"2024-08-05": {"DXY": -0.012, "USDCNY": -0.006, "US_10Y_FUT": 0.009},
                     "2025-04-07": {"DXY": -0.008, "USDCNY": 0.005, "US_10Y_FUT": -0.008, "CN_10Y_FUT": 0.003}}.items():
        k = days.get_loc(pd.Timestamp(d))
        for kk, v in moves.items():
            r[kk][k] = v
    x = np.log(7.10) + np.cumsum(r["USDCNY"])
    for t in range(1, n):                        # managed currency: mean reversion to the fix
        x[t] = x[t - 1] + 0.003 * (np.log(7.15) - x[t - 1]) + r["USDCNY"][t]
    return pd.DataFrame({"DXY": 102.0 * np.exp(np.cumsum(r["DXY"])), "USDCNY": np.exp(x),
                         "US_10Y_FUT": 110.0 * np.exp(np.cumsum(r["US_10Y_FUT"])),
                         "CN_10Y_FUT": 102.0 * np.exp(np.cumsum(r["CN_10Y_FUT"]))}, index=days)


def _fx_and_rates(cfg, macro: pd.DataFrame):
    days = macro.index
    fx = pd.concat([pd.DataFrame({"date": days, "pair": "USDCNY", "rate": np.round(macro.USDCNY.values, 5)}),
                    pd.DataFrame({"date": days, "pair": "DXY", "rate": np.round(macro.DXY.values, 4)})])
    usd = np.interp(np.arange(len(days)), [0, 250, 360, 700, len(days) - 1], [5.33, 5.33, 4.33, 4.08, 3.60])
    cny = np.interp(np.arange(len(days)), [0, len(days) - 1], [1.80, 1.35])
    rates = pd.concat([pd.DataFrame({"date": days, "currency": "USD", "rate_pct": np.round(usd, 3)}),
                       pd.DataFrame({"date": days, "currency": "CNY", "rate_pct": np.round(cny, 3)})])
    return fx, rates


def _equity_score_fns(sim: EquitySim, rng):
    Z = sim.Z
    rel = {
        "A1": pd.Timestamp("2025-09-15"), "C1": pd.Timestamp("2026-01-12"),
        "D1": pd.Timestamp("2025-06-02"), "A2": pd.Timestamp("2025-05-12"),
    }
    d = sim.dates

    def a1(t, ok):
        rev_w = 1.0 if d[t] >= rel["A1"] else 0.8
        return (rev_w * Z["st_reversal"][t] + 0.45 * Z["theme"][t] - 0.2 * Z["liquidity"][t]
                + 0.25 * Z["volatility"][t] + 0.9 * rng.standard_normal(sim.N))

    def a2(t, ok):
        lim = sim.limit_flag[t - 1]
        size_w = 0.3 if d[t] >= rel["A2"] else 0.0
        return (0.8 * Z["st_reversal"][t] + 0.5 * lim - size_w * Z["size"][t]
                + 0.9 * rng.standard_normal(sim.N))

    def c1(t, ok):
        lo = max(0, t - 3)
        recent = sim.earn[lo:t].any(0)
        react = np.where(sim.earn[lo:t], sim.r[lo:t], 0).sum(0)
        beta_w = -0.2 if d[t] >= rel["C1"] else -0.7
        sc = 1.0 * _z(react, recent) + beta_w * _z(sim.beta_true + rng.normal(0, 0.1, sim.N)) \
            + 0.5 * rng.standard_normal(sim.N)
        return np.where(recent, sc, np.nan)

    def d1(t, ok):
        vol_w = 0.7 if d[t] >= rel["D1"] else 0.0
        return (-0.7 * Z["crowding"][t] + 0.45 * Z["theme"][t] + vol_w * Z["volatility"][t]
                + 0.25 * Z["st_reversal"][t] + 0.9 * rng.standard_normal(sim.N))

    return a1, a2, c1, d1


def generate(cfg: SimConfig | None = None, verbose: bool = True) -> Path:
    cfg = cfg or SimConfig()
    rng = np.random.default_rng(cfg.seed)
    out = Path(cfg.out_dir)
    for sub in ["reference", "market", "fundamentals", "alt", "crypto", "macro", "trading", "truth"]:
        (out / sub).mkdir(parents=True, exist_ok=True)
    log = print if verbose else (lambda *a, **k: None)

    log("[gen] crypto ...")
    cs = CryptoSim(cfg, rng, cfg.n_crypto)
    mcal = macro_calendar(cfg)
    macro = _macro_series(cfg, rng, mcal)
    log("[gen] US equities ...")
    us = EquitySim(US, cfg, rng, cfg.n_us, cs.btc_log_returns, None, macro, mcal)
    log("[gen] CN equities ...")
    cn = EquitySim(CN, cfg, rng, cfg.n_cn, cs.btc_log_returns, us.fut_lr, macro, mcal)
    fx, rates = _fx_and_rates(cfg, macro)
    fx_series = fx[fx.pair == "USDCNY"].set_index("date")["rate"]

    # ---------------- reference & market data ----------------------------- #
    ref_rows, ca_rows, px_frames, earn_frames, fund_rows, si_rows, fee_frames = [], [], [], [], [], [], []
    etf_rows, retail_rows, hf_rows, mkt_rows, depth_rows, fut_rows = [], [], [], [], [], []
    theme_names = {1.0: "AI infrastructure"}
    for sim in (us, cn):
        spec = sim.spec
        for i in range(sim.N):
            ref_rows.append({
                "ticker": sim.tickers[i], "market": spec.code, "country": spec.country,
                "currency": spec.currency, "sector": spec.sectors[sim.sector[i]],
                "list_date": sim.dates[sim.list_idx[i]].date() if sim.list_idx[i] > 0 else pd.Timestamp("2015-01-02").date(),
                "delist_date": sim.dates[sim.delist_idx[i]].date() if sim.delist_idx[i] < sim.T else None,
                "shares_outstanding": int(sim.shares0[i]), "lot_size": spec.lot_size,
                "shortable": bool(sim.shortable[i]), "index_member_at_start": bool(sim.member0[i]),
                "theme_tag": theme_names.get(sim.theme[i], ""),
            })
        tt, ii = np.where(sim.split != 1)
        for t, i in zip(tt, ii):
            ca_rows.append({"ticker": sim.tickers[i], "ex_date": sim.dates[t].date(), "action": "SPLIT",
                            "ratio": sim.split[t, i], "amount": None, "currency": spec.currency})
        tt, ii = np.where(sim.div > 0)
        for t, i in zip(tt, ii):
            ca_rows.append({"ticker": sim.tickers[i], "ex_date": sim.dates[t].date(), "action": "CASH_DIVIDEND",
                            "ratio": None, "amount": sim.div[t, i], "currency": spec.currency})
        tt, ii = np.where(sim.alive)
        px_frames.append(pd.DataFrame({
            "date": sim.dates[tt], "ticker": sim.tickers[ii],
            "open": np.round(sim.open[tt, ii], 2), "high": np.round(sim.high[tt, ii], 2),
            "low": np.round(sim.low[tt, ii], 2), "close": np.round(sim.close[tt, ii], 2),
            "vwap": np.round(sim.vwap[tt, ii], 3), "volume": sim.volume[tt, ii].astype(np.int64),
            "spread_bps": np.round(sim.spread[tt, ii], 2), "halted": sim.halted[tt, ii].astype(int),
        }).assign(market=spec.code))
        for (tk, dt, fpe, i, k) in sim.earn_rows:
            earn_frames.append({"ticker": tk, "market": spec.code, "event_date": dt.date(),
                                "timing": "BMO", "fiscal_period_end": fpe.date()})
            mc = np.exp(sim.logmcap[k, i])
            book = sim.book[k, i]
            ni = book * sim.roe[i] * (1 + rng.normal(0, 0.25))
            fund_rows.append({"ticker": tk, "currency": spec.currency, "fiscal_period_end": fpe.date(),
                              "report_date": dt.date(), "book_equity": round(book, 0),
                              "net_income_q": round(ni, 0), "revenue_q": round(abs(ni) / max(sim.margin[i], 0.03), 0),
                              "total_assets": round(book * np.exp(rng.normal(np.log(2.5), 0.4)), 0)})
        # short interest: US semi-monthly with 8 business-day lag; CN daily T+1
        if spec.code == "US":
            settle = sorted({sim.dates[_snap(sim.dates, pd.Timestamp(d.year, d.month, 15), "left")] for d in sim.dates}
                            | {sim.dates[_snap(sim.dates, d + pd.offsets.MonthEnd(0), "left")] for d in sim.dates})
            for d in settle:
                k = sim.dates.get_loc(d)
                pub = sim.dates[min(k + 8, sim.T - 1)]
                for i in np.where(sim.alive[k])[0]:
                    si_rows.append((sim.tickers[i], d.date(), pub.date(), int(sim.si[k, i] * sim.shares[k, i])))
        else:
            for k in range(0, sim.T, 1):
                pub = sim.dates[min(k + 1, sim.T - 1)]
                for i in np.where(sim.alive[k] & sim.shortable)[0]:
                    si_rows.append((sim.tickers[i], sim.dates[k].date(), pub.date(), int(sim.si[k, i] * sim.shares[k, i])))
        tt, ii = np.where(sim.alive & sim.shortable[None, :])
        lend = sim.lendable[ii] * sim.shares[tt, ii]
        on_loan = sim.si[tt, ii] * sim.shares[tt, ii]
        fee_frames.append(pd.DataFrame({"date": sim.dates[tt], "ticker": sim.tickers[ii],
                                        "fee_bps": np.round(sim.fee[tt, ii], 1),
                                        "available_shares": np.round(np.maximum(lend - on_loan, 0), 0).astype(np.int64),
                                        "utilization_pct": np.round(np.clip(100 * on_loan / np.maximum(lend, 1), 0, 100), 1)}))
        # ETF ownership (month-end snapshots, published 5 business days later)
        me = sorted({sim.dates[_snap(sim.dates, d + pd.offsets.MonthEnd(0), "left")] for d in sim.dates})
        for d in me:
            k = sim.dates.get_loc(d)
            ii = np.where(sim.alive[k])[0]
            etf_rows.append(pd.DataFrame({"as_of_date": d.date(), "publication_date": sim.dates[min(k + 5, sim.T - 1)].date(),
                                          "ticker": sim.tickers[ii],
                                          "etf_shares_held": np.round(sim.etf[k, ii] * sim.shares[k, ii]).astype(np.int64)}))
        # retail flow: US sub-penny-identified retail share; CN small-trade share (daily)
        tt, ii = np.where(sim.alive & ~sim.halted)
        retail_rows.append(pd.DataFrame({"date": sim.dates[tt], "ticker": sim.tickers[ii],
                                         "retail_share": np.round(sim.retail[tt, ii], 4),
                                         "method": "subpenny_price_improvement" if spec.code == "US" else "small_trade_share"}))
        # 13F hedge fund ownership (US only; quarterly, 45-day filing lag) - background monitor
        if spec.code == "US":
            for y in sorted(set(sim.dates.year)):
                for qm in (3, 6, 9, 12):
                    qe = pd.Timestamp(y, qm, 1) + pd.offsets.MonthEnd(0)
                    k = _snap(sim.dates, qe, "left")
                    if k is None or qe > sim.dates[-1]:
                        continue
                    ii = np.where(sim.alive[k])[0]
                    hf_rows.append(pd.DataFrame({"quarter_end": qe.date(), "filing_date": (qe + pd.Timedelta(days=45)).date(),
                                                 "ticker": sim.tickers[ii],
                                                 "hf_shares_held": np.round(np.clip(sim.hf_own[ii] + rng.normal(0, 0.01, len(ii)), 0, 0.6)
                                                                            * sim.shares[k, ii]).astype(np.int64)}))
        # market-wide series: implied vol index, depth, index futures
        mkt_rows.append(pd.DataFrame({"date": sim.dates, "index": spec.vol_index, "close": np.round(sim.vol_index, 3)}))
        depth_rows.append(pd.DataFrame({"date": sim.dates, "market": spec.code,
                                        "top5_depth_local": np.round(sim.depth, -3)}))
        fut_rows.append(pd.DataFrame({"date": sim.dates, "contract": spec.index_future, "market": spec.code,
                                      "open": np.round(sim.fut_open, 2), "close": np.round(sim.fut_close, 2)}))

    pd.DataFrame(ref_rows).to_csv(out / "reference/securities.csv", index=False)
    pd.DataFrame(ca_rows).sort_values(["ex_date", "ticker"]).to_csv(out / "reference/corporate_actions.csv", index=False)
    pd.DataFrame(earn_frames).sort_values(["event_date", "ticker"]).to_csv(out / "reference/earnings_calendar.csv", index=False)
    idx_rows = [(d.date(), tk, ch, "US" if sim is us else "CN") for sim in (us, cn) for (d, tk, ch) in sim.index_rows]
    pd.DataFrame(idx_rows, columns=["effective_date", "ticker", "change", "market"]).to_csv(
        out / "reference/index_changes.csv", index=False)
    cal_rows = []
    for sim in (us, cn):
        expiries = {sim.dates[_snap(sim.dates, _nth_weekday(d.year, d.month), "left")] for d in sim.dates}
        rebal = {sim.dates[k] for k in sim.rebal_idx}
        for d in sim.dates:
            cal_rows.append({"market": sim.spec.code, "date": d.date(), "is_option_expiry": d in expiries,
                             "is_index_rebalance": d in rebal})
    pd.DataFrame(cal_rows).to_csv(out / "reference/market_calendar.csv", index=False)
    for f in px_frames:
        mkt = f.market.iloc[0]
        f.drop(columns="market").to_csv(out / f"market/prices_daily_{mkt}.csv.gz", index=False)
    pd.DataFrame(fund_rows).sort_values(["report_date", "ticker"]).to_csv(out / "fundamentals/fundamentals_quarterly.csv", index=False)
    pd.DataFrame(si_rows, columns=["ticker", "settlement_date", "publication_date", "short_interest_shares"]).to_csv(
        out / "alt/short_interest.csv.gz", index=False)
    pd.concat(fee_frames).to_csv(out / "alt/borrow_fees.csv.gz", index=False)
    fx.to_csv(out / "macro/fx_rates.csv", index=False)
    rates.to_csv(out / "macro/short_rates.csv", index=False)
    wk = macro.index[macro.index.dayofweek < 5]
    pd.concat([pd.DataFrame({"date": wk, "contract": c, "close": np.round(macro.loc[wk, c].values, 4)})
               for c in ("US_10Y_FUT", "CN_10Y_FUT")]).to_csv(out / "macro/rates_futures.csv", index=False)
    pd.concat(mkt_rows).to_csv(out / "macro/vol_index.csv", index=False)
    pd.concat(depth_rows).to_csv(out / "macro/market_depth.csv", index=False)
    pd.concat(fut_rows).to_csv(out / "market/index_futures_daily.csv", index=False)
    mcal.assign(date=mcal.date.dt.date).to_csv(out / "reference/macro_calendar.csv", index=False)
    pd.concat(etf_rows).to_csv(out / "alt/etf_ownership.csv.gz", index=False)
    pd.concat(retail_rows).to_csv(out / "alt/retail_flow.csv.gz", index=False)
    pd.concat(hf_rows).to_csv(out / "alt/hf_ownership_13f.csv", index=False)

    # 30-minute bars for the US, last N trading days
    k0 = us.T - cfg.intraday_days
    B = US.n_bars
    bars, fbars = [], []
    for t in range(k0, us.T):
        ii = np.where(us.alive[t])[0]
        p = us.path[t][ii]
        o, c = p[:, :-1], p[:, 1:]
        noise = np.abs(rng.normal(0, 0.0008, o.shape))
        hi = np.maximum(o, c) * (1 + noise); lo = np.minimum(o, c) * (1 - noise)
        vw = us.bar_W[t] * np.exp(rng.normal(0, 0.2, o.shape))
        vol = np.round(us.volume[t, ii, None] * vw / vw.sum(1, keepdims=True))
        idio_sd = us.spec_vol[ii, None] * 0.8 * np.sqrt(us.bar_w[None, :])
        ofi = np.tanh(0.8 * us.idio_lr[t, ii] / idio_sd + 0.4 * rng.standard_normal(o.shape))
        buy = np.round(vol * (1 + ofi) / 2)
        ends = _minute_to_clock(US.sessions, np.arange(1, B + 1) * US.bar_minutes)
        ts = us.dates[t] + pd.to_timedelta(ends, unit="s")
        bars.append(pd.DataFrame({
            "bar_end": np.tile(ts, len(ii)), "ticker": np.repeat(us.tickers[ii], B),
            "open": np.round(o.ravel(), 3), "high": np.round(hi.ravel(), 3), "low": np.round(lo.ravel(), 3),
            "close": np.round(c.ravel(), 3), "volume": vol.ravel().astype(np.int64),
            "buy_volume": buy.ravel().astype(np.int64), "sell_volume": (vol - buy).ravel().astype(np.int64),
            "vwap": np.round(((o + hi + lo + c) / 4).ravel(), 3)}))
        fp = us.fut_path[t]
        fbars.append(pd.DataFrame({"bar_end": ts, "contract": US.index_future, "open": np.round(fp[:-1], 2),
                                   "close": np.round(fp[1:], 2)}))
    pd.concat(bars).to_csv(out / "market/bars_30m_US.csv.gz", index=False)
    pd.concat(fbars).to_csv(out / "market/index_futures_bars_30m_US.csv", index=False)

    # crypto
    T, N = cs.T, cs.N
    rows = []
    venue_mult = {}
    for v in CRYPTO_VENUES:
        dis = np.ones((T, N))
        if v == VENUE_INCIDENT["venue"]:
            k = cs.dates.searchsorted(pd.Timestamp(VENUE_INCIDENT["date"]))
            dis[k] = 1 + VENUE_INCIDENT["dislocation"]
        noise = 1 + rng.normal(0, 0.0003, (T, N)) * (v != "VENUE_A")
        venue_mult[v] = noise * dis
        share = 0.6 if v == "VENUE_A" else 0.4
        tt, ii = np.meshgrid(np.arange(T), np.arange(N), indexing="ij")
        rows.append(pd.DataFrame({
            "date": cs.dates[tt.ravel()], "symbol": cs.symbols[ii.ravel()], "venue": v,
            "spot_close": (cs.spot * noise * dis).ravel(), "perp_close": (cs.perp * noise * dis).ravel(),
            "funding_rate_daily": np.round(cs.funding.ravel(), 6),
            "open_interest_usd": np.round((np.exp(cs.logmcap) * 0.015 * share).ravel(), 0),
            "volume_usd": np.round((cs.vol_usd * share).ravel(), 0)}))
    pd.concat(rows).to_csv(out / "crypto/crypto_daily.csv.gz", index=False, float_format="%.8g")
    pd.DataFrame({"symbol": cs.symbols, "sector": cs.sector_names, "primary_venue": cs.venue}).to_csv(
        out / "crypto/crypto_reference.csv", index=False)
    tt, ii = np.where(cs.unlock)
    pd.DataFrame({"symbol": cs.symbols[ii], "unlock_date": cs.dates[tt].date,
                  "pct_circulating_supply": np.round(rng.uniform(0.5, 6.0, len(tt)), 2)}).sort_values(
        "unlock_date").to_csv(out / "crypto/token_unlocks.csv", index=False)

    # ---------------- strategies --------------------------------------- #
    log("[gen] strategies, fills and books ...")
    g = cfg.gmv_scale
    strategies = [
        StrategyDef("A1_US_STATARB", "US", 60e6 * g, 90, 0.5, 0.10,
                    "ML stat-arb on US equities (gradient boosted trees on price/volume features)", "1-2 days"),
        StrategyDef("A2_CN_STATARB", "CN", 25e6 * g, 40, 0.5, 0.14,
                    "ML stat-arb on China A-shares via Stock Connect", "1-2 days"),
        StrategyDef("B1_US_INTRADAY", "US", 40e6 * g, 35, 0.0, 0.29,
                    "Intraday ML on opening auction imbalance / gap dynamics", "hours"),
        StrategyDef("C1_US_EVENT", "US", 30e6 * g, 25, 0.6, 0.33,
                    "Post-earnings announcement drift with NLP on transcripts", "3-5 days"),
        StrategyDef("D1_US_CROWDING", "US", 50e6 * g, 70, 0.8, 0.13,
                    "Positioning / crowding model (short interest, borrow, flows)", "3-7 days"),
        StrategyDef("E1_CRYPTO_CARRY", "CRYPTO", 20e6 * g, 8, 0.6, 0.17,
                    "Perpetual-futures funding carry with momentum overlay", "2-4 days"),
    ]
    start = pd.Timestamp(cfg.trading_start)
    pos_rows, fill_frames, fin_rows, pnl_rows = [], [], [], []
    rate_usd = rates[rates.currency == "USD"].set_index("date")["rate_pct"] / 100
    a1, a2, c1, d1 = _equity_score_fns(us, rng)
    a2 = _equity_score_fns(cn, rng)[1]

    for sim, defs in ((us, [s for s in strategies if s.market == "US"]),
                      (cn, [s for s in strategies if s.market == "CN"])):
        fxl = np.ones(sim.T) if sim.spec.code == "US" else fx_series.reindex(sim.dates).values
        ss = StrategySimulator(sim, fxl, start, rng)
        books = {}
        for sd in defs:
            if sd.name == "B1_US_INTRADAY":
                books[sd.name], _ = ss.run_intraday(
                    sd, lambda t: 0.9 if sim.dates[t] >= pd.Timestamp("2025-03-03") else 0.7)
            else:
                fn = {"A1_US_STATARB": a1, "A2_CN_STATARB": a2, "C1_US_EVENT": c1, "D1_US_CROWDING": d1}[sd.name]
                books[sd.name] = ss.run_daily(sd, fn)
        fills = ss.fills()
        fill_frames.append(fills)
        rate_loc = rate_usd if sim.spec.code == "US" else rates[rates.currency == "CNY"].set_index("date")["rate_pct"] / 100
        for sd in defs:
            sh = books[sd.name]
            tt, ii = np.where(sh != 0)
            pos_rows.append(pd.DataFrame({"date": sim.dates[tt], "strategy": sd.name, "ticker": sim.tickers[ii],
                                          "venue": "", "quantity": sh[tt, ii]}))
            f = fills[fills.strategy == sd.name]
            trade_local = np.zeros(sim.T); cost_local = np.zeros(sim.T)
            np.add.at(trade_local, f._t.values, f.quantity.values * (sim.close[f._t.values, f._i.values] - f.price.values))
            np.add.at(cost_local, f._t.values, -(f.commission.values + f.fees.values))
            # booking break: one late-booked fill per strategy
            big = f.loc[(f.quantity * f.price).abs().idxmax()] if len(f) else None
            for t in range(ss.t0, sim.T):
                prev = sh[t - 1]
                mv_prev = prev * sim.close[t - 1]
                hold_usd = ((prev * (sim.split[t] * sim.close[t] + sim.div[t])).sum() / fxl[t] - mv_prev.sum() / fxl[t - 1])
                dc = (sim.dates[t] - sim.dates[t - 1]).days
                rf = rate_loc.asof(sim.dates[t])
                long_mv = mv_prev[mv_prev > 0].sum(); short_mv = -mv_prev[mv_prev < 0].sum()
                if sim.spec.code == "US":
                    financing = (-long_mv * (rf + 0.004) + short_mv * max(rf - 0.0025, 0)) * dc / 360
                else:
                    financing = -long_mv * (rf + 0.006) * dc / 360
                fee_bps = np.nan_to_num(sim.fee[t - 1])
                borrow = -(np.where(mv_prev < 0, -mv_prev, 0) * fee_bps / 1e4).sum() * dc / 360
                financing /= fxl[t]; borrow /= fxl[t]
                trade_usd = trade_local[t] / fxl[t]; cost_usd = cost_local[t] / fxl[t]
                true_pnl = hold_usd + trade_usd + cost_usd + financing + borrow
                official = true_pnl + rng.normal(0, 25)
                if big is not None and t == big._t:
                    official -= big.quantity * (sim.close[t, big._i] - big.price) / fxl[t]
                gmv = np.abs(sh[t] * sim.close[t]).sum() / fxl[t]
                nmv = (sh[t] * sim.close[t]).sum() / fxl[t]
                fin_rows.append({"date": sim.dates[t].date(), "strategy": sd.name,
                                 "financing_usd": round(financing, 2), "borrow_usd": round(borrow, 2),
                                 "funding_usd": 0.0})
                pnl_rows.append({"date": sim.dates[t].date(), "strategy": sd.name, "team": TEAMS[sd.name],
                                 "pnl_usd": round(official, 2), "gmv_usd": round(gmv, 0), "nmv_usd": round(nmv, 0)})

    # crypto strategy (calendar days, perps)
    sd = strategies[-1]
    T, N = cs.T, cs.N
    t0 = int(cs.dates.searchsorted(start))
    qty_pos = np.zeros((T, N)); w_prev = np.zeros(N)
    corders = []
    for t in range(t0, T):
        ok = np.ones(N, bool)
        mom = cs.r[max(0, t - 7):t].sum(0)
        rel = cs.dates[t] >= pd.Timestamp("2025-12-01")
        z = -0.8 * _cs_z(cs.funding[t - 1], ok) + (0.6 if rel else 0.4) * _cs_z(mom, ok) \
            + 0.8 * rng.standard_normal(N)
        if t + 1 < T:
            z += sd.alpha * _cs_z(cs.u[t + 1], ok)
        tgt = _long_short(z, ok, ok, sd.n_side)
        w = (1 - sd.persistence) * tgt + sd.persistence * w_prev
        gsum = np.abs(w).sum()
        w = w / gsum if gsum > 0 else w
        p_dec = cs.perp[t - 1]
        q = np.round(w * sd.gmv_usd / p_dec, 3)
        qty_pos[t] = q; w_prev = w
        dq = q - qty_pos[t - 1]
        for i in np.where(np.abs(dq) > 0)[0]:
            corders.append((t, i, dq[i], p_dec[i]))
    co = pd.DataFrame(corders, columns=["t", "i", "qty", "dec"])
    hr = rng.uniform(0.2, 23.8, len(co))
    b = np.floor(hr).astype(int); fr = hr - b
    mid = cs.path[co.t, co.i, b] + fr * (cs.path[co.t, co.i, b + 1] - cs.path[co.t, co.i, b])
    arrival = cs.path[co.t, co.i, np.maximum(b - 0, 0)]
    part = np.abs(co.qty * mid) / cs.adv[co.t, co.i]
    side = np.sign(co.qty)
    px = mid * (1 + side * (0.0002 + 0.3 * cs.sigma_d[co.t, co.i] * np.sqrt(part)))
    venue = cs.venue[co.i]
    dis = np.ones(len(co))
    kinc = cs.dates.searchsorted(pd.Timestamp(VENUE_INCIDENT["date"]))
    dis[(co.t == kinc) & (venue == VENUE_INCIDENT["venue"])] = 1 + VENUE_INCIDENT["dislocation"]
    px = px * dis
    notional = np.abs(co.qty * px)
    cfills = pd.DataFrame({
        "date": cs.dates[co.t], "timestamp": cs.dates[co.t] + pd.to_timedelta(hr * 3600, unit="s").round("s"),
        "strategy": sd.name, "ticker": cs.symbols[co.i], "venue": venue,
        "side": np.where(side > 0, "BUY", "SELL"), "quantity": co.qty.values, "price": px.values,
        "decision_price": co.dec.values, "decision_time": cs.dates[co.t],
        "arrival_price": arrival * dis, "commission": np.round(notional * 4e-4, 2), "fees": 0.0,
        "currency": "USD", "tz": "UTC", "_t": co.t.values, "_i": co.i.values})
    fill_frames.append(cfills)
    tt, ii = np.where(qty_pos != 0)
    pos_rows.append(pd.DataFrame({"date": cs.dates[tt], "strategy": sd.name, "ticker": cs.symbols[ii],
                                  "venue": cs.venue[ii], "quantity": qty_pos[tt, ii]}))
    # crypto books (marks at venue perp incl. venue dislocation)
    # books mark each token at its primary venue's published perp price
    mark = cs.perp * np.where(cs.venue[None, :] == "VENUE_A", venue_mult["VENUE_A"], venue_mult["VENUE_B"])
    trade = np.zeros(T); cost = np.zeros(T)
    np.add.at(trade, cfills._t.values, cfills.quantity.values * (mark[cfills._t.values, cfills._i.values] - cfills.price.values))
    np.add.at(cost, cfills._t.values, -cfills.commission.values)
    for t in range(t0, T):
        prev = qty_pos[t - 1]
        hold = (prev * (mark[t] - mark[t - 1])).sum()
        funding = -(prev * mark[t - 1] * cs.funding[t]).sum()
        official = hold + trade[t] + cost[t] + funding + rng.normal(0, 15)
        fin_rows.append({"date": cs.dates[t].date(), "strategy": sd.name, "financing_usd": 0.0,
                         "borrow_usd": 0.0, "funding_usd": round(funding, 2)})
        pnl_rows.append({"date": cs.dates[t].date(), "strategy": sd.name, "team": TEAMS[sd.name],
                         "pnl_usd": round(official, 2), "gmv_usd": round(np.abs(qty_pos[t] * mark[t]).sum(), 0),
                         "nmv_usd": round((qty_pos[t] * mark[t]).sum(), 0)})

    fills = pd.concat(fill_frames, ignore_index=True).drop(columns=["_t", "_i"])
    fills = fills.sort_values(["date", "timestamp", "strategy"]).reset_index(drop=True)
    fills.insert(0, "fill_id", [f"F{n:08d}" for n in range(len(fills))])
    fills.to_csv(out / "trading/fills.csv.gz", index=False, float_format="%.6f")
    pd.concat(pos_rows).sort_values(["date", "strategy", "ticker"]).to_csv(
        out / "trading/positions_eod.csv.gz", index=False, float_format="%.6f")
    pd.DataFrame(fin_rows).to_csv(out / "trading/financing.csv", index=False)
    pd.DataFrame(pnl_rows).to_csv(out / "trading/official_pnl.csv", index=False)
    pd.DataFrame([{"strategy": s.name, "team": TEAMS[s.name], "market": s.market,
                   "asset_class": "crypto" if s.market == "CRYPTO" else "equity",
                   "description": s.description, "target_gmv_usd": s.gmv_usd, "holding_period": s.holding}
                  for s in strategies]).to_csv(out / "trading/strategies.csv", index=False)
    pd.DataFrame([
        ("B1_US_INTRADAY", "2025-03-03", "v5.1", "Retrained gap model; stronger opening-gap fade"),
        ("A2_CN_STATARB", "2025-05-12", "v2.3", "Added small-cap feature set"),
        ("D1_US_CROWDING", "2025-06-02", "v2.0", "New feature family (realised-vol features)"),
        ("A1_US_STATARB", "2025-09-15", "v3.2", "Retrain on extended window; more weight on short-horizon features"),
        ("E1_CRYPTO_CARRY", "2025-12-01", "v1.6", "Momentum overlay re-weighted"),
        ("C1_US_EVENT", "2026-01-12", "v1.4", "Beta-neutralisation constraint added after risk review"),
    ], columns=["strategy", "release_date", "version", "notes"]).to_csv(out / "trading/model_releases.csv", index=False)

    # ---------------- truth (for model validation only) ----------------- #
    for sim in (us, cn):
        (sim.F_on + sim.F_id).to_csv(out / f"truth/factor_returns_{sim.spec.code}.csv")
        sim.shocks.to_csv(out / f"truth/ts_shocks_{sim.spec.code}.csv")
        pd.DataFrame({**{k: v for k, v in sim.ts_load.items()}, "lam_intraday": sim.lam,
                      "beta": sim.beta_true}, index=sim.tickers).to_csv(out / f"truth/ts_loadings_{sim.spec.code}.csv")
        pd.DataFrame({"date": sim.dates, "regime": sim.regime}).to_csv(out / f"truth/regime_{sim.spec.code}.csv", index=False)
    cs.F.to_csv(out / "truth/factor_returns_CRYPTO.csv")
    stress = [(n, m, d.date()) for sim in (us, cn) for (n, m, d) in sim.stress_rows]
    stress += [(e["name"], "CRYPTO", pd.Timestamp(e["date"]).date()) for e in STRESS_EPISODES if "CRYPTO" in e]
    pd.DataFrame(stress, columns=["episode", "market", "date"]).to_csv(out / "truth/stress_episodes.csv", index=False)
    log(f"[gen] done -> {out}")
    return out


if __name__ == "__main__":
    generate()
