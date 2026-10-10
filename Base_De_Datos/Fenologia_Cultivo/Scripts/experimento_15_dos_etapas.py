#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EXPERIMENTO 15 — MODELO BIOFÍSICO EN DOS ETAPAS / NESTED LOGO
Reto AgroCebada 2026

Objetivo
========
Separar el rendimiento en dos componentes SIN usar identidad espacial:

    Y = f_ENV(CLIMATE, TOPO) + g_CROP(BASIC, PRO, TRAJ)

Municipio se usa exclusivamente como GROUP para Leave-One-Group-Out.
Nunca entra como predictor. Tampoco entran Estado, coordenadas, AREA_HA,
LOG_AREA, IDs, medias municipales, champion municipal ni sus residuos.

Arquitectura two-stage estricta
===============================
Dentro de cada outer LOGO:
  1) Stage1 ENV = Ridge sobre CLIMATE+TOPO.
  2) Para entrenar Stage2 se generan predicciones ENV OOF por municipio
     dentro del TRAIN; el residual de una parcela nunca usa un Stage1 que
     haya visto su municipio.
  3) Stage2 aprende residual = Y - ENV_OOF usando BASIC+PRO+TRAJ.
  4) Para predecir el municipio outer-test:
         ENV_TEST = Stage1 fit en todo outer-train
         CORR_TEST = Stage2(CROP_TEST)
         YHAT = ENV_TEST + lambda * CORR_TEST
  5) env_alpha, parámetros Stage2 y lambda se eligen sólo con inner LOGO.

Comparación
===========
    GLOBAL_MEAN
    BASE_RIDGE_ALL        (Exp09 biofísico: ENV + BASIC + PRO, sin TRAJ)
    ENV_RIDGE             (CLIMATE + TOPO)
    CROP_RIDGE            (BASIC + PRO + TRAJ)
    CROP_XGB              (BASIC + PRO + TRAJ)
    ONE_STAGE_RIDGE       (ENV + CROP)
    ONE_STAGE_XGB         (ENV + CROP)
    TWO_STAGE_RIDGE       (ENV Ridge + residual Ridge)
    TWO_STAGE_XGB         (ENV Ridge + residual XGBoost)

Métrica primaria de continuidad:
    MACRO_RMSE_ALL
Diagnóstico obligatorio:
    MACRO_RMSE_CORE (municipios N>=3)
    POOLED_RMSE, BIAS, CENTERED_RMSE, Spearman intramunicipal.

Benchmark municipality-free previo:
    0.682213 (RIDGE_ALL, Exp12/13/14)

Requiere artefactos de Exp09 y Exp14:
    01_Diagnostico_Modelo/01_Matriz_Features_138.csv
    01_Diagnostico_Modelo/02_Inventario_Features.csv
    02_Trayectorias_Temporales/04_Matriz_Trayectorias_138.csv
