"""Central configuration for the short-horizon factor risk framework.

Everything that a risk manager might want to change without touching code lives
here: market definitions, factor taxonomy, estimation half-lives, limits and
stress scenarios.  Factor *definitions* are deliberately shared across markets
(common taxonomy), while estimation is local (Section 2.4 of the case).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Markets
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MarketSpec:
    code: str
    country: str
    currency: str
    fx_pair: str | None                 # quote convention: local units per 1 USD
    sectors: tuple[str, ...]
    sessions: tuple[tuple[str, str], ...]  # local-time trading sessions
    bar_minutes: int
    lot_size: int
    price_limit: float | None           # daily limit as fraction of prev close
    commission_bps: float
    sell_tax_bps: float                 # stamp duty / SEC fee on sells
    holidays: tuple[str, ...]
    extra_factors: tuple[str, ...] = ()  # market-specific factors
    ts_factors: tuple[str, ...] = ()     # time-series shock factors (Section 2.2)
    tick_size: float = 0.01
    index_future: str = ""
    vol_index: str = ""
    fx_series: str = ""                  # currency series stocks are sensitive to
    rates_future: str = ""
    short_side_crowding: bool = True     # False where short selling is restricted

    @property
    def session_minutes(self) -> int:
        total = 0
        for start, end in self.sessions:
            h0, m0 = map(int, start.split(":"))
            h1, m1 = map(int, end.split(":"))
            total += (h1 * 60 + m1) - (h0 * 60 + m0)
        return total

    @property
    def n_bars(self) -> int:
        return self.session_minutes // self.bar_minutes


US_HOLIDAYS = (
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19",
    "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07",
)


def _span(start: str, end: str) -> tuple[str, ...]:
    import pandas as pd
    return tuple(d.strftime("%Y-%m-%d") for d in pd.date_range(start, end))


CN_HOLIDAYS = (
    ("2024-01-01",) + _span("2024-02-09", "2024-02-16") + _span("2024-04-04", "2024-04-05")
    + _span("2024-05-01", "2024-05-03") + ("2024-06-10",) + ("2024-09-16", "2024-09-17")
    + _span("2024-10-01", "2024-10-07")
    + ("2025-01-01",) + _span("2025-01-28", "2025-02-04") + ("2025-04-04",)
    + _span("2025-05-01", "2025-05-05") + ("2025-06-02",) + _span("2025-10-01", "2025-10-08")
    + ("2026-01-01", "2026-01-02") + _span("2026-02-16", "2026-02-23") + ("2026-04-06",)
    + _span("2026-05-01", "2026-05-05") + ("2026-06-19",)
)

US = MarketSpec(
    code="US", country="United States", currency="USD", fx_pair=None,
    sectors=("Technology", "Semiconductors", "Communication", "Consumer Discretionary",
             "Consumer Staples", "Health Care", "Financials", "Industrials", "Energy",
             "Materials", "Utilities"),
    sessions=(("09:30", "16:00"),), bar_minutes=30, lot_size=1, price_limit=None,
    commission_bps=0.5, sell_tax_bps=0.278, holidays=US_HOLIDAYS,
    extra_factors=("crypto_beta",),
    ts_factors=("vol_shock", "liq_shock", "fx", "rates"),
    index_future="US_IDX_FUT", vol_index="US_VIX", fx_series="DXY", rates_future="US_10Y_FUT",
)

CN = MarketSpec(
    code="CN", country="China (A-shares via Connect)", currency="CNY", fx_pair="USDCNY",
    sectors=("Banks", "Non-bank Financials", "Electronics", "Computers", "Pharma",
             "Food & Beverage", "Machinery", "Autos", "Chemicals", "Real Estate"),
    sessions=(("09:30", "11:30"), ("13:00", "15:00")), bar_minutes=30, lot_size=100,
    price_limit=0.10, commission_bps=1.5, sell_tax_bps=5.0, holidays=CN_HOLIDAYS,
    extra_factors=("limit_hit",),
    ts_factors=("vol_shock", "liq_shock", "fx", "rates", "us_session"),
    index_future="CN_IDX_FUT", vol_index="CN_VIX", fx_series="USDCNY", rates_future="CN_10Y_FUT",
)

MARKETS: dict[str, MarketSpec] = {"US": US, "CN": CN}

CRYPTO_SECTORS = ("Store of Value", "Smart Contract L1", "DeFi", "Exchange Token",
                  "Infrastructure", "Meme")
CRYPTO_VENUES = ("VENUE_A", "VENUE_B")


# --------------------------------------------------------------------------- #
# Factor taxonomy (common across markets)
# --------------------------------------------------------------------------- #
MARKET_FACTOR = "market"
STYLE_FACTORS = (
    "beta", "size", "liquidity", "volatility",
    "st_reversal", "st_momentum", "overnight_gap", "crowding",
)
# Events and calendar (Section 2.2).  Market-wide calendar events (macro
# announcements) cannot be cross-sectional factors - they scale factor risk instead.
EVENT_FACTORS = ("earnings", "index_rebalance", "option_expiry", "corporate_action", "in_play")
SPECIFIC_RISK_EVENTS = ("earnings", "in_play_any")  # extra specific risk on these days; in_play_any is
                                                     # in_play before limit hits are removed from it (CN)
MACRO_SENSITIVE = ("market", "rates", "fx", "vol_shock")   # factor risk scaled on macro days

# Time-series shock factors: exposures are estimated sensitivities B to observed
# shock series g, r = X f + B g + u (Section 3.1).  Which apply where is set by
# MarketSpec.ts_factors.
TS_FACTOR_DESCRIPTIONS = {
    "vol_shock": "change in log implied volatility index",
    "liq_shock": "market liquidity shock: change in log aggregate spread minus change in log depth",
    "fx": "local currency return (US: dollar index; CN: USDCNY)",
    "rates": "10-year government bond futures return",
    "us_session": "previous US session index-futures return (Asian markets)",
}

# Medium-priority factors: tested for promotion to the core, otherwise monitored
CANDIDATE_FACTORS = ("etf_ownership", "retail_attention")
# Governance decision; empty = monitor only.  A promoted candidate becomes a core style factor and leaves the
# add-one test (it is then drop-one tested like the other styles).  Both passed the add-one test in US and CN
# (marginal R² 0.006-0.010, |t| > 2 on 15-27% of days), comparable to st_momentum / overnight_gap / liquidity.
PROMOTED_CANDIDATES: tuple[str, ...] = ("etf_ownership", "retail_attention")
# Slow / traditional factors: monitoring layer only (Section 2.3)
SLOW_FACTORS = ("value", "earnings_yield", "quality", "momentum_12_1", "long_term_reversal")

CRYPTO_STYLE_FACTORS = ("btc_beta", "size", "momentum", "funding")
CRYPTO_EVENT_FACTORS = ("token_unlock",)

# Fixed, documented orthogonalisation order (Section 3.4): factor -> regress on
# Crowding is cleaned of size, volatility and liquidity last (Section 2.2, level 1, step 5).
# Promoted candidates are cleaned of size (raw exposure correlation: ETF ownership about +0.7, retail
# attention -0.5 to -0.7), so they carry only what size does not imply and size attribution is unchanged.
# Entries whose factor is not in a market's model are skipped.
ORTHOGONALISATION = {
    "liquidity": ("size",),
    "volatility": ("beta", "size"),
    "crowding": ("size", "volatility", "liquidity"),
    "etf_ownership": ("size",),
    "retail_attention": ("size",),
}
CROWDING_INPUTS = ("si_float", "days_to_cover", "borrow_fee", "borrow_scarcity", "utilisation")


# --------------------------------------------------------------------------- #
# Model / estimation parameters
# --------------------------------------------------------------------------- #
@dataclass
class ModelConfig:
    # exposures
    winsor_mad: float = 4.0            # clip at median +/- k * 1.4826 * MAD
    winsor_z: float = 3.0              # final z clip
    beta_halflife: int = 63
    beta_window: int = 252
    beta_shrink: float = 0.3           # Vasicek-style shrink toward 1
    vol_window: int = 20
    liquidity_window: int = 20
    reversal_window: int = 5
    momentum_window: int = 3
    gap_window: int = 5
    min_history: int = 60
    min_price: float = 1.0
    min_adv_usd: float = 2e6
    # cross-sectional regression
    regression_weight: str = "sqrt_mcap"
    n_stat_factors: int = 2
    stat_factor_window: int = 120
    # risk model
    vol_halflife: int = 21             # short half-life for volatilities
    corr_halflife: int = 84            # longer half-life for correlations
    specific_halflife: int = 42
    vra_halflife: int = 21             # volatility regime adjustment
    lw_max: float = 0.25               # cap on Ledoit-Wolf intensity: keep the few strong correlations
                                       # (e.g. reversal vs vol shocks); eigen adjustment handles noise
    eigen_sims: int = 60
    eigen_scale: float = 1.4           # USE4 'a' coefficient
    eigen_every: int = 5               # recompute eigen adjustment every k days
    event_specific_mult: float = 3.0   # extra specific vol on known event days
    cov_min_obs: int = 60
    macro_mult_cap: float = 3.0        # cap on macro-day variance uplift
    # time-series shock betas
    ts_beta_halflife: int = 63
    ts_min_obs: int = 60
    # crowding monitor (level 2) and in-play flag
    comomentum_window: int = 60
    comomentum_every: int = 5
    comomentum_decile: float = 0.1
    crowding_z_alert: float = 2.0
    in_play_volume_mult: float = 3.0
    in_play_move_sd: float = 3.0
    # validation
    bias_window: int = 63
    selection_min_dr2: float = 0.002   # factor selection: marginal cross-sectional R^2
    selection_min_sig: float = 0.15    # share of (estimable) days with |t| > 2
    selection_min_dr2_event: float = 0.02   # events: R^2 gained on the stock-days they affect
    # intraday
    intraday_days: int = 60
    intraday_beta_shrink: float = 0.5  # shrink intraday (Dimson) betas toward daily beta


MODEL = ModelConfig()


# --------------------------------------------------------------------------- #
# Limits (applied per strategy; exposures expressed per $ of gross)
# --------------------------------------------------------------------------- #
@dataclass
class LimitConfig:
    beta_adj_net_pct_gross: float = 0.10
    style_exposure_abs: float = 0.60          # (X^T h)/GMV in std units
    industry_net_pct_gross: float = 0.12
    max_name_pct_gross: dict[str, float] = field(default_factory=lambda: {
        "default": 0.04, "C1_US_EVENT": 0.08, "E1_CRYPTO_CARRY": 0.12})
    max_pct_adv: float = 0.15
    predicted_vol_annual_pct_gmv: dict[str, float] = field(default_factory=lambda: {
        "default": 0.10, "E1_CRYPTO_CARRY": 0.30})
    soft_slow_factor_abs: float = 0.30         # monitoring-layer soft threshold
    shock_loss_pct_gmv: float = 0.006          # expected loss in a 3-sigma vol or liquidity shock
    firm_days_to_unwind: float = 3.0           # internal crowding: firm position / (20% ADV)
    drift_z_alert: float = 3.0


LIMITS = LimitConfig()


# --------------------------------------------------------------------------- #
# Hypothetical stress scenarios, shocks in units of current factor daily vol
# (keeps them portable across markets and regimes).  Absolute shocks are
# given with an "abs:" prefix as daily returns.
# --------------------------------------------------------------------------- #
HYPOTHETICAL_SCENARIOS: dict[str, dict] = {
    "Aug-2007 quant deleveraging": {
        "description": "Crowded quant books unwind over 3 days; reversal and crowding crash.",
        "days": 3,
        "shocks": {"st_reversal": -4.0, "crowding": 3.0, "liquidity": -2.0, "size": -1.0,
                   "liq_shock": 4.0, "vol_shock": 3.0},
    },
    "Mar-2020 COVID crash": {
        "description": "Market -10%, volatility and beta spike, liquidity evaporates.",
        "days": 1,
        "shocks": {"market": "abs:-0.10", "beta": -3.0, "volatility": -3.0,
                   "liquidity": 2.5, "btc_beta": -3.0, "crypto:market": "abs:-0.35",
                   "vol_shock": 6.0, "liq_shock": 5.0, "rates": 3.0},
    },
    "Nov-2020 momentum/value rotation": {
        "description": "Value +5 sigma, 12-1 momentum -5 sigma in a single day (monitoring layer).",
        "days": 1,
        "shocks": {"slow:value": 5.0, "slow:momentum_12_1": -5.0, "volatility": 2.0, "size": 2.0},
    },
    "Jan-2021 short squeeze": {
        "description": "Heavily shorted names squeeze; crowding +6 sigma.",
        "days": 2,
        "shocks": {"crowding": 6.0, "volatility": 3.0, "st_reversal": -2.0},
    },
    "Aug-2024 carry unwind": {
        "description": "Global deleveraging: equities -4%, crypto -15%, crowded factors hit.",
        "days": 1,
        "shocks": {"market": "abs:-0.04", "crowding": 2.0, "liquidity": -2.0,
                   "crypto:market": "abs:-0.15", "vol_shock": 5.0, "liq_shock": 3.0,
                   "fx": -3.0, "us_session": -4.0},
    },
    "May-2022 LUNA collapse": {
        "description": "Crypto contagion: alt-coins -30%, funding flips negative.",
        "days": 2,
        "shocks": {"crypto:market": "abs:-0.20", "btc_beta": -3.0, "funding": -4.0,
                   "crypto_beta": -3.0},
    },
    "Rates shock / hawkish surprise": {
        "description": "10y futures -4 sigma after a macro release; duration-sensitive sectors hit.",
        "days": 1,
        "shocks": {"rates": -4.0, "vol_shock": 2.0, "fx": 2.0},
    },
    "Nov-2022 FTX failure": {
        "description": "Venue failure: exchange tokens -60%, crypto -20%, venue B marks frozen.",
        "days": 1,
        "shocks": {"crypto:market": "abs:-0.20", "crypto:Exchange Token": "abs:-0.50",
                   "crypto_beta": -2.0},
    },
}
