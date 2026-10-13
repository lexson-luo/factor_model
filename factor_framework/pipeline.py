"""End-to-end orchestration of the seven layers (Section 3.1)."""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import diagnostics as dg
from . import limits as lm
from . import stress as st
from . import validation as vl
from .attribution import PnLAttributor, reconciliation, returns_based_crosscheck
from .config import DATA_DIR, MODEL, OUTPUT_DIR, SPECIFIC_RISK_EVENTS
from .data_loader import (load_bars, load_crypto_panel, load_equity_panel, load_futures_bars, load_trading,
                          load_truth)
from .estimation import estimate_local_model
from .exposures import CryptoExposureBuilder, EquityExposureBuilder
from .global_layer import GlobalRiskLayer
from .intraday import IntradayModel
from .risk_model import RiskModelBuilder


@dataclass
class FrameworkResults:
    panels: dict
    trading: object
    models: dict
    risk: dict
    att: object
    recon: pd.DataFrame
    intraday: object = None
    glayer: object = None
    firm_risk: pd.DataFrame = field(default_factory=pd.DataFrame)
    firm_risk_last: object = None
    diagnostics: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    stress: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)
    truth: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)


def firm_risk_history(att, risk: dict, glayer: GlobalRiskLayer, start: pd.Timestamp):
    """Aggregate holdings across strategies by local model and compute firm risk every business day."""
    cal = glayer.calendar
    rows, last = [], None
    by_model = {}
    for s, b in att.books.items():
        by_model.setdefault(b.market, []).append(b)
    for ti, d in enumerate(cal):
        if d < start or not np.isfinite(glayer.G[ti]).all():
            continue
        xs, svs = {}, {}
        cn_net = 0.0
        for m, books in by_model.items():
            rm = risk[m]
            k = rm.dates.searchsorted(d, "right") - 1
            if k < 0 or not np.isfinite(rm.F[k]).all():
                continue
            h = sum(b.h.values[k] for b in books)
            pr = rm.portfolio(k, h)
            xs[m] = pr.exposures
            svs[m] = pr.specific_vol ** 2
            if m == "CN":
                cn_net = h.sum()
        xs["FX"] = pd.Series({"FX:CNY": cn_net})
        fr = glayer.firm_risk(ti, xs, svs)
        last = fr
        rows.append({"date": d, "firm_vol": fr.total_vol, "diversification": fr.diversification,
                     **{f"standalone_{k}": v for k, v in fr.standalone_vol.items()},
                     **{f"contrib_{k}": v for k, v in fr.contribution.items()}})
    return pd.DataFrame(rows).set_index("date"), last