"""

from pathlib import Path
import hashlib, json, re, unicodedata, warnings
import numpy as np
import pandas as pd

from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

ID = "ID_POLIGONO"
MUNI = "Municipio"
Y = "RENDIMIENTO_T_HA"
SET = "CONJUNTO"
SEED = 20261008
BENCHMARK = 0.682213
PHENOLOGY_ROOT = Path(__file__).resolve().parents[1]

ENV_BLOCKS = {"CLIMATE", "TOPO"}
CROP_BLOCKS = {"BASIC", "PRO"}
FORBIDDEN = [
    "municipio", "estado", "area_ha", "log_area", "spatial", "coord",
    "longitude", "latitude", "latitud", "longitud", "rendimiento", "yield",
    "target", "pred", "prediction", "error", "resid", "delta"
]

RIDGE_GRID = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
ENV_ALPHA_GRID = [10.0, 100.0, 1000.0]
STAGE2_RIDGE_GRID = [10.0, 100.0, 1000.0]
CORR_LAMBDAS = [0.5, 1.0]

XGB_GRID = [
    dict(n_estimators=250, learning_rate=.03, max_depth=1, min_child_weight=12,
         gamma=.25, subsample=.80, colsample_bytree=.60, reg_alpha=2., reg_lambda=30.),
    dict(n_estimators=250, learning_rate=.05, max_depth=1, min_child_weight=6,
         gamma=.10, subsample=.80, colsample_bytree=.85, reg_alpha=1., reg_lambda=20.),
    dict(n_estimators=250, learning_rate=.03, max_depth=2, min_child_weight=10,
         gamma=.20, subsample=.80, colsample_bytree=.60, reg_alpha=2., reg_lambda=30.),
    dict(n_estimators=250, learning_rate=.05, max_depth=2, min_child_weight=6,
         gamma=.05, subsample=.80, colsample_bytree=.80, reg_alpha=.5, reg_lambda=15.),
]
STAGE2_XGB_GRID = XGB_GRID


def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def forbidden(c):
    n = norm_name(c)
    return any(t in n for t in FORBIDDEN)


def stable_seed(*parts):
    raw = "|".join(map(str, parts)).encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def rmse(y, p):
    return float(np.sqrt(mean_squared_error(y, p)))


def mae(y, p):
    return float(mean_absolute_error(y, p))


def bias(y, p):
    return float(np.mean(np.asarray(p, float) - np.asarray(y, float)))


def centered_rmse(y, p):
    if len(y) < 2:
        return np.nan
    e = np.asarray(p, float) - np.asarray(y, float)
    return float(np.sqrt(np.mean((e - e.mean()) ** 2)))


def spearman_within(y, p):
    if len(y) < 3:
        return np.nan
    a, b = pd.Series(y), pd.Series(p)
    if a.nunique() < 2 or b.nunique() < 2:
        return np.nan
    return float(a.rank().corr(b.rank(), method="pearson"))


def metrics(y, p):
    return dict(RMSE=rmse(y, p), MAE=mae(y, p), BIAS=bias(y, p),
                CENTERED_RMSE=centered_rmse(y, p), SPEARMAN_WITHIN=spearman_within(y, p))


def find_file(bases, rels):
    for b in bases:
        for rel in rels:
            p = b / rel
            if p.is_file():
                return p
    return None


def locate():
    root = PHENOLOGY_ROOT
    master = root / "Maestro_Cebada_197.csv"
    matrix = root / "01_Diagnostico_Modelo" / "01_Matriz_Features_138.csv"
    inventory = root / "01_Diagnostico_Modelo" / "02_Inventario_Features.csv"
    trajectories = root / "02_Trayectorias_Temporales" / "04_Matriz_Trayectorias_138.csv"
    missing = [str(path) for path in (master, matrix, inventory, trajectories) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Faltan archivos de entrada:\n  - " + "\n  - ".join(missing))
    return master, matrix, inventory, trajectories



def feature_sets(inv, mat, traj):
    z = inv.copy()
    z["FEATURE"] = z["FEATURE"].astype(str)
    z["BLOCK"] = z["BLOCK"].astype(str).str.upper()
    z["PRESENT"] = z["FEATURE"].isin(mat.columns)
    z["FORBIDDEN"] = z["FEATURE"].map(forbidden)
    env = z.loc[z["BLOCK"].isin(ENV_BLOCKS) & z["PRESENT"] & ~z["FORBIDDEN"], "FEATURE"].tolist()
    crop_base = z.loc[z["BLOCK"].isin(CROP_BLOCKS) & z["PRESENT"] & ~z["FORBIDDEN"], "FEATURE"].tolist()
    traj_cols = [c for c in traj.columns if c != ID and not forbidden(c)]
    crop = list(dict.fromkeys(crop_base + traj_cols))
    base_all = list(dict.fromkeys(env + crop_base))
    one = list(dict.fromkeys(env + crop))
    leaks = [c for c in one if forbidden(c)]
    if leaks:
        raise RuntimeError("Features prohibidas: " + ", ".join(leaks))
    audit = pd.DataFrame(
        [(c, "ENV", "EXP09") for c in env] +
        [(c, "CROP", "EXP09") for c in crop_base] +
        [(c, "CROP", "EXP14_TRAJ") for c in traj_cols],
        columns=["FEATURE", "ROLE", "SOURCE"]
    )
    return env, crop_base, traj_cols, crop, base_all, one, audit


def require_xgb():
    try:
        import xgboost  # noqa
    except Exception as e:
        raise RuntimeError("Instala xgboost: pip install xgboost") from e


def ridge(alpha):
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("model", Ridge(alpha=float(alpha)))
    ])


def xgb(params, seed):
    from xgboost import XGBRegressor
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("model", XGBRegressor(objective="reg:squarederror", eval_metric="rmse",
                               tree_method="hist", random_state=seed, n_jobs=-1,
                               verbosity=0, **params))
    ])


def standard_grid(name):
    if "RIDGE" in name:
        return [{"alpha": a} for a in RIDGE_GRID]
    return XGB_GRID


def make_standard(name, params, seed):
    if "RIDGE" in name:
        return ridge(params["alpha"])
    return xgb(params, seed)


def tune_standard(X, y, groups, name, outer):
    logo = LeaveOneGroupOut()
    rows, best_score, best_params, best_i = [], np.inf, None, None
    for i, params in enumerate(standard_grid(name), 1):
        scores = []
        for j, (tr, va) in enumerate(logo.split(X, y, groups), 1):
            m = make_standard(name, params, stable_seed(SEED, name, outer, i, j))
            m.fit(X.iloc[tr], y[tr])
            scores.append(rmse(y[va], m.predict(X.iloc[va])))
        score = float(np.mean(scores))
        rows.append(dict(OUTER_HELDOUT=outer, MODEL=name, CANDIDATE=i,
                         INNER_MACRO_RMSE=score, PARAMS=json.dumps(params, sort_keys=True)))
        if score < best_score - 1e-12:
            best_score, best_params, best_i = score, params, i
    return best_params, best_score, best_i, pd.DataFrame(rows)


def env_crossfit(Xe, y, groups, alpha):
    logo = LeaveOneGroupOut()
    p = np.full(len(y), np.nan)
    for tr, va in logo.split(Xe, y, groups):
        m = ridge(alpha)
        m.fit(Xe.iloc[tr], y[tr])
        p[va] = m.predict(Xe.iloc[va])
    if not np.isfinite(p).all():
        raise RuntimeError("ENV crossfit incompleto")
    return p


def stage2_model(kind, params, seed):
    if kind == "TWO_STAGE_RIDGE":
        return ridge(params["alpha"])
    return xgb(params, seed)


def two_candidates(kind):
    out = []
    s2_grid = ([{"alpha": a} for a in STAGE2_RIDGE_GRID]
               if kind == "TWO_STAGE_RIDGE" else STAGE2_XGB_GRID)
    for ea in ENV_ALPHA_GRID:
        for s2 in s2_grid:
            for lam in CORR_LAMBDAS:
                out.append(dict(env_alpha=ea, stage2_params=s2, correction_lambda=lam))
    return out


def prepare_inner_env_cache(Xe, y, groups, env_alpha):
    """Para cada inner fold, residuals OOF estrictos dentro del inner-train + ENV prediction del valid."""
    logo = LeaveOneGroupOut()
    cache = []
    for inner_i, (idx_t, idx_v) in enumerate(logo.split(Xe, y, groups), 1):
        Xe_t = Xe.iloc[idx_t].reset_index(drop=True)
        y_t = y[idx_t]
        g_t = groups[idx_t]
        env_oof_t = env_crossfit(Xe_t, y_t, g_t, env_alpha)
        env_final = ridge(env_alpha)
        env_final.fit(Xe_t, y_t)
        env_v = env_final.predict(Xe.iloc[idx_v])
        cache.append((idx_t, idx_v, env_oof_t, env_v))
    return cache


def tune_two_stage(Xe, Xc, y, groups, kind, outer):
    rows, best_score, best_cfg, best_i = [], np.inf, None, None
    cache_by_alpha = {a: prepare_inner_env_cache(Xe, y, groups, a) for a in ENV_ALPHA_GRID}
    for i, cfg in enumerate(two_candidates(kind), 1):
        scores = []
        for inner_i, (idx_t, idx_v, env_oof_t, env_v) in enumerate(cache_by_alpha[cfg["env_alpha"]], 1):
            resid_t = y[idx_t] - env_oof_t
            s2 = stage2_model(kind, cfg["stage2_params"], stable_seed(SEED, kind, outer, i, inner_i))
            s2.fit(Xc.iloc[idx_t], resid_t)
            corr_v = s2.predict(Xc.iloc[idx_v])
            pred_v = env_v + cfg["correction_lambda"] * corr_v
            scores.append(rmse(y[idx_v], pred_v))
        score = float(np.mean(scores))
        rows.append(dict(OUTER_HELDOUT=outer, MODEL=kind, CANDIDATE=i,
                         INNER_MACRO_RMSE=score, ENV_ALPHA=cfg["env_alpha"],
                         CORRECTION_LAMBDA=cfg["correction_lambda"],
                         STAGE2_PARAMS=json.dumps(cfg["stage2_params"], sort_keys=True)))
        if score < best_score - 1e-12:
            best_score, best_cfg, best_i = score, cfg, i
    return best_cfg, best_score, best_i, pd.DataFrame(rows)


def fit_two_stage(Xe_tr, Xc_tr, ytr, gtr, Xe_te, Xc_te, kind, cfg, outer):
    env_oof = env_crossfit(Xe_tr, ytr, gtr, cfg["env_alpha"])
    resid = ytr - env_oof
    s2 = stage2_model(kind, cfg["stage2_params"], stable_seed(SEED, "FINAL", kind, outer))
    s2.fit(Xc_tr, resid)
    env_final = ridge(cfg["env_alpha"])
    env_final.fit(Xe_tr, ytr)
    env_te = env_final.predict(Xe_te)
    corr_raw = s2.predict(Xc_te)
    corr_used = cfg["correction_lambda"] * corr_raw
    return env_te, corr_raw, corr_used, env_te + corr_used


def summarize(results, preds):
    rows = []
    for name, g in results.groupby("MODEL"):
        p = preds[preds["MODEL"].eq(name)]
        core = g[g["N_TEST"] >= 3]
        sp = core[core["SPEARMAN_WITHIN"].notna()]
        rows.append(dict(
            MODEL=name,
            N_MUNICIPIOS_ALL=int(g[MUNI].nunique()),
            N_MUNICIPIOS_CORE_NGE3=int(core[MUNI].nunique()),
            MACRO_RMSE_ALL=float(g.RMSE.mean()),
            MACRO_RMSE_CORE=float(core.RMSE.mean()),
            POOLED_RMSE=rmse(p.REAL, p.PRED),
            MACRO_MAE_ALL=float(g.MAE.mean()),
            MACRO_ABS_BIAS_ALL=float(g.BIAS.abs().mean()),
            MACRO_CENTERED_RMSE_CORE=float(core.CENTERED_RMSE.mean()),
            MEAN_SPEARMAN_CORE=float(sp.SPEARMAN_WITHIN.mean()) if len(sp) else np.nan,
            MEDIAN_SPEARMAN_CORE=float(sp.SPEARMAN_WITHIN.median()) if len(sp) else np.nan,
            WORST_MUNICIPIO_RMSE=float(g.RMSE.max()),
        ))
    return pd.DataFrame(rows).sort_values("MACRO_RMSE_ALL").reset_index(drop=True)


def main():
    require_xgb()
    master_p, mat_p, inv_p, traj_p = locate()
    master = pd.read_csv(master_p, encoding="utf-8-sig")
    mat = pd.read_csv(mat_p, encoding="utf-8-sig")
    inv = pd.read_csv(inv_p, encoding="utf-8-sig")
    traj = pd.read_csv(traj_p, encoding="utf-8-sig")

    for df in [master, mat, traj]:
        df[ID] = df[ID].astype(str).str.strip()
    master[MUNI] = master[MUNI].astype(str).str.strip()
    master[SET] = master[SET].astype(str).str.strip().str.upper()
    master[Y] = pd.to_numeric(master[Y], errors="coerce")
    if MUNI in mat.columns:
        mat = mat.drop(columns=[MUNI])
    if MUNI in traj.columns:
        traj = traj.drop(columns=[MUNI])

    train = master[master[SET].eq("ENTRENAMIENTO")][[ID, MUNI, Y]].copy()
    if len(train) != 138:
        raise ValueError(f"Esperaba 138 TRAIN; encontré {len(train)}")

    env, crop_base, traj_cols, crop, base_all, one, audit = feature_sets(inv, mat, traj)
    if len(env) < 5 or len(crop) < 100:
        raise RuntimeError(f"Feature sets inesperados: ENV={len(env)}, CROP={len(crop)}")

    data = train.merge(mat[[ID] + list(dict.fromkeys(env + crop_base))], on=ID, how="left", validate="one_to_one")
    data = data.merge(traj[[ID] + traj_cols], on=ID, how="left", validate="one_to_one")
    for c in one:
        data[c] = pd.to_numeric(data[c], errors="coerce")

    outdir = PHENOLOGY_ROOT / "03_Modelo_Dos_Etapas"
    outdir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(outdir / "01_Auditoria_Features.csv", index=False, encoding="utf-8-sig")

    counts = data[MUNI].value_counts().sort_values(ascending=False)
    print("=" * 138)
    print("EXPERIMENTO 15 — MODELO BIOFÍSICO EN DOS ETAPAS / NESTED LOGO")
    print("=" * 138)
    print(f"ENV features:          {len(env)}")
    print(f"CROP summaries:        {len(crop_base)}")
    print(f"CROP trajectories:     {len(traj_cols)}")
    print(f"CROP total:            {len(crop)}")
    print(f"BASE_ALL no-TRAJ:      {len(base_all)}")
    print(f"ONE_STAGE total:       {len(one)}")
    print("\nMunicipio = GROUP solamente; nunca predictor.\n")
    print(counts.to_string())

    groups = data[MUNI].astype(str).to_numpy()
    yall = data[Y].to_numpy(float)
    outer_groups = sorted(data[MUNI].unique())

    res_rows, pred_rows, par_rows, tune_parts, comp_rows = [], [], [], [], []
    specs = {
        "BASE_RIDGE_ALL": base_all,
        "ENV_RIDGE": env,
        "CROP_RIDGE": crop,
        "CROP_XGB": crop,
        "ONE_STAGE_RIDGE": one,
        "ONE_STAGE_XGB": one,
    }

    for oi, held in enumerate(outer_groups, 1):
        te = np.flatnonzero(groups == str(held))
        tr = np.flatnonzero(groups != str(held))
        ytr, yte, gtr = yall[tr], yall[te], groups[tr]
        ids_te = data.iloc[te][ID].tolist()
        print("\n" + "-" * 138)
        print(f"OUTER {oi}/{len(outer_groups)} | HELD-OUT={held} | N_TEST={len(te)} | N_TRAIN={len(tr)}")
        print("-" * 138)

        pm = np.full(len(yte), float(ytr.mean()))
        met = metrics(yte, pm)
        res_rows.append(dict(**{MUNI: held}, N_TEST=len(yte), MODEL="GLOBAL_MEAN", **met,
                             INNER_MACRO_RMSE=np.nan, BEST_CANDIDATE=np.nan))
        for pid, yy, pp in zip(ids_te, yte, pm):
            pred_rows.append(dict(**{ID: pid, MUNI: held}, MODEL="GLOBAL_MEAN", REAL=float(yy), PRED=float(pp), ERROR=float(pp-yy)))
        print(f"{'GLOBAL_MEAN':20s} RMSE={met['RMSE']:.6f} | BIAS={met['BIAS']:+.6f}")

        for name, cols in specs.items():
            Xtr = data.iloc[tr][cols].reset_index(drop=True)
            Xte = data.iloc[te][cols].reset_index(drop=True)
            bp, bis, bi, tdf = tune_standard(Xtr, ytr, gtr, name, held)
            tune_parts.append(tdf)
            par_rows.append(dict(OUTER_HELDOUT=held, MODEL=name, BEST_CANDIDATE=bi,
                                 INNER_MACRO_RMSE=bis, BEST_PARAMS=json.dumps(bp, sort_keys=True)))
            m = make_standard(name, bp, stable_seed(SEED, "FINALSTD", held, name))
            m.fit(Xtr, ytr)
            pp = m.predict(Xte)
            met = metrics(yte, pp)
            res_rows.append(dict(**{MUNI: held}, N_TEST=len(yte), MODEL=name, **met,
                                 INNER_MACRO_RMSE=bis, BEST_CANDIDATE=bi))
            for pid, yy, pred in zip(ids_te, yte, pp):
                pred_rows.append(dict(**{ID: pid, MUNI: held}, MODEL=name, REAL=float(yy), PRED=float(pred), ERROR=float(pred-yy)))
            cr = f"{met['CENTERED_RMSE']:.6f}" if np.isfinite(met['CENTERED_RMSE']) else "NA"
            print(f"{name:20s} inner={bis:.6f} | RMSE={met['RMSE']:.6f} | BIAS={met['BIAS']:+.6f} | cRMSE={cr}")

        Xe_tr = data.iloc[tr][env].reset_index(drop=True)
        Xe_te = data.iloc[te][env].reset_index(drop=True)
        Xc_tr = data.iloc[tr][crop].reset_index(drop=True)
        Xc_te = data.iloc[te][crop].reset_index(drop=True)

        for kind in ["TWO_STAGE_RIDGE", "TWO_STAGE_XGB"]:
            cfg, bis, bi, tdf = tune_two_stage(Xe_tr, Xc_tr, ytr, gtr, kind, held)
            tune_parts.append(tdf)
            par_rows.append(dict(OUTER_HELDOUT=held, MODEL=kind, BEST_CANDIDATE=bi,
                                 INNER_MACRO_RMSE=bis, BEST_PARAMS=json.dumps(cfg, sort_keys=True)))
            envp, craw, cused, pp = fit_two_stage(Xe_tr, Xc_tr, ytr, gtr, Xe_te, Xc_te, kind, cfg, held)
            met = metrics(yte, pp)
            res_rows.append(dict(**{MUNI: held}, N_TEST=len(yte), MODEL=kind, **met,
                                 INNER_MACRO_RMSE=bis, BEST_CANDIDATE=bi))
            for pid, yy, ep, crw, cu, pred in zip(ids_te, yte, envp, craw, cused, pp):
                pred_rows.append(dict(**{ID: pid, MUNI: held}, MODEL=kind, REAL=float(yy), PRED=float(pred), ERROR=float(pred-yy)))
                comp_rows.append(dict(**{ID: pid, MUNI: held}, MODEL=kind, REAL=float(yy),
                                      ENV_PRED=float(ep), CORRECTION_RAW=float(crw),
                                      CORRECTION_LAMBDA=float(cfg['correction_lambda']),
                                      CORRECTION_USED=float(cu), FINAL_PRED=float(pred),
                                      ENV_ERROR=float(ep-yy), FINAL_ERROR=float(pred-yy)))
            cr = f"{met['CENTERED_RMSE']:.6f}" if np.isfinite(met['CENTERED_RMSE']) else "NA"
            print(f"{kind:20s} inner={bis:.6f} | RMSE={met['RMSE']:.6f} | BIAS={met['BIAS']:+.6f} | cRMSE={cr} | lambda={cfg['correction_lambda']:.2f}")

    results = pd.DataFrame(res_rows)
    preds = pd.DataFrame(pred_rows)
    params = pd.DataFrame(par_rows)
    tuning = pd.concat(tune_parts, ignore_index=True)
    comps = pd.DataFrame(comp_rows)
    summary = summarize(results, preds)

    print("\n" + "=" * 138)
    print("RESULTADOS POR MUNICIPIO — EXP15")
    print("=" * 138)
    print(results.sort_values([MUNI, "RMSE"]).to_string(index=False, float_format=lambda x: f"{x:.6f}"))
    print("\n" + "=" * 138)
    print("RESUMEN MODELOS — TWO-STAGE")
    print("=" * 138)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.6f}"))

    def row(name):
        return summary[summary.MODEL.eq(name)].iloc[0]
    one_r, two_r = row("ONE_STAGE_RIDGE"), row("TWO_STAGE_RIDGE")
    one_x, two_x = row("ONE_STAGE_XGB"), row("TWO_STAGE_XGB")
    base = row("BASE_RIDGE_ALL")
    best = summary.iloc[0]
    dr = float(one_r.MACRO_RMSE_ALL - two_r.MACRO_RMSE_ALL)
    drc = float(one_r.MACRO_RMSE_CORE - two_r.MACRO_RMSE_CORE)
    dx = float(one_x.MACRO_RMSE_ALL - two_x.MACRO_RMSE_ALL)
    dxc = float(one_x.MACRO_RMSE_CORE - two_x.MACRO_RMSE_CORE)
    gain = float(BENCHMARK - best.MACRO_RMSE_ALL)

    print("\n" + "=" * 138)
    print("LECTURA AUTOMÁTICA CONSERVADORA")
    print("=" * 138)
    print(f"BASE_RIDGE_ALL = {base.MACRO_RMSE_ALL:.6f} (sanity vs histórico {BENCHMARK:.6f})")
    print(f"TWO_STAGE_RIDGE vs ONE_STAGE_RIDGE: ALL9 mejora={dr:+.6f}; CORE mejora={drc:+.6f}")
    print(f"TWO_STAGE_XGB vs ONE_STAGE_XGB:     ALL9 mejora={dx:+.6f}; CORE mejora={dxc:+.6f}")
    print(f"Mejor Exp15: {best.MODEL} | ALL9={best.MACRO_RMSE_ALL:.6f} | CORE={best.MACRO_RMSE_CORE:.6f}")
    print(f"Mejora descriptiva vs {BENCHMARK:.6f}: {gain:+.6f}")
    print("TWO_STAGE_RIDGE mejora robustamente." if dr > 0 and drc > 0 else "TWO_STAGE_RIDGE no mejora simultáneamente ALL9 y CORE.")
    print("TWO_STAGE_XGB mejora robustamente." if dx > 0 and dxc > 0 else "TWO_STAGE_XGB no mejora simultáneamente ALL9 y CORE.")
    if best.MACRO_RMSE_CORE - best.MACRO_CENTERED_RMSE_CORE > .10:
        print("Persiste un gap grande RMSE CORE vs Centered-RMSE CORE: sigue habiendo domain shift/calibración territorial.")
    print("Toda mejora es de desarrollo sobre los mismos municipios; no es confirmación externa independiente.")

    results.to_csv(outdir / "02_Resultados_Por_Municipio.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(outdir / "03_Resumen_Modelos.csv", index=False, encoding="utf-8-sig")
    params.to_csv(outdir / "04_Mejores_Hiperparametros.csv", index=False, encoding="utf-8-sig")
    tuning.to_csv(outdir / "05_Tuning_Inner_LOGO.csv", index=False, encoding="utf-8-sig")
    preds.to_csv(outdir / "06_Predicciones_LOGO.csv", index=False, encoding="utf-8-sig")
    comps.to_csv(outdir / "07_Componentes_TwoStage.csv", index=False, encoding="utf-8-sig")
    with open(outdir / "08_Resumen.txt", "w", encoding="utf-8") as f:
        f.write("EXPERIMENTO 15 — TWO-STAGE BIOPHYSICAL\n\n")
        f.write(f"ENV={len(env)}\nCROP_BASE={len(crop_base)}\nTRAJ={len(traj_cols)}\nCROP_TOTAL={len(crop)}\nBASE_ALL={len(base_all)}\nONE_STAGE={len(one)}\n\n")
        f.write("RESUMEN MODELOS\n" + summary.to_string(index=False) + "\n\n")
        f.write(f"TWO_STAGE_RIDGE vs ONE_STAGE_RIDGE ALL9={dr:+.6f} CORE={drc:+.6f}\n")
        f.write(f"TWO_STAGE_XGB vs ONE_STAGE_XGB ALL9={dx:+.6f} CORE={dxc:+.6f}\n")
        f.write(f"BEST={best.MODEL} ALL9={best.MACRO_RMSE_ALL:.6f} CORE={best.MACRO_RMSE_CORE:.6f}\nGAIN_VS_BENCH={gain:+.6f}\n")

    print(f"\nArchivos guardados en:\n{outdir}")
    print("\nPÁSAME:")
    print("  1) conteos ENV/CROP/TRAJ")
    print("  2) RESULTADOS POR MUNICIPIO — EXP15")
    print("  3) RESUMEN MODELOS — TWO-STAGE")
    print("  4) LECTURA AUTOMÁTICA CONSERVADORA")
    print("  5) Si TWO_STAGE gana: 07_Componentes_TwoStage.csv")


if __name__ == "__main__":
    main()
