"""Core invariants of the framework (fast; uses small synthetic inputs plus the generated data if present)."""
import numpy as np
import pandas as pd
import pytest

from factor_framework.attribution import carino_link
from factor_framework.config import DATA_DIR
from factor_framework.estimation import constrained_wls
from factor_framework.exposures import orthogonalize, standardize
from factor_framework.risk_model import eigen_adjustment


def test_standardize_cap_weighted_mean_zero_unit_std():
    rng = np.random.default_rng(0)
    raw = rng.lognormal(size=500)
    cap = rng.lognormal(10, 1, 500)
    z = standardize(raw, np.ones(500, bool), cap)
    assert abs(np.average(z, weights=cap)) < 0.05
    assert abs(z.std() - 1) < 0.1
    assert np.abs(z).max() <= 3.0 + 1e-12


def test_orthogonalize_removes_projection():
    rng = np.random.default_rng(1)
    a = rng.normal(size=300)
    y = 0.8 * a + rng.normal(size=300)
    yp = orthogonalize(y, a[:, None], np.ones(300, bool), np.ones(300))
    assert abs(np.corrcoef(yp, a)[0, 1]) < 1e-8


def test_constrained_regression_recovers_factors_and_constraint():
    rng = np.random.default_rng(2)
    n, n_ind = 400, 4
    ind = rng.integers(0, n_ind, n)
    X = np.column_stack([np.ones(n), np.eye(n_ind)[ind], rng.normal(size=(n, 2))])
    cap = rng.lognormal(size=n)
    caps = np.array([cap[ind == j].sum() for j in range(n_ind)])
    f_ind = rng.normal(0, 0.01, n_ind)
    f_ind -= (caps * f_ind).sum() / caps.sum()             # satisfy constraint
    f_true = np.r_[0.01, f_ind, 0.004, -0.002]
    y = X @ f_true + rng.normal(0, 0.002, n)
    ind_idx = list(range(1, 1 + n_ind))
    ind_cap = np.zeros(X.shape[1]); ind_cap[ind_idx] = caps
    f, se, r2, _ = constrained_wls(y, X, np.ones(n), ind_idx, ind_cap, np.ones(X.shape[1], bool))
    assert abs((caps * f[ind_idx]).sum()) < 1e-10
    assert np.allclose(f, f_true, atol=1e-3)
    assert r2 > 0.8


def test_eigen_adjustment_inflates_small_eigenvalues():
    rng = np.random.default_rng(3)
    A = rng.normal(size=(10, 10))
    F = A @ A.T / 10 + np.eye(10) * 0.1
    g = eigen_adjustment(F, 60, 40, 1.4, rng)
    assert g[0] > 1.0                   # smallest eigen-portfolio risk is underestimated in samples
    assert np.all(np.isfinite(g))


def test_carino_linking_adds_up():
    rng = np.random.default_rng(4)
    comp = pd.DataFrame(rng.normal(0, 0.005, (50, 3)), columns=list("abc"))
    total = comp.sum(axis=1)
    linked = carino_link(comp, total)
    assert np.isclose(linked.sum(), (1 + total).prod() - 1)


needs_data = pytest.mark.skipif(not (DATA_DIR / "trading/positions_eod.csv.gz").exists(),
                                reason="run generate_data.py first")


@needs_data
def test_end_to_end_attribution_reconciles_and_is_additive():
    from factor_framework.attribution import COMPONENTS, PnLAttributor, reconciliation
    from factor_framework.data_loader import load_crypto_panel, load_trading
    from factor_framework.estimation import estimate_local_model
    from factor_framework.exposures import CryptoExposureBuilder
    cp, td = load_crypto_panel(), load_trading()
    fm = estimate_local_model("CRYPTO", CryptoExposureBuilder(cp).build(), cp.ret, n_stat=1)
    att = PnLAttributor({"CRYPTO": cp}, {"CRYPTO": fm}, td).run(["E1_CRYPTO_CARRY"])
    d = att.daily
    assert np.allclose(d[COMPONENTS].sum(axis=1), d.total_attributed)
    assert np.allclose(d.factor + d.slow_factor + d.specific + d.basis, d.hold_pnl)
    assert d.basis.abs().sum() > 0                  # perp marks differ from the spot the model is estimated on
    rec = reconciliation(d)
    assert (~rec["break"]).mean() > 0.99