def run(data_dir: Path = DATA_DIR, out_dir: Path = OUTPUT_DIR, write_reports: bool = True,
        verbose: bool = True) -> FrameworkResults:
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    log = print if verbose else (lambda *a, **k: None)
    T = {}
    clock = time.time()

    def lap(name):
        nonlocal clock
        T[name] = time.time() - clock
        log(f"  [{name}] {T[name]:.1f}s")
        clock = time.time()

    log("Layer 1  data")
    us, cn, cp = load_equity_panel("US", data_dir), load_equity_panel("CN", data_dir), load_crypto_panel(data_dir)
    td, truth = load_trading(data_dir), load_truth(data_dir)
    panels = {"US": us, "CN": cn, "CRYPTO": cp}
    lap("data")

    log("Layer 2-3  exposures and factor returns")
    btc = np.log1p(cp.ret["BTC"]).fillna(0)
    models = {
        "US": estimate_local_model("US", EquityExposureBuilder(us, btc).build(), us.ret, us.ret_on, us.ret_id),
        "CN": estimate_local_model("CN", EquityExposureBuilder(cn).build(), cn.ret, cn.ret_on, cn.ret_id),
        "CRYPTO": estimate_local_model("CRYPTO", CryptoExposureBuilder(cp).build(), cp.ret, n_stat=1),
    }
    lap("exposures+regression")

    log("Layer 4  risk models")
    risk = {m: RiskModelBuilder(models[m], event_factors=SPECIFIC_RISK_EVENTS, macro_day=panels[m].macro_day).build()
            for m in ("US", "CN")}
    risk["CRYPTO"] = RiskModelBuilder(models["CRYPTO"], event_factors=("token_unlock",)).build()
    lap("risk")

    log("Layer 5  attribution")
    att = PnLAttributor(panels, models, td).run()
    recon = reconciliation(att.daily)
    lap("attribution")
    res = FrameworkResults(panels, td, models, risk, att, recon, truth=truth, timings=T)

    log("Intraday layer")
    us_strats = [s for s, b in att.books.items() if b.market == "US"]
    res.intraday = IntradayModel(us, models["US"], load_bars("US", data_dir),
                                 load_futures_bars("US", data_dir)).run(td, att, us_strats, risk["US"])
    lap("intraday")

    log("Global layer")
    cal = pd.bdate_range(us.dates[0], us.dates[-1])
    usd_per_cny = cn.usd_per_local
    glayer = GlobalRiskLayer(risk, {m: risk[m].factor_returns for m in risk}, usd_per_cny, cal).build()
    start = pd.Timestamp(td.official_pnl.date.min())
    res.glayer = glayer
    res.firm_risk, res.firm_risk_last = firm_risk_history(att, risk, glayer, start)
    lap("global")

    log("Layer 6  diagnostics")
    D = res.diagnostics
    D["surrogate"] = {}
    for s, b in att.books.items():
        if b.market in ("US", "CN") and s != "B1_US_INTRADAY":
            D["surrogate"][s] = dg.surrogate_model(s, b, panels[b.market], models[b.market])
    # SHAP attribution cross-check: one return surrogate per market, then the two-sided P&L split per strategy
    D["return_surrogate"], D["shap_attribution"] = {}, {}
    for m in sorted({att.books[s].market for s in D["surrogate"]}):
        live = np.flatnonzero(sum(np.abs(b.h.values).sum(axis=1) for b in att.books.values() if b.market == m) > 0)
        D["return_surrogate"][m] = dg.return_surrogate(m, panels[m], models[m], live)
    for s, sur in D["surrogate"].items():
        D["shap_attribution"][s] = dg.shap_attribution(s, att.books[s], sur, D["return_surrogate"][att.books[s].market],
                                                       att)
    D["overlap"] = dg.strategy_overlap(att)
    n_obs = len(att.by_reporting_day().index.get_level_values(0).unique())
    D["resid_corr_named"] = dg.residual_correlation_test(D["overlap"]["corr_residual_named_only"], n_obs)
    D["resid_corr_core"] = dg.residual_correlation_test(D["overlap"]["corr_residual"], n_obs)
    D["regimes"] = dg.detect_regimes(models["US"])
    D["residual_pca"] = {m: dg.residual_pca(models[m], panels[m]) for m in ("US", "CN")}
    D["residual_pca_core"] = {m: dg.residual_pca(models[m], panels[m], use_named=False) for m in ("US", "CN")}
    D["shared_shocks"] = dg.shared_residual_shocks(att)
    style_like = ["beta", "size", "liquidity", "volatility", "st_reversal", "st_momentum", "overnight_gap",
                  "crowding", "btc_beta", "momentum", "funding", "stat_1", "beta_adj_net",
                  "vol_shock", "liq_shock", "fx", "rates", "us_session"]
    D["drift"] = dg.exposure_drift(att.exposures, style_like)
    D["releases"] = dg.release_comparison(att.exposures, td.releases, style_like)
    D["lead_lag"] = glayer.lead_lag()
    D["factor_crowding"] = {m: dg.factor_crowding(models[m], panels[m]) for m in ("US", "CN")}
    D["shock_sensitivities"] = dg.shock_sensitivities(att, models, risk)
    D["monitor_exposures"] = dg.monitor_exposures(att, models)
    D["crosscheck"] = returns_based_crosscheck(att.daily, att.exposures, models["US"].factor_returns,
                                               "C1_US_EVENT", ["market", "beta", "st_reversal", "volatility"])
    lap("diagnostics")

    log("Validation")
    V = res.validation
    V["factor_bias"] = {m: vl.factor_bias(models[m], risk[m]) for m in models}
    V["specific_bias"] = {m: vl.specific_bias(models[m], risk[m]) for m in models}
    V["portfolio_bias"], V["portfolio_bias_series"] = vl.portfolio_bias(att, risk)
    V["factor_quality"] = {m: vl.factor_quality(models[m]) for m in models}
    V["vif"] = {m: vl.vif(models[m].expo) for m in ("US", "CN")}
    V["stability"] = {m: vl.exposure_stability(models[m].expo) for m in ("US", "CN")}
    V["explained"] = vl.explained_share(att)
    V["r2"] = pd.DataFrame({m: {"named": models[m].r2_named.loc[start:].mean(),
                                "hybrid": models[m].r2_hybrid.loc[start:].mean()} for m in models}).T
    V["truth"] = {m: vl.truth_recovery(models[m], truth[m],
                                       {"crypto_beta": "crypto"} if m == "US" else {})
                  for m in ("US", "CN") if m in truth}
    V["challengers"] = vl.challenger_comparison(models["US"], risk["US"], att, "US")
    if len(truth.get("stress", [])):
        V["event_replay"] = vl.event_replay(att, V["portfolio_bias_series"], truth["stress"])
    V["factor_selection"] = pd.concat([vl.factor_selection(models[m], att, m, start, truth.get("stress"))
                                       for m in ("US", "CN")], ignore_index=True)
    V["ts_betas"] = {m: vl.ts_beta_checks(models[m], truth.get(f"ts_loadings_{m}")) for m in ("US", "CN")}
    if "regime_US" in truth:
        r = D["regimes"].join(truth["regime_US"].rename("true_regime"), how="inner")
        V["regime_accuracy"] = float((r.regime == r.true_regime).mean())
    lap("validation")

    log("Stress and limits")
    episodes = truth.get("stress", pd.DataFrame(columns=["episode", "market", "date"]))
    cmult = {m: D["factor_crowding"][m]["latest"].set_index("factor").stress_multiplier.to_dict() for m in ("US", "CN")}
    teams = td.strategies.set_index("strategy").team.to_dict()
    res.stress = {"hypothetical": st.hypothetical_scenarios(att, models, risk, crowding_mult=cmult),
                  "internal_crowding": st.internal_crowding(att, panels, teams),
                  "historical_factor": st.historical_factor_replay(att, models, episodes),
                  "stock_level": st.stock_level_replay(att, panels, models, episodes),
                  "liquidity": st.liquidity_stress(att, panels)}
    D["rolling_shock_betas"] = dg.rolling_shock_betas(att, models)
    hist = lm.limit_history(att, panels, models, risk, shock_betas=D["rolling_shock_betas"])
    res.limits = {"history": hist, "current": lm.current_status(hist), "breaches": lm.breach_log(hist)}
    lap("stress+limits")

    if write_reports:
        from .reporting import write_all
        log("Layer 7  reporting")
        write_all(res, Path(out_dir))
        lap("reporting")
    return res