def test_time_series_betas_recover_sensitivities_and_are_demeaned():
    from factor_framework.exposures import time_series_betas
    rng = np.random.default_rng(5)
    T, N = 400, 120
    dates = pd.bdate_range("2024-01-01", periods=T)
    m = pd.Series(rng.normal(0, 0.01, T), index=dates)
    g = pd.DataFrame({"fx": rng.normal(0, 0.004, T)}, index=dates)
    sector = np.repeat(np.arange(6), N // 6)
    b_true = np.array([-0.8, -0.4, 0.0, 0.3, 0.6, 1.0])[sector] + rng.normal(0, 0.2, N)
    r = pd.DataFrame(np.outer(m, np.ones(N)) + np.outer(g.fx, b_true) + rng.normal(0, 0.012, (T, N)),
                     index=dates)
    estu = pd.DataFrame(True, index=dates, columns=r.columns)
    cap = pd.DataFrame(1.0, index=dates, columns=r.columns)
    B, info = time_series_betas(r, m, g, sector, estu, cap)
    last = B[-1, :, 0]
    assert np.corrcoef(last, b_true)[0, 1] > 0.8
    assert abs(last.mean()) < 1e-8                      # demeaned: market factor stays identified


needs_data_module = pytest.mark.skipif(not (DATA_DIR / "market/index_futures_bars_30m_US.csv").exists(),
                                       reason="run generate_data.py first")


@pytest.fixture(scope="module")
def us_model():
    from factor_framework.data_loader import load_crypto_panel, load_equity_panel
    from factor_framework.estimation import estimate_local_model
    from factor_framework.exposures import EquityExposureBuilder
    cp, us = load_crypto_panel(), load_equity_panel("US")
    btc = np.log1p(cp.ret["BTC"]).fillna(0)
    return us, estimate_local_model("US", EquityExposureBuilder(us, btc).build(), us.ret, us.ret_on, us.ret_id)


@needs_data_module
def test_hybrid_model_is_additive(us_model):
    """r = X_cs f_cs + B g + X_stat f_stat + u exactly, for every modelled stock-day."""
    us, fm = us_model
    X = fm.expo.X
    fitted = np.einsum("tnk,tk->tn", np.nan_to_num(X), np.nan_to_num(fm.factor_returns.values))
    gap = us.ret.values - fitted - fm.resid.values
    ok = np.all(np.isfinite(X), 2) & np.isfinite(fm.resid.values) & np.isfinite(us.ret.values)
    assert ok.sum() > 1000
    assert np.nanmax(np.abs(gap[ok])) < 1e-10


@needs_data_module
def test_crowding_is_cleaned_of_size_volatility_liquidity(us_model):
    _, fm = us_model
    e = fm.expo
    t = len(e.dates) - 1
    m = e.estu.values[t]
    c = e.X[t, m, e.factors.index("crowding")]
    for f in ("size", "volatility", "liquidity"):
        assert abs(np.corrcoef(c, e.X[t, m, e.factors.index(f)])[0, 1]) < 0.15


@needs_data_module
def test_promoted_candidates_are_core_styles_cleaned_of_size(us_model):
    from factor_framework.config import PROMOTED_CANDIDATES
    _, fm = us_model
    e = fm.expo
    t = len(e.dates) - 1
    m = e.estu.values[t]
    size = e.X[t, m, e.factors.index("size")]
    w = e.reg_weight.values[t][m]

    def wcorr(a, b):            # orthogonality holds under the regression weights (equal-weighted it need not:
        a, b = a - np.average(a, weights=w), b - np.average(b, weights=w)   # the link to size is non-linear)
        return np.average(a * b, weights=w) / np.sqrt(np.average(a * a, weights=w) * np.average(b * b, weights=w))

    for f in PROMOTED_CANDIDATES:
        assert e.groups[f] == "style" and f not in e.candidates
        assert f in fm.factor_returns.columns
        assert abs(wcorr(e.X[t, m, e.factors.index(f)], size)) < 0.01


@needs_data_module
def test_event_dummies_are_cap_centred_and_keep_raw_flags(us_model):
    from factor_framework.config import EVENT_FACTORS
    us, fm = us_model
    e = fm.expo
    t = int(np.flatnonzero(us.option_expiry.values)[-1])          # every index member flagged
    m = e.estu.values[t]
    cap = np.nan_to_num(e.cap.values[t])[m]
    for f in EVENT_FACTORS:
        x, raw = e.X[t, m, e.factors.index(f)], e.flags[f][t][m]
        assert abs(np.average(x, weights=cap)) < 1e-12
        assert set(np.unique(raw)) <= {-1.0, 0.0, 1.0}
        assert np.allclose(x - raw, (x - raw)[0])                 # centring is a per-day shift only
    # the market factor stays the cap-weighted universe return on expiry days (raw 0/1 dummies: ~60bp RMS gap)
    cw = e.cap.where(e.estu)
    R = fm.returns.reindex(index=e.dates, columns=e.tickers)
    capret = (R * cw).sum(axis=1) / cw.where(R.notna()).sum(axis=1)
    gap = (fm.factor_returns["market"] - capret)[us.option_expiry.reindex(e.dates).fillna(False).values].dropna()
    assert np.sqrt((gap ** 2).mean()) < 0.002


@needs_data_module
def test_limit_hit_is_cap_centred_and_disjoint_from_in_play():
    from factor_framework.data_loader import load_equity_panel
    from factor_framework.exposures import EquityExposureBuilder
    e = EquityExposureBuilder(load_equity_panel("CN")).build()
    lh, ip = np.nan_to_num(e.flags["limit_hit"]), np.nan_to_num(e.flags["in_play"])
    assert np.count_nonzero(lh) > 0 and set(np.unique(lh)) <= {-1.0, 0.0, 1.0}
    assert not ((lh != 0) & (ip != 0)).any()                      # otherwise the two dummies can be collinear
    ip_any = np.nan_to_num(e.flags["in_play_any"])               # specific-risk uplift keeps limit hits in play
    assert ((lh != 0) & (ip_any != 0)).any() and not ((ip != 0) & (ip_any == 0)).any()
    t = int(np.argmax((lh != 0).sum(1)))                          # busiest limit-hit day
    m = e.estu.values[t]
    x = e.X[t, m, e.factors.index("limit_hit")]
    assert abs(np.average(x, weights=np.nan_to_num(e.cap.values[t])[m])) < 1e-12
    assert np.allclose(x - lh[t, m], (x - lh[t, m])[0])


@needs_data_module
def test_dimson_betas_correct_epps_bias(us_model):
    from factor_framework.data_loader import load_bars, load_futures_bars
    from factor_framework.intraday import IntradayModel
    us, fm = us_model
    im = IntradayModel(us, fm, load_bars("US"), load_futures_bars("US"))
    _, _, _, betas = im.estimate()
    b = betas.dropna()
    assert b.dimson_30m.mean() > b.concurrent_30m.mean() + 0.1


def test_surrogate_shap_is_additive_and_flags_unmapped_driver():
    from factor_framework.diagnostics import fit_surrogate
    rng = np.random.default_rng(0)
    T, N = 40, 300
    df = pd.DataFrame({"t": np.repeat(np.arange(T), N),
                       "reversal_5d": rng.standard_normal(T * N), "log_mcap": rng.standard_normal(T * N),
                       "theme_tag": (rng.random(T * N) < 0.2).astype(float),
                       "sector": rng.integers(0, 5, T * N).astype(float)})
    w = -df.reversal_5d + 1.5 * df.theme_tag * (df.reversal_5d < 0) + 0.1 * rng.standard_normal(T * N)
    df["weight"] = w / w.abs().sum() * T
    r = fit_surrogate(df, n_shap=2000, n_interact=300)
    assert r["reliable"] and r["r2_oos"] > 0.8
    assert r["importance"].feature.iloc[0] == "reversal_5d"
    assert r["candidate_factors"] == ["theme_tag"]
    assert r["interactions"].iloc[0][["a", "b"]].tolist() == ["reversal_5d", "theme_tag"]
    sv = r["shap_values"]
    feats = [c[5:] for c in sv.columns if c.startswith("shap_")]
    x = sv[[f"x_{f}" for f in feats]].set_axis(feats, axis=1)
    pred = r["model"].predict(x) * r["y_scale"]
    np.testing.assert_allclose(r["base_value"] + sv[[f"shap_{f}" for f in feats]].sum(axis=1), pred, atol=1e-6)
    assert set(r["fit"].target) == {"weight", "rank", "held_only"}   # no unheld names -> no 'held' AUC row


def test_two_sided_shap_attribution_is_exact_and_recovers_factor_pnl():
    from factor_framework.diagnostics import _by_group, fit_return_surrogate, two_sided_pnl
    rng = np.random.default_rng(1)
    T, N = 60, 400
    t, i = np.repeat(np.arange(T), N), np.tile(np.arange(N), T)
    x, z = rng.standard_normal(T * N), rng.standard_normal(T * N)
    f = rng.normal(0, 0.01, T)                                  # daily return of the reversal characteristic
    ret = f[t] * x + 0.01 * rng.standard_normal(T * N)
    frame = pd.DataFrame({"t": t, "i": i, "reversal_5d": x, "log_mcap": z,
                          "sector": rng.integers(0, 3, T * N).astype(float), "ret": ret})
    rs = fit_return_surrogate(frame, n_jobs=1)
    F, cols = rs.frame, [f"shap_{c}" for c in rs.feats]
    np.testing.assert_allclose(F.base + F[cols].sum(axis=1) + F.resid, F.ret, atol=1e-12)

    h = rng.standard_normal(T * N) * 1e4
    gmv = pd.Series(np.abs(h)).groupby(t).transform("sum").values
    w = h / gmv
    a = _by_group(np.c_[0.6 * w, 0.4 * w], ["reversal_5d", "log_mcap"], np.zeros(T * N), np.zeros(T * N))
    b = _by_group(F[cols].values, rs.feats, F.base.values, F.resid.values)
    M, ret_side, w_side = two_sided_pnl(t, gmv, a, b)
    pnl = pd.Series(h * ret).groupby(t).sum()
    np.testing.assert_allclose(ret_side.sum(axis=1), pnl, rtol=1e-9)
    np.testing.assert_allclose(w_side.sum(axis=1), pnl, rtol=1e-9)
    assert np.isclose(M.values.sum(), pnl.sum())
    np.testing.assert_allclose(w_side.st_reversal, 0.6 * pnl, rtol=1e-9)
    true = pd.Series(h * f[t] * x).groupby(t).sum()
    assert np.corrcoef(ret_side.st_reversal, true)[0, 1] > 0.8
    assert ret_side["size"].abs().sum() < 0.3 * ret_side.st_reversal.abs().sum()
