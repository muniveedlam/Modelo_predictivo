#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
EXPERIMENTO 14 v4 — TRAYECTORIAS TEMPORALES EXPLÍCITAS / MUNICIPALITY-FREE
Reto AgroCebada 2026

HIPÓTESIS
=========
Los Experimentos 12-13 sugieren que:
  1) existe señal biofísica transferible;
  2) XGBoost no supera todavía a Ridge con los resúmenes actuales;
  3) existe fuerte domain shift entre municipios;
  4) seleccionar/reducir columnas estáticas no resolvió el problema.

Este experimento deja de preguntar "qué columna gana" y pregunta:

    ¿la FORMA temporal de la respuesta espectral contiene información
    transferible que los resúmenes actuales no representan explícitamente?

OBJETIVO
========
Construir features de trayectoria por parcela, sensor e índice SIN usar Y:

BASIC:
    NDVI, EVI, LAI, NDWI, MSI, NDDI, EMSI, NDTI, STI

PRO:
    NDVI, EVI, LAI, MSAVI

De la serie temporal por períodos de 10 días se calculan:
    N_PERIODS
    AUC_NORM
    TEMP_MEAN
    TEMP_STD
    PEAK_VALUE
    PEAK_PERIOD
    AMPLITUDE
    EARLY_MED
    MID_MED
    LATE_MED
    RISE_SLOPE
    DECLINE_SLOPE
    FRAC_ABOVE_70PCT_PEAK

Se usan observaciones Abril-Octubre y, por defecto, SAT_YEAR=2025.
Los huecos internos se interpolan linealmente sólo dentro del rango
observado de cada parcela/índice. No se extrapola antes/después.

BASIC:
    si existe una columna de nubosidad, se conservan observaciones <=20%.

PRO:
    si existe nubosidad, también se aplica <=20% para mantener una
    política conservadora y reproducible.

COMPARACIÓN
===========
    GLOBAL_MEAN
    RIDGE_ALL
    RIDGE_TRAJ
    RIDGE_ALL_PLUS_TRAJ
    XGB_ALL
    XGB_TRAJ
    XGB_ALL_PLUS_TRAJ

ALL = las 364 features biofísicas válidas de Exp12/13:
      BASIC + PRO + CLIMATE + TOPO, sin municipio/área/coordenadas.

TRAJ = trayectorias satelitales + CLIMATE + TOPO.
       Se añade contexto climático/topográfico para que el modelo pueda
       interpretar una trayectoria bajo condiciones ambientales distintas.

ALL_PLUS_TRAJ = ALL + nuevas features temporales.

VALIDACIÓN
==========
Nested Leave-One-Municipality-Out (LOGO):

Outer:
    municipio completo retenido.

Inner:
    LOGO dentro de los municipios restantes para tuning.

Municipio se usa SÓLO como GROUP. Nunca entra en X.

Métrica de selección inner:
    Macro-RMSE entre municipios inner-held-out.

MÉTRICAS
========
Primaria de continuidad:
    MACRO_RMSE_ALL9

Diagnóstico:
    MACRO_RMSE_CORE (municipios N>=3)
    POOLED_RMSE
    MACRO_ABS_BIAS
    MACRO_CENTERED_RMSE_CORE
    Spearman within-municipality cuando es calculable.

CRITERIOS DE LECTURA PREDECLARADOS
==================================
A) Valor de trayectoria:
    ALL_PLUS_TRAJ mejora ALL si:
        MacroRMSE_ALL baja > 0
    y se revisa obligatoriamente MacroRMSE_CORE.

B) No linealidad:
    XGB_ALL_PLUS_TRAJ vs RIDGE_ALL_PLUS_TRAJ.

C) Domain shift:
    si CenteredRMSE_CORE << RMSE_CORE, el error continúa dominado
    por calibración entre territorios.

IMPORTANTE
==========
Este experimento sigue siendo desarrollo sobre los mismos municipios.
No es confirmación externa independiente.

DESCUBRIMIENTO DE DATOS CRUDOS
==============================
El script busca automáticamente CSVs de BASIC y PRO/Planet bajo:
    carpeta del script
    DataSet/DATASET_RETO_AGRO_2026 y la carpeta de la fenología

Ignora carpetas de Experimentos/Resultados.

Si tus archivos tienen nombres no detectables, puedes fijarlos manualmente
abajo en MANUAL_BASIC_FILES y MANUAL_PRO_FILES.

Formatos soportados:
  A) largo:
       ID + fecha/periodo + indice + promedio
  B) ancho:
       ID + fecha/periodo + NDVI_promedio + EVI_promedio + ...
  C) un índice por CSV:
       ID + fecha/periodo + promedio
       (el índice se infiere del nombre del archivo)

SALIDAS
=======
02_Trayectorias_Temporales/
    01_Auditoria_All.csv
    02_Auditoria_Raw_Files.csv
    03_Cobertura_Trayectorias.csv
    04_Matriz_Trayectorias_138.csv
    05_Resultados_Por_Municipio.csv
    06_Resumen_Modelos.csv
    07_Mejores_Hiperparametros.csv
    08_Tuning_Inner_LOGO.csv
    09_Predicciones_LOGO.csv
    10_Importancias_XGB.csv
    11_Top_Importancias_XGB.csv
    12_Resumen.txt
"""

from pathlib import Path
import os
import hashlib
import json
import re
import unicodedata
import warnings

import numpy as np
import pandas as pd

from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")


# ======================================================================
# CONFIGURACIÓN
# ======================================================================
ID = "ID_POLIGONO"
MUNI = "Municipio"
Y = "RENDIMIENTO_T_HA"
SET = "CONJUNTO"

SEED = 20261008
SAT_YEAR = 2025
CLOUD_MAX = 20.0
MIN_PERIODS_FOR_SHAPE = 3

# Si el autodiscovery no encuentra tus fuentes, coloca rutas exactas aquí.
# Ejemplo:
# MANUAL_BASIC_FILES = ["/ruta/NDVI_BASIC.csv", "/ruta/EVI_BASIC.csv"]
PHENOLOGY_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = PHENOLOGY_ROOT.parents[2] / "DataSet" / "DATASET_RETO_AGRO_2026"

MANUAL_BASIC_FILES = [
    str(RAW_ROOT / "Conjunto_datos_BASICO_AgroCebada2026.csv")
]
MANUAL_PRO_FILES = [
    str(RAW_ROOT / "Conjunto_datos_PRO_AgroCebada.csv")
]

ALLOWED_BLOCKS = {"BASIC", "PRO", "CLIMATE", "TOPO"}

FORBIDDEN_TOKENS = [
    "municipio", "estado", "area_ha", "log_area",
    "spatial", "coord", "longitude", "latitude",
    "latitud", "longitud", "rendimiento", "yield",
    "target", "pred", "prediction", "error",
    "resid", "delta",
]

BASIC_INDICES = [
    "NDVI", "EVI", "LAI",
    "NDWI", "MSI", "NDDI", "EMSI",
    "NDTI", "STI",
]

PRO_INDICES = [
    "NDVI", "EVI", "LAI", "MSAVI",
]

TRAJ_STATS = [
    "N_PERIODS",
    "AUC_NORM",
    "TEMP_MEAN",
    "TEMP_STD",
    "PEAK_VALUE",
    "PEAK_PERIOD",
    "AMPLITUDE",
    "EARLY_MED",
    "MID_MED",
    "LATE_MED",
    "RISE_SLOPE",
    "DECLINE_SLOPE",
    "FRAC_ABOVE_70PCT_PEAK",
]

# Ridge: mismo espíritu que Exp12-13.
RIDGE_GRID = [
    {"alpha": a}
    for a in [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]
]

# Grid pequeño. Mismo grid para ALL / TRAJ / ALL_PLUS_TRAJ.
XGB_GRID = [
    {
        "n_estimators": 250, "learning_rate": 0.03,
        "max_depth": 1, "min_child_weight": 12,
        "gamma": 0.25, "subsample": 0.80,
        "colsample_bytree": 0.60,
        "reg_alpha": 2.0, "reg_lambda": 30.0,
    },
    {
        "n_estimators": 250, "learning_rate": 0.05,
        "max_depth": 1, "min_child_weight": 6,
        "gamma": 0.05, "subsample": 0.80,
        "colsample_bytree": 0.85,
        "reg_alpha": 0.5, "reg_lambda": 12.0,
    },
    {
        "n_estimators": 250, "learning_rate": 0.03,
        "max_depth": 2, "min_child_weight": 12,
        "gamma": 0.25, "subsample": 0.80,
        "colsample_bytree": 0.60,
        "reg_alpha": 2.0, "reg_lambda": 30.0,
    },
    {
        "n_estimators": 250, "learning_rate": 0.05,
        "max_depth": 2, "min_child_weight": 6,
        "gamma": 0.05, "subsample": 0.80,
        "colsample_bytree": 0.85,
        "reg_alpha": 0.5, "reg_lambda": 12.0,
    },
    {
        "n_estimators": 250, "learning_rate": 0.03,
        "max_depth": 3, "min_child_weight": 12,
        "gamma": 0.25, "subsample": 0.80,
        "colsample_bytree": 0.60,
        "reg_alpha": 2.0, "reg_lambda": 30.0,
    },
    {
        "n_estimators": 250, "learning_rate": 0.05,
        "max_depth": 3, "min_child_weight": 6,
        "gamma": 0.05, "subsample": 0.80,
        "colsample_bytree": 0.85,
        "reg_alpha": 0.5, "reg_lambda": 12.0,
    },
    {
        "n_estimators": 400, "learning_rate": 0.02,
        "max_depth": 2, "min_child_weight": 10,
        "gamma": 0.10, "subsample": 0.90,
        "colsample_bytree": 0.70,
        "reg_alpha": 1.0, "reg_lambda": 20.0,
    },
    {
        "n_estimators": 350, "learning_rate": 0.03,
        "max_depth": 3, "min_child_weight": 8,
        "gamma": 0.10, "subsample": 0.90,
        "colsample_bytree": 0.70,
        "reg_alpha": 1.0, "reg_lambda": 20.0,
    },
]


# ======================================================================
# UTILIDADES GENERALES
# ======================================================================
def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def stable_seed(*parts):
    raw = "|".join(map(str, parts)).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def trapezoid_integral(y, x):
    """
    Integral trapezoidal compatible con NumPy nuevo y antiguo.

    NumPy moderno usa np.trapezoid(); algunas versiones ya no exponen
    np.trapz(). Como último fallback, calculamos la regla trapezoidal
    directamente para no depender de la versión instalada.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)

    if len(y) < 2:
        return 0.0

    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(y, x))

    dx = np.diff(x)
    return float(
        np.sum(
            0.5 * (y[:-1] + y[1:]) * dx
        )
    )


def mae(y_true, y_pred):
    return float(mean_absolute_error(y_true, y_pred))


def bias(y_true, y_pred):
    return float(np.mean(np.asarray(y_pred, float) - np.asarray(y_true, float)))


def centered_rmse(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    if len(y_true) < 2:
        return np.nan
    e = y_pred - y_true
    return float(np.sqrt(np.mean((e - e.mean()) ** 2)))


def spearman_within(y_true, y_pred):
    yt = pd.Series(np.asarray(y_true, float))
    yp = pd.Series(np.asarray(y_pred, float))
    if len(yt) < 3 or yt.nunique() < 2 or yp.nunique() < 2:
        return np.nan
    return float(yt.rank().corr(yp.rank(), method="pearson"))


def is_forbidden_feature(feature):
    nf = norm_name(feature)
    return any(tok in nf for tok in FORBIDDEN_TOKENS)


def find_col(columns, candidates):
    mapping = {norm_name(c): c for c in columns}
    for cand in candidates:
        if cand in mapping:
            return mapping[cand]
    return None


def find_file(base_dirs, names):
    for b in base_dirs:
        for n in names:
            p = b / n
            if p.is_file():
                return p
    return None


# ======================================================================
# LOCALIZAR MASTER + EXP09
# ======================================================================
def locate_core():
    root = PHENOLOGY_ROOT
    raw_root = RAW_ROOT
    master = root / "Maestro_Cebada_197.csv"
    matrix = root / "01_Diagnostico_Modelo" / "01_Matriz_Features_138.csv"
    inventory = root / "01_Diagnostico_Modelo" / "02_Inventario_Features.csv"
    missing = [str(path) for path in (master, matrix, inventory, raw_root) if not path.exists()]
    if missing:
        raise FileNotFoundError("No encuentro las rutas de entrada:\n  - " + "\n  - ".join(missing))
    return master, matrix, inventory, [raw_root]


# ======================================================================
# ALL BIOPHYS DEL EXP12/13
# ======================================================================
def make_all_feature_set(inventory, feature_matrix):
    inv = inventory.copy()
    inv["FEATURE"] = inv["FEATURE"].astype(str)
    inv["BLOCK"] = inv["BLOCK"].astype(str).str.upper()
    inv["PRESENT"] = inv["FEATURE"].isin(feature_matrix.columns)
    inv["BLOCK_ALLOWED"] = inv["BLOCK"].isin(ALLOWED_BLOCKS)
    inv["FORBIDDEN_NAME"] = inv["FEATURE"].map(is_forbidden_feature)
    inv["IN_ALL"] = (
        inv["PRESENT"]
        & inv["BLOCK_ALLOWED"]
        & ~inv["FORBIDDEN_NAME"]
    )

    def why(r):
        if r["IN_ALL"]:
            return "INCLUDED_ALL_BIOPHYS"
        if not r["PRESENT"]:
            return "EXCLUDED_MISSING"
        if not r["BLOCK_ALLOWED"]:
            return "EXCLUDED_BLOCK"
        if r["FORBIDDEN_NAME"]:
            return "EXCLUDED_FORBIDDEN_NAME"
        return "EXCLUDED_OTHER"

    inv["REASON"] = inv.apply(why, axis=1)
    cols = inv.loc[inv["IN_ALL"], "FEATURE"].tolist()
    return cols, inv


# ======================================================================
# DESCUBRIR CSVs CRUDOS
# ======================================================================
def candidate_csvs(bases):
    """
    v3: búsqueda robusta, sin symlinks y sin depender de que el nombre
    contenga BASIC/PRO. Se priorizan explícitamente los archivos limpios
    que ya existen en Satelite_AbrOct_Limpio.
    """
    preferred_exact = [
        Path("/Satelite_AbrOct_Limpio/BASIC_10dias_AbrOct_WIDE.csv"),
        Path("/Satelite_AbrOct_Limpio/BASIC_10dias_AbrOct.csv"),
        Path("/Satelite_AbrOct_Limpio/PRO_10dias_AbrOct_WIDE.csv"),
        Path("/Satelite_AbrOct_Limpio/PRO_10dias_AbrOct.csv"),
    ]

    seen = set()
    out = []

    for p in preferred_exact:
        if p.is_file():
            ps = str(p.absolute())
            seen.add(ps)
            out.append(p)

    skip_tokens = [
        "experimento_", "resultados", "predicciones",
        "resumen", "submission", "salida", "__pycache__",
        "analisis_", "forense_",
    ]

    hard_skip_names = {
        "proc", "sys", "dev", "run",
        ".git", ".idea", ".venv", "venv",
        "__pycache__", "node_modules",
    }

    def _onerror(err):
        return None

    for base in bases:
        base = Path(base)
        try:
            if not base.exists() or not base.is_dir():
                continue
        except OSError:
            continue

        try:
            walker = os.walk(
                base,
                topdown=True,
                onerror=_onerror,
                followlinks=False,
            )

            for root, dirnames, filenames in walker:
                root_path = Path(root)

                kept = []
                for d in dirnames:
                    nd = norm_name(d)
                    if d in hard_skip_names or d.startswith("."):
                        continue
                    if any(tok in nd for tok in skip_tokens):
                        continue
                    child = root_path / d
                    try:
                        if child.is_symlink():
                            continue
                    except OSError:
                        continue
                    kept.append(d)

                dirnames[:] = kept

                for filename in filenames:
                    if not filename.lower().endswith(".csv"):
                        continue

                    p = root_path / filename

                    try:
                        ps = str(p.absolute())
                    except OSError:
                        ps = str(p)

                    if ps in seen:
                        continue

                    npth = norm_name(ps)

                    if any(tok in npth for tok in skip_tokens):
                        continue

                    # Evitar core/resultados conocidos.
                    nf = norm_name(filename)
                    if any(tok in nf for tok in [
                        "master_cebada_197", "cebada_197",
                        "matriz_features_138", "inventario_features",
                        "splits_50", "auditoria_raw_files",
                    ]):
                        continue

                    # El raw satelital debe al menos parecer satelital.
                    if not any(tok in npth for tok in [
                        "basic", "pro", "planet", "sentinel",
                        "ndvi", "evi", "lai", "msavi",
                        "ndwi", "msi", "nddi", "emsi",
                        "ndti", "sti", "satelite",
                    ]):
                        continue

                    seen.add(ps)
                    out.append(p)

        except (PermissionError, OSError):
            continue

    return out


def robust_read_csv(path):
    errors = []

    for enc in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            df = pd.read_csv(
                path,
                encoding=enc,
                low_memory=False,
            )
            if len(df.columns) == 1:
                try:
                    df2 = pd.read_csv(
                        path,
                        encoding=enc,
                        sep=None,
                        engine="python",
                    )
                    if len(df2.columns) > len(df.columns):
                        return df2, f"encoding={enc};sep=auto"
                except Exception:
                    pass
            return df, f"encoding={enc};sep=comma"
        except Exception as e:
            errors.append(
                f"{enc}/comma:{type(e).__name__}"
            )

        try:
            df = pd.read_csv(
                path,
                encoding=enc,
                sep=None,
                engine="python",
            )
            return df, f"encoding={enc};sep=auto"
        except Exception as e:
            errors.append(
                f"{enc}/auto:{type(e).__name__}"
            )

    raise RuntimeError(
        " | ".join(errors[-6:])
    )


def infer_sensor_from_path(path):
    n = norm_name(str(path))

    # PRO primero para evitar "BASIC_PRO" ambiguo.
    if (
        "planet" in n
        or re.search(r"(^|_)pro(_|$)", n)
    ):
        return "PRO"

    if (
        "basic" in n
        or "sentinel" in n
    ):
        return "BASIC"

    return None


def infer_sensor_from_dataframe(df):
    cols = list(df.columns)

    sensor_col = find_col(
        cols,
        [
            "sensor", "satelite", "satellite",
            "plataforma", "platform", "fuente",
            "source", "provider", "proveedor",
        ],
    )

    if sensor_col is not None:
        vals = (
            df[sensor_col]
            .dropna()
            .astype(str)
            .map(norm_name)
            .head(200)
            .tolist()
        )
        joined = " ".join(vals)

        if "planet" in joined:
            return "PRO"

        if "sentinel" in joined:
            return "BASIC"

    norm_cols = [norm_name(c) for c in cols]

    # MSAVI es característico del bloque PRO del proyecto.
    if any(
        re.search(r"(^|_)msavi(_|$)", c)
        for c in norm_cols
    ):
        return "PRO"

    # Índices presentes sólo en BASIC dentro de este proyecto.
    basic_unique = [
        "ndwi", "msi", "nddi", "emsi",
        "ndti", "sti", "fapar", "sav",
        "endwi", "enddi", "vi6t", "srndi",
    ]

    if any(
        any(
            re.search(
                rf"(^|_){re.escape(tok)}(_|$)",
                c,
            )
            for tok in basic_unique
        )
        for c in norm_cols
    ):
        return "BASIC"

    return None


def infer_index_from_path(path, allowed_indices):
    n = norm_name(path.stem)
    for idx in allowed_indices:
        token = idx.lower()
        if re.search(
            rf"(^|_){re.escape(token)}(_|$)",
            n,
        ):
            return idx
    return None


def derive_period_from_date(series):
    # dayfirst=True ayuda con fechas dd/mm/yyyy usadas comúnmente en MX.
    d = pd.to_datetime(
        series,
        errors="coerce",
        dayfirst=True,
    )

    if SAT_YEAR is not None:
        d = d.where(
            d.dt.year.eq(SAT_YEAR)
        )

    month = d.dt.month
    day = d.dt.day

    dekad = np.where(
        day <= 10,
        1,
        np.where(day <= 20, 2, 3),
    )

    period = (
        (month - 4) * 3 + dekad
    )

    period = pd.Series(
        period,
        index=series.index,
        dtype="float64",
    )

    return period.where(
        month.between(4, 10)
    )


def parse_period_label(value):
    """
    Acepta:
      1..21 / 0..20
      P1, periodo_1, decena_1, dekad_1
      abr1, abril_1, may2, junio3, etc.
      YYYY-MM-DD / dd/mm/YYYY
    """
    if pd.isna(value):
        return np.nan

    # Numérico directo.
    try:
        x = float(value)
        if np.isfinite(x):
            if 1 <= x <= 21:
                return float(x)
            if 0 <= x <= 20:
                return float(x + 1)
    except Exception:
        pass

    raw = str(value).strip()
    n = norm_name(raw)

    m = re.search(
        r"(?:periodo|period|p|decena|dekad|dekada)_?0?([1-9]|1\d|2[01])(?:_|$)",
        n,
    )
    if m:
        return float(int(m.group(1)))

    month_map = {
        "abr": 4, "abril": 4, "apr": 4, "april": 4,
        "may": 5, "mayo": 5,
        "jun": 6, "junio": 6, "june": 6,
        "jul": 7, "julio": 7, "july": 7,
        "ago": 8, "agosto": 8, "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "septiembre": 9, "september": 9,
        "oct": 10, "octubre": 10, "october": 10,
    }

    for name, month in month_map.items():
        m = re.search(
            rf"(?:^|_){name}_?([123])(?:_|$)",
            n,
        )
        if m:
            dekad = int(m.group(1))
            return float(
                (month - 4) * 3 + dekad
            )

    # Intentar fecha.
    try:
        d = pd.to_datetime(
            [raw],
            errors="coerce",
            dayfirst=True,
        )[0]

        if pd.notna(d):
            if SAT_YEAR is not None and d.year != SAT_YEAR:
                return np.nan
            if 4 <= d.month <= 10:
                dekad = (
                    1 if d.day <= 10
                    else 2 if d.day <= 20
                    else 3
                )
                return float(
                    (d.month - 4) * 3 + dekad
                )
    except Exception:
        pass

    return np.nan


def normalize_period(series):
    return series.map(
        parse_period_label
    ).astype(float)


def fuzzy_id_col(cols):
    exact = find_col(
        cols,
        [
            "id_poligono", "id_poligon",
            "id_parcela", "parcela_id", "id",
        ],
    )

    if exact is not None:
        return exact

    for c in cols:
        nc = norm_name(c)
        if (
            nc.startswith("id_")
            and (
                "polig" in nc
                or "parcela" in nc
            )
        ):
            return c

    return None


def fuzzy_period_col(cols):
    exact = find_col(
        cols,
        [
            "periodo", "period",
            "periodo_10d", "periodo10d",
            "periodo_10_dias", "periodo_10dias",
            "periodo10dias", "decena",
            "dekad", "dekada", "period_10d",
        ],
    )

    if exact is not None:
        return exact

    for c in cols:
        nc = norm_name(c)
        if any(
            tok in nc
            for tok in [
                "periodo", "period",
                "decena", "dekad",
            ]
        ):
            return c

    return None


def fuzzy_date_col(cols):
    exact = find_col(
        cols,
        [
            "fecha", "date", "datetime",
            "timestamp", "acquisition_date",
            "fecha_adquisicion",
            "fecha_imagen", "image_date",
        ],
    )

    if exact is not None:
        return exact

    for c in cols:
        nc = norm_name(c)
        if (
            "fecha" in nc
            or nc.endswith("_date")
            or nc.startswith("date_")
        ):
            return c

    return None


def parse_superwide_columns(
    df,
    path,
    sensor,
    id_col,
    cloud_col,
):
    """
    Soporta una fila por parcela con columnas que codifican índice+periodo,
    por ejemplo:
      NDVI_promedio_P01
      NDVI_PROMEDIO_PERIODO_1
      P01_NDVI_promedio
      NDVI_promedio_Abr1
    """
    allowed = (
        BASIC_INDICES
        if sensor == "BASIC"
        else PRO_INDICES
    )

    extracted = []

    for c in df.columns:
        if c == id_col:
            continue

        nc = norm_name(c)

        idx = None
        for candidate in allowed:
            tok = candidate.lower()
            if re.search(
                rf"(^|_){re.escape(tok)}(_|$)",
                nc,
            ):
                idx = candidate
                break

        if idx is None:
            continue

        # Preferimos columnas de promedio/mean si el nombre trae estadístico.
        stat_tokens = [
            "promedio", "mean", "media",
            "avg", "average",
        ]

        # Si existe explícitamente std/max/min, no usarla como trayectoria de mean.
        if any(
            re.search(
                rf"(^|_){tok}(_|$)",
                nc,
            )
            for tok in [
                "std", "sd", "desv",
                "max", "min",
            ]
        ):
            continue

        # Extraer periodo de tokens conocidos.
        period = parse_period_label(nc)

        if not np.isfinite(period):
            # Buscar P01 en cualquier parte.
            m = re.search(
                r"(?:^|_)p0?([1-9]|1\d|2[01])(?:_|$)",
                nc,
            )
            if m:
                period = float(
                    int(m.group(1))
                )

        if not np.isfinite(period):
            # periodo_1 etc.
            m = re.search(
                r"(?:periodo|period|decena|dekad|dekada)_?0?([1-9]|1\d|2[01])(?:_|$)",
                nc,
            )
            if m:
                period = float(
                    int(m.group(1))
                )

        if not np.isfinite(period):
            # Mes-decena embebido.
            month_patterns = {
                4: ["abr", "abril", "apr", "april"],
                5: ["may", "mayo"],
                6: ["jun", "junio", "june"],
                7: ["jul", "julio", "july"],
                8: ["ago", "agosto", "aug", "august"],
                9: ["sep", "sept", "septiembre", "september"],
                10: ["oct", "octubre", "october"],
            }

            for month, names in month_patterns.items():
                hit = None
                for name in names:
                    mm = re.search(
                        rf"(?:^|_){name}_?([123])(?:_|$)",
                        nc,
                    )
                    if mm:
                        hit = int(mm.group(1))
                        break
                if hit is not None:
                    period = float(
                        (month - 4) * 3 + hit
                    )
                    break

        if not np.isfinite(period):
            continue

        values = pd.to_numeric(
            df[c],
            errors="coerce",
        )

        if cloud_col is not None:
            cloud = pd.to_numeric(
                df[cloud_col],
                errors="coerce",
            )
        else:
            cloud = pd.Series(
                np.nan,
                index=df.index,
                dtype=float,
            )

        extracted.append(
            pd.DataFrame({
                ID: (
                    df[id_col]
                    .astype(str)
                    .str.strip()
                ),
                "SENSOR": sensor,
                "INDEX": idx,
                "PERIOD": float(period),
                "VALUE": values,
                "CLOUD": cloud,
                "SOURCE_FILE": str(path),
            })
        )

    if not extracted:
        return pd.DataFrame()

    return pd.concat(
        extracted,
        ignore_index=True,
    )


def inspect_raw_file(path, sensor_hint=None):
    """
    v3: parser amplio.
    Devuelve long_df + auditoría rica con columnas detectadas.
    """
    audit = {
        "FILE": str(path),
        "SENSOR_HINT": sensor_hint,
        "SENSOR_USED": "",
        "STATUS": "SKIPPED",
        "ROWS_RAW": np.nan,
        "ROWS_EXTRACTED": 0,
        "FORMAT": "",
        "ID_COL": "",
        "PERIOD_COL": "",
        "DATE_COL": "",
        "CLOUD_COL": "",
        "READ_INFO": "",
        "N_COLUMNS": np.nan,
        "COLUMNS_SAMPLE": "",
        "NOTE": "",
    }

    try:
        df, read_info = robust_read_csv(path)
    except Exception as e:
        audit["NOTE"] = (
            f"READ_ERROR: {e}"
        )
        return pd.DataFrame(), audit

    audit["READ_INFO"] = read_info
    audit["ROWS_RAW"] = len(df)
    audit["N_COLUMNS"] = len(df.columns)
    audit["COLUMNS_SAMPLE"] = " | ".join(
        map(str, list(df.columns)[:20])
    )

    if len(df) == 0:
        audit["NOTE"] = "EMPTY"
        return pd.DataFrame(), audit

    cols = list(df.columns)

    sensor = sensor_hint
    if sensor is None:
        sensor = infer_sensor_from_path(path)
    if sensor is None:
        sensor = infer_sensor_from_dataframe(df)

    if sensor not in {"BASIC", "PRO"}:
        audit["NOTE"] = "SENSOR_NOT_IDENTIFIED"
        return pd.DataFrame(), audit

    audit["SENSOR_USED"] = sensor

    id_col = fuzzy_id_col(cols)
    audit["ID_COL"] = (
        "" if id_col is None
        else str(id_col)
    )

    if id_col is None:
        audit["NOTE"] = "NO_ID_COLUMN"
        return pd.DataFrame(), audit

    period_col = fuzzy_period_col(cols)
    date_col = fuzzy_date_col(cols)

    audit["PERIOD_COL"] = (
        "" if period_col is None
        else str(period_col)
    )
    audit["DATE_COL"] = (
        "" if date_col is None
        else str(date_col)
    )

    cloud_col = find_col(
        cols,
        [
            "porcentaje_nubosidad",
            "nubosidad", "cloud",
            "cloud_pct", "cloud_percent",
            "cloud_percentage",
        ],
    )

    # Fuzzy cloud.
    if cloud_col is None:
        for c in cols:
            nc = norm_name(c)
            if (
                "nubos" in nc
                or "cloud" in nc
            ):
                cloud_col = c
                break

    audit["CLOUD_COL"] = (
        "" if cloud_col is None
        else str(cloud_col)
    )

    index_col = find_col(
        cols,
        [
            "indice", "index_name",
            "indice_vegetacion",
            "spectral_index",
            "variable",
        ],
    )

    generic_mean = find_col(
        cols,
        [
            "promedio", "mean",
            "media", "avg", "average",
        ],
    )

    allowed = (
        BASIC_INDICES
        if sensor == "BASIC"
        else PRO_INDICES
    )

    extracted = []

    # ==============================================================
    # CASO A: dataset fila-a-fila con columna periodo/fecha.
    # ==============================================================
    period = None

    if period_col is not None:
        period = normalize_period(
            df[period_col]
        )
    elif date_col is not None:
        period = derive_period_from_date(
            df[date_col]
        )

    if period is not None:
        if cloud_col is not None:
            cloud = pd.to_numeric(
                df[cloud_col],
                errors="coerce",
            )
        else:
            cloud = pd.Series(
                np.nan,
                index=df.index,
                dtype=float,
            )

        # Largo: INDEX + PROMEDIO.
        if (
            index_col is not None
            and generic_mean is not None
        ):
            idx_values = (
                df[index_col]
                .astype(str)
                .str.upper()
                .str.strip()
            )

            # Limpiar nombres como NDVI_PROMEDIO -> NDVI.
            idx_clean = []
            for v in idx_values:
                nv = norm_name(v)
                match = None
                for candidate in allowed:
                    tok = candidate.lower()
                    if re.search(
                        rf"(^|_){re.escape(tok)}(_|$)",
                        nv,
                    ):
                        match = candidate
                        break
                idx_clean.append(
                    match if match else v
                )

            tmp = pd.DataFrame({
                ID: (
                    df[id_col]
                    .astype(str)
                    .str.strip()
                ),
                "SENSOR": sensor,
                "INDEX": idx_clean,
                "PERIOD": period,
                "VALUE": pd.to_numeric(
                    df[generic_mean],
                    errors="coerce",
                ),
                "CLOUD": cloud,
                "SOURCE_FILE": str(path),
            })

            tmp = tmp[
                tmp["INDEX"].isin(allowed)
            ]

            if len(tmp):
                extracted.append(tmp)
                audit["FORMAT"] = "LONG_INDEX"

        # Wide por periodo: NDVI_promedio, EVI_promedio...
        for idx in allowed:
            idxn = idx.lower()
            candidates = []

            for c in cols:
                nc = norm_name(c)

                has_idx = bool(
                    re.search(
                        rf"(^|_){re.escape(idxn)}(_|$)",
                        nc,
                    )
                )

                has_mean = any(
                    tok in nc
                    for tok in [
                        "promedio", "mean",
                        "media", "avg",
                        "average",
                    ]
                )

                # También aceptar columna exactamente NDVI/EVI/etc.
                if (
                    has_idx
                    and (
                        has_mean
                        or nc == idxn
                    )
                ):
                    # excluir std/max/min
                    if any(
                        re.search(
                            rf"(^|_){tok}(_|$)",
                            nc,
                        )
                        for tok in [
                            "std", "sd", "desv",
                            "max", "min",
                        ]
                    ):
                        continue
                    candidates.append(c)

            if candidates:
                candidates = sorted(
                    candidates,
                    key=lambda c: (
                        0
                        if norm_name(c) in {
                            idxn,
                            f"{idxn}_promedio",
                            f"{idxn}_mean",
                            f"{idxn}_media",
                            f"{idxn}_avg",
                        }
                        else 1,
                        len(c),
                    ),
                )

                c = candidates[0]

                tmp = pd.DataFrame({
                    ID: (
                        df[id_col]
                        .astype(str)
                        .str.strip()
                    ),
                    "SENSOR": sensor,
                    "INDEX": idx,
                    "PERIOD": period,
                    "VALUE": pd.to_numeric(
                        df[c],
                        errors="coerce",
                    ),
                    "CLOUD": cloud,
                    "SOURCE_FILE": str(path),
                })

                extracted.append(tmp)

                audit["FORMAT"] = (
                    audit["FORMAT"] + "+WIDE_ROWS"
                    if audit["FORMAT"]
                    else "WIDE_ROWS"
                )

        # Un índice por archivo.
        if (
            not extracted
            and generic_mean is not None
        ):
            inferred_idx = infer_index_from_path(
                path,
                allowed,
            )

            if inferred_idx is not None:
                tmp = pd.DataFrame({
                    ID: (
                        df[id_col]
                        .astype(str)
                        .str.strip()
                    ),
                    "SENSOR": sensor,
                    "INDEX": inferred_idx,
                    "PERIOD": period,
                    "VALUE": pd.to_numeric(
                        df[generic_mean],
                        errors="coerce",
                    ),
                    "CLOUD": cloud,
                    "SOURCE_FILE": str(path),
                })

                extracted.append(tmp)
                audit["FORMAT"] = (
                    "ONE_INDEX_PER_FILE"
                )

    # ==============================================================
    # CASO B: super-wide. Periodo codificado en nombre de columna.
    # ==============================================================
    if not extracted:
        superwide = parse_superwide_columns(
            df=df,
            path=path,
            sensor=sensor,
            id_col=id_col,
            cloud_col=cloud_col,
        )

        if len(superwide):
            extracted.append(
                superwide
            )
            audit["FORMAT"] = (
                "SUPERWIDE_PERIOD_IN_COLUMN"
            )

    if not extracted:
        audit["NOTE"] = (
            "SUPPORTED_SCHEMA_NOT_FOUND"
        )
        return pd.DataFrame(), audit

    out = pd.concat(
        extracted,
        ignore_index=True,
    )

    out["PERIOD"] = pd.to_numeric(
        out["PERIOD"],
        errors="coerce",
    )

    out["VALUE"] = pd.to_numeric(
        out["VALUE"],
        errors="coerce",
    )

    out["CLOUD"] = pd.to_numeric(
        out["CLOUD"],
        errors="coerce",
    )

    # Sólo período agronómico definido.
    out = out[
        out["PERIOD"].between(1, 21)
        & out["VALUE"].notna()
        & out[ID].notna()
    ].copy()

    out[ID] = (
        out[ID]
        .astype(str)
        .str.strip()
    )

    out = out[
        out[ID].ne("")
        & ~out[ID].eq("nan")
    ]

    # Evitar dobles extracciones del mismo archivo.
    out = out.drop_duplicates(
        subset=[
            ID, "SENSOR",
            "INDEX", "PERIOD",
            "VALUE", "SOURCE_FILE",
        ]
    )

    has_cloud = (
        out["CLOUD"]
        .notna()
        .any()
    )

    if has_cloud:
        out = out[
            out["CLOUD"].isna()
            | out["CLOUD"].le(
                CLOUD_MAX
            )
        ].copy()

    audit["STATUS"] = (
        "PARSED"
        if len(out)
        else "NO_VALID_ROWS"
    )

    audit["ROWS_EXTRACTED"] = len(out)

    audit["NOTE"] = (
        f"CLOUD_FILTER<={CLOUD_MAX}"
        if has_cloud
        else "NO_CLOUD_INFO"
    )

    return out, audit


def discover_raw(bases):
    """
    v3:
      1) inspecciona todos los candidatos;
      2) guarda auditoría completa;
      3) elige UNA fuente principal por sensor para evitar mezclar
         backups/derivados;
      4) prioriza Satelite_AbrOct_Limpio y archivos WIDE;
      5) dentro de esa prioridad elige el que produzca más observaciones.
    """
    audit_rows = []
    parsed = []

    manual = []

    for p in MANUAL_BASIC_FILES:
        manual.append(
            (Path(p), "BASIC")
        )

    for p in MANUAL_PRO_FILES:
        manual.append(
            (Path(p), "PRO")
        )

    if manual:
        candidates = manual
    else:
        candidates = []

        for p in candidate_csvs(bases):
            candidates.append(
                (
                    p,
                    infer_sensor_from_path(p),
                )
            )

    for p, sensor_hint in candidates:
        if not p.is_file():
            audit_rows.append({
                "FILE": str(p),
                "SENSOR_HINT": sensor_hint,
                "SENSOR_USED": "",
                "STATUS": "MISSING_FILE",
                "ROWS_RAW": np.nan,
                "ROWS_EXTRACTED": 0,
                "FORMAT": "",
                "ID_COL": "",
                "PERIOD_COL": "",
                "DATE_COL": "",
                "CLOUD_COL": "",
                "READ_INFO": "",
                "N_COLUMNS": np.nan,
                "COLUMNS_SAMPLE": "",
                "NOTE": "",
            })
            continue

        long_df, audit = inspect_raw_file(
            p,
            sensor_hint=sensor_hint,
        )

        audit_rows.append(audit)

        if len(long_df):
            parsed.append(
                (
                    p,
                    audit["SENSOR_USED"],
                    long_df,
                    audit,
                )
            )

    audit_df = pd.DataFrame(
        audit_rows
    )

    if not parsed:
        # Guardar auditoría directamente aquí para que nunca se pierdan
        # las razones del fallo.
        try:
            outdir = PHENOLOGY_ROOT / "02_Trayectorias_Temporales"
            outdir.mkdir(
                parents=True,
                exist_ok=True,
            )
            audit_df.to_csv(
                outdir
                / "02_Auditoria_Raw_Files.csv",
                index=False,
                encoding="utf-8-sig",
            )
        except Exception:
            pass

        raise RuntimeError(
            "No pude construir series temporales BASIC/PRO.\n"
            "La v3 dejó una auditoría detallada con columnas y motivo "
            "de descarte en 02_Auditoria_Raw_Files.csv."
        )

    # --------------------------------------------------------------
    # Elegir una fuente por sensor.
    # --------------------------------------------------------------
    selected_parts = []

    for sensor in ["BASIC", "PRO"]:
        options = [
            x for x in parsed
            if x[1] == sensor
        ]

        if not options:
            continue

        def source_score(item):
            p, _, long_df, audit = item
            npth = norm_name(str(p))

            score = 0

            if "satelite_abroct_limpio" in npth:
                score += 1_000_000

            if "wide" in npth:
                score += 100_000

            if "10dias_abroct" in npth:
                score += 50_000

            # Cobertura por parcela/índice/período.
            score += int(
                long_df[
                    [ID, "INDEX", "PERIOD"]
                ]
                .drop_duplicates()
                .shape[0]
            )

            return score

        options = sorted(
            options,
            key=source_score,
            reverse=True,
        )

        selected = options[0]

        p, _, long_df, audit = selected

        selected_parts.append(
            long_df
        )

        # Marcar auditoría.
        mask = (
            audit_df["FILE"]
            .astype(str)
            .eq(str(p))
        )

        audit_df.loc[
            mask,
            "STATUS",
        ] = "SELECTED_PRIMARY"

        # Los demás parsed quedan explícitamente como no seleccionados.
        other_paths = [
            str(x[0])
            for x in options[1:]
        ]

        if other_paths:
            mask_other = (
                audit_df["FILE"]
                .astype(str)
                .isin(other_paths)
                & audit_df["STATUS"].eq(
                    "PARSED"
                )
            )

            audit_df.loc[
                mask_other,
                "STATUS",
            ] = "PARSED_NOT_SELECTED"

    if not selected_parts:
        raise RuntimeError(
            "Hay archivos parseables, pero no pude seleccionar "
            "una fuente BASIC/PRO válida."
        )

    raw = pd.concat(
        selected_parts,
        ignore_index=True,
    )

    raw = raw.drop_duplicates(
        subset=[
            ID, "SENSOR",
            "INDEX", "PERIOD",
            "VALUE",
        ]
    )

    period_df = (
        raw.groupby(
            [
                ID, "SENSOR",
                "INDEX", "PERIOD",
            ],
            as_index=False,
        )["VALUE"]
        .median()
    )

    return period_df, audit_df


# ======================================================================
# FEATURE ENGINEERING TEMPORAL
# ======================================================================
def slope_ols(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x = x[ok]
    y = y[ok]
    if len(x) < 2 or np.unique(x).size < 2:
        return np.nan
    return float(np.polyfit(x, y, 1)[0])


def trajectory_features_one(x_period, y_value):
    s = pd.Series(
        np.asarray(y_value, float),
        index=np.asarray(x_period, int),
    ).groupby(level=0).median()

    s = s.sort_index()
    s = s[np.isfinite(s.values)]

    if len(s) == 0:
        return {k: np.nan for k in TRAJ_STATS}

    n_periods = int(len(s))
    x_obs = s.index.to_numpy(dtype=float)
    y_obs = s.to_numpy(dtype=float)

    # Interpolación únicamente dentro del rango observado.
    grid = np.arange(int(x_obs.min()), int(x_obs.max()) + 1, dtype=float)
    if len(x_obs) >= 2:
        y_grid = np.interp(grid, x_obs, y_obs)
    else:
        grid = x_obs.copy()
        y_grid = y_obs.copy()

    peak_i = int(np.nanargmax(y_grid))
    peak_value = float(y_grid[peak_i])
    peak_period = float(grid[peak_i])

    min_value = float(np.nanmin(y_grid))
    amp = peak_value - min_value

    if len(grid) >= 2 and grid[-1] > grid[0]:
        auc = trapezoid_integral(y_grid, grid)
        auc_norm = auc / float(grid[-1] - grid[0])
    else:
        auc_norm = float(y_grid[0])

    def med_window(lo, hi):
        m = (grid >= lo) & (grid <= hi)
        if not np.any(m):
            return np.nan
        return float(np.nanmedian(y_grid[m]))

    early = med_window(1, 7)
    mid = med_window(8, 14)
    late = med_window(15, 21)

    if n_periods >= MIN_PERIODS_FOR_SHAPE:
        pre = grid <= peak_period
        post = grid >= peak_period
        rise = slope_ols(grid[pre], y_grid[pre]) if pre.sum() >= 2 else np.nan
        decline = slope_ols(grid[post], y_grid[post]) if post.sum() >= 2 else np.nan
    else:
        rise = np.nan
        decline = np.nan

    threshold = 0.70 * peak_value
    frac_above = float(np.mean(y_grid >= threshold)) if len(y_grid) else np.nan

    return {
        "N_PERIODS": float(n_periods),
        "AUC_NORM": auc_norm,
        "TEMP_MEAN": float(np.nanmean(y_grid)),
        "TEMP_STD": float(np.nanstd(y_grid, ddof=0)),
        "PEAK_VALUE": peak_value,
        "PEAK_PERIOD": peak_period,
        "AMPLITUDE": float(amp),
        "EARLY_MED": early,
        "MID_MED": mid,
        "LATE_MED": late,
        "RISE_SLOPE": rise,
        "DECLINE_SLOPE": decline,
        "FRAC_ABOVE_70PCT_PEAK": frac_above,
    }


def build_trajectory_matrix(period_df, train_ids):
    period_df = period_df[
        period_df[ID].isin(train_ids)
    ].copy()

    allowed_pairs = (
        [("BASIC", x) for x in BASIC_INDICES]
        + [("PRO", x) for x in PRO_INDICES]
    )

    parts = []
    coverage_rows = []

    for sensor, idx in allowed_pairs:
        sub = period_df[
            period_df["SENSOR"].eq(sensor)
            & period_df["INDEX"].eq(idx)
        ].copy()

        by_id = {
            pid: g
            for pid, g in sub.groupby(ID)
        }

        rows = []
        n_any = 0
        n_ge3 = 0
        period_counts = []

        for pid in train_ids:
            g = by_id.get(pid)

            if g is None or len(g) == 0:
                feats = {k: np.nan for k in TRAJ_STATS}
            else:
                feats = trajectory_features_one(
                    g["PERIOD"].to_numpy(),
                    g["VALUE"].to_numpy(),
                )
                if np.isfinite(feats["N_PERIODS"]):
                    n_any += 1
                    period_counts.append(feats["N_PERIODS"])
                    if feats["N_PERIODS"] >= MIN_PERIODS_FOR_SHAPE:
                        n_ge3 += 1

            row = {ID: pid}
            for stat, val in feats.items():
                row[f"TRAJ__{sensor}__{idx}__{stat}"] = val
            rows.append(row)

        part = pd.DataFrame(rows)
        parts.append(part)

        coverage_rows.append({
            "SENSOR": sensor,
            "INDEX": idx,
            "N_PARCELS_ANY": n_any,
            "N_PARCELS_GE3_PERIODS": n_ge3,
            "MEDIAN_N_PERIODS": (
                float(np.median(period_counts))
                if period_counts else np.nan
            ),
            "MIN_N_PERIODS": (
                float(np.min(period_counts))
                if period_counts else np.nan
            ),
            "MAX_N_PERIODS": (
                float(np.max(period_counts))
                if period_counts else np.nan
            ),
        })

    traj = pd.DataFrame({ID: train_ids})

    for part in parts:
        traj = traj.merge(
            part,
            on=ID,
            how="left",
            validate="one_to_one",
        )

    coverage = pd.DataFrame(coverage_rows)

    # Eliminar features completamente vacías o constantes.
    feature_cols = [c for c in traj.columns if c != ID]
    keep = []
    dropped = []

    for c in feature_cols:
        s = pd.to_numeric(traj[c], errors="coerce")
        finite = s.dropna()
        if len(finite) == 0:
            dropped.append((c, "ALL_NA"))
        elif finite.nunique() <= 1:
            dropped.append((c, "CONSTANT"))
        else:
            keep.append(c)

    traj = traj[[ID] + keep].copy()

    dropped_df = pd.DataFrame(
        dropped,
        columns=["FEATURE", "DROP_REASON"],
    )

    return traj, coverage, dropped_df


# ======================================================================
# MODELOS + NESTED LOGO
# ======================================================================
def require_xgboost():
    try:
        import xgboost  # noqa
    except Exception as exc:
        raise RuntimeError(
            "XGBoost es obligatorio para Exp14. "
            "Instala con: pip install xgboost"
        ) from exc


def make_model(model_name, params, seed):
    if model_name.startswith("RIDGE"):
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=float(params["alpha"]))),
        ])

    if model_name.startswith("XGB"):
        from xgboost import XGBRegressor
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                XGBRegressor(
                    objective="reg:squarederror",
                    eval_metric="rmse",
                    tree_method="hist",
                    random_state=seed,
                    n_jobs=-1,
                    verbosity=0,
                    **params,
                ),
            ),
        ])

    raise ValueError(model_name)


def grid_for(model_name):
    return RIDGE_GRID if model_name.startswith("RIDGE") else XGB_GRID


def inner_logo_score(X, y, groups, model_name, params, outer_group, cand_idx):
    logo = LeaveOneGroupOut()
    scores = []

    for inner_i, (tr, va) in enumerate(logo.split(X, y, groups), 1):
        seed = stable_seed(
            SEED, outer_group, model_name, cand_idx, inner_i
        )
        model = make_model(model_name, params, seed)
        model.fit(X.iloc[tr], y[tr])
        pred = model.predict(X.iloc[va])
        scores.append(rmse(y[va], pred))

    return float(np.mean(scores))


def tune_nested(X, y, groups, model_name, outer_group):
    best_score = np.inf
    best_params = None
    best_idx = None
    rows = []

    for i, params in enumerate(grid_for(model_name), 1):
        score = inner_logo_score(
            X, y, groups, model_name, params, outer_group, i
        )
        rows.append({
            "OUTER_HELDOUT": outer_group,
            "MODEL": model_name,
            "CANDIDATE": i,
            "INNER_MACRO_RMSE": score,
            "PARAMS": json.dumps(params, sort_keys=True),
        })
        if score < best_score - 1e-12:
            best_score = score
            best_params = params
            best_idx = i

    return best_params, best_score, best_idx, pd.DataFrame(rows)


def extract_xgb_importance(model, cols, heldout, model_name):
    m = model.named_steps["model"]
    v = np.asarray(m.feature_importances_, float)
    total = float(v.sum())
    vn = v / total if total > 0 else v

    return pd.DataFrame({
        "OUTER_HELDOUT": heldout,
        "MODEL": model_name,
        "FEATURE": cols,
        "IMPORTANCE": v,
        "IMPORTANCE_NORM": vn,
    })


def summarize(results, predictions):
    rows = []

    for model_name, g in results.groupby("MODEL"):
        pred = predictions[predictions["MODEL"].eq(model_name)]
        core = g[g["N_TEST"] >= 3]
        centered = core[core["CENTERED_RMSE"].notna()]
        spear = core[core["SPEARMAN_WITHIN"].notna()]

        rows.append({
            "MODEL": model_name,
            "N_MUNICIPIOS_ALL": int(g[MUNI].nunique()),
            "N_MUNICIPIOS_CORE_NGE3": int(core[MUNI].nunique()),
            "MACRO_RMSE_ALL": float(g["RMSE"].mean()),
            "MACRO_RMSE_CORE": float(core["RMSE"].mean()),
            "POOLED_RMSE": rmse(pred["REAL"], pred["PRED"]),
            "MACRO_MAE_ALL": float(g["MAE"].mean()),
            "MACRO_ABS_BIAS_ALL": float(g["BIAS"].abs().mean()),
            "MACRO_CENTERED_RMSE_CORE": (
                float(centered["CENTERED_RMSE"].mean())
                if len(centered) else np.nan
            ),
            "MEAN_SPEARMAN_CORE": (
                float(spear["SPEARMAN_WITHIN"].mean())
                if len(spear) else np.nan
            ),
            "MEDIAN_SPEARMAN_CORE": (
                float(spear["SPEARMAN_WITHIN"].median())
                if len(spear) else np.nan
            ),
            "WORST_MUNICIPIO_RMSE": float(g["RMSE"].max()),
        })

    return (
        pd.DataFrame(rows)
        .sort_values("MACRO_RMSE_ALL")
        .reset_index(drop=True)
    )


# ======================================================================
# MAIN
# ======================================================================
def main():
    require_xgboost()

    master_path, matrix_path, inventory_path, bases = locate_core()

    outdir = PHENOLOGY_ROOT / "02_Trayectorias_Temporales"
    outdir.mkdir(parents=True, exist_ok=True)

    master = pd.read_csv(master_path, encoding="utf-8-sig")
    matrix = pd.read_csv(matrix_path, encoding="utf-8-sig")
    inventory = pd.read_csv(inventory_path, encoding="utf-8-sig")

    master[ID] = master[ID].astype(str).str.strip()
    master[MUNI] = master[MUNI].astype(str).str.strip()
    master[SET] = master[SET].astype(str).str.strip().str.upper()
    master[Y] = pd.to_numeric(master[Y], errors="coerce")

    matrix[ID] = matrix[ID].astype(str).str.strip()
    if MUNI in matrix.columns:
        matrix = matrix.drop(columns=[MUNI])

    train = master[
        master[SET].eq("ENTRENAMIENTO")
    ][[ID, MUNI, Y]].copy()

    if len(train) != 138:
        raise ValueError(f"Esperaba 138 TRAIN; encontré {len(train)}.")

    train_ids = train[ID].tolist()

    # --------------------------------------------------------------
    # ALL = mismo conjunto biofísico de Exp12/13.
    # --------------------------------------------------------------
    all_cols, audit_all = make_all_feature_set(inventory, matrix)

    if len(all_cols) < 100:
        raise RuntimeError(
            f"ALL inesperadamente pequeño: {len(all_cols)} features."
        )

    audit_all.to_csv(
        outdir / "01_Auditoria_All.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------------------
    # Descubrir series crudas y construir trayectoria.
    # --------------------------------------------------------------
    try:
        period_df, audit_raw = discover_raw(bases)
    except Exception:
        # Crear auditoría aunque falle parcialmente cuando sea posible.
        candidates = []
        for p in candidate_csvs(bases):
            s = infer_sensor_from_path(p)
            if s:
                candidates.append({
                    "FILE": str(p),
                    "SENSOR_HINT": s,
                    "STATUS": "CANDIDATE_NOT_PARSED",
                })
        pd.DataFrame(candidates).to_csv(
            outdir / "02_Auditoria_Raw_Files.csv",
            index=False,
            encoding="utf-8-sig",
        )
        raise

    audit_raw.to_csv(
        outdir / "02_Auditoria_Raw_Files.csv",
        index=False,
        encoding="utf-8-sig",
    )

    traj, coverage, dropped_traj = build_trajectory_matrix(
        period_df,
        train_ids,
    )

    coverage.to_csv(
        outdir / "03_Cobertura_Trayectorias.csv",
        index=False,
        encoding="utf-8-sig",
    )

    traj.to_csv(
        outdir / "04_Matriz_Trayectorias_138.csv",
        index=False,
        encoding="utf-8-sig",
    )

    if len(dropped_traj):
        dropped_traj.to_csv(
            outdir / "04b_Trajectory_Features_Dropped.csv",
            index=False,
            encoding="utf-8-sig",
        )

    traj_cols = [c for c in traj.columns if c != ID]

    if len(traj_cols) < 30:
        raise RuntimeError(
            f"Sólo se construyeron {len(traj_cols)} trajectory features. "
            "Revisa 02_Auditoria_Raw_Files.csv y 03_Cobertura_Trayectorias.csv."
        )

    # Contexto universal: CLIMATE + TOPO válidos del ALL.
    inv_map = (
        inventory[["FEATURE", "BLOCK"]]
        .copy()
    )
    inv_map["BLOCK"] = inv_map["BLOCK"].astype(str).str.upper()

    context_cols = inv_map.loc[
        inv_map["BLOCK"].isin(["CLIMATE", "TOPO"])
        & inv_map["FEATURE"].isin(all_cols),
        "FEATURE",
    ].tolist()

    traj_context_cols = traj_cols + context_cols

    # ALL + TRAJ, sin duplicados.
    all_plus_traj_cols = list(dict.fromkeys(all_cols + traj_cols))

    # --------------------------------------------------------------
    # Unir matrices.
    # --------------------------------------------------------------
    data = (
        train
        .merge(
            matrix[[ID] + all_cols],
            on=ID,
            how="left",
            validate="one_to_one",
        )
        .merge(
            traj,
            on=ID,
            how="left",
            validate="one_to_one",
        )
    )

    for c in all_plus_traj_cols:
        data[c] = pd.to_numeric(data[c], errors="coerce")

    # Seguridad final.
    bad = [
        c for c in all_plus_traj_cols
        if is_forbidden_feature(c)
    ]
    if bad:
        raise RuntimeError(
            "AUDITORÍA FALLIDA: features prohibidas:\n"
            + "\n".join(bad)
        )

    municipalities = (
        data[MUNI]
        .value_counts()
        .sort_values(ascending=False)
    )

    print("=" * 132)
    print(
        "EXPERIMENTO 14 v4 — TRAYECTORIAS TEMPORALES EXPLÍCITAS / NESTED LOGO"
    )
    print("=" * 132)

    print(f"MASTER:         {master_path}")
    print(f"MATRIZ EXP09:   {matrix_path}")
    print(f"ALL features:   {len(all_cols)}")
    print(f"TRAJ features:  {len(traj_cols)}")
    print(f"CONTEXT:        {len(context_cols)}")
    print(f"TRAJ+CONTEXT:   {len(traj_context_cols)}")
    print(f"ALL+TRAJ:       {len(all_plus_traj_cols)}")

    print("\nCOBERTURA DE TRAYECTORIAS:")
    print(
        coverage.to_string(
            index=False,
            float_format=lambda x: f"{x:.2f}",
        )
    )

    print("\nTAMAÑO POR MUNICIPIO:")
    print(municipalities.to_string())

    print("\nMunicipio = GROUP solamente. Nunca predictor.")

    specs = {
        "RIDGE_ALL": all_cols,
        "RIDGE_TRAJ": traj_context_cols,
        "RIDGE_ALL_PLUS_TRAJ": all_plus_traj_cols,
        "XGB_ALL": all_cols,
        "XGB_TRAJ": traj_context_cols,
        "XGB_ALL_PLUS_TRAJ": all_plus_traj_cols,
    }

    groups_all = data[MUNI].astype(str).to_numpy()
    y_all = data[Y].to_numpy(float)
    outer_groups = sorted(data[MUNI].unique())

    result_rows = []
    pred_rows = []
    param_rows = []
    tuning_parts = []
    imp_parts = []

    for outer_i, heldout in enumerate(outer_groups, 1):
        test_mask = groups_all == str(heldout)
        idx_te = np.flatnonzero(test_mask)
        idx_tr = np.flatnonzero(~test_mask)

        ytr = y_all[idx_tr]
        yte = y_all[idx_te]
        gtr = groups_all[idx_tr]
        ids_te = data.iloc[idx_te][ID].tolist()

        print("\n" + "-" * 132)
        print(
            f"OUTER {outer_i}/{len(outer_groups)} | "
            f"HELD-OUT={heldout} | N_TEST={len(idx_te)} | N_TRAIN={len(idx_tr)}"
        )
        print("-" * 132)

        # Global mean.
        pred_mean = np.full(len(yte), float(np.mean(ytr)))
        met = {
            "RMSE": rmse(yte, pred_mean),
            "MAE": mae(yte, pred_mean),
            "BIAS": bias(yte, pred_mean),
            "CENTERED_RMSE": centered_rmse(yte, pred_mean),
            "SPEARMAN_WITHIN": spearman_within(yte, pred_mean),
        }
        result_rows.append({
            MUNI: heldout,
            "N_TEST": len(yte),
            "MODEL": "GLOBAL_MEAN",
            **met,
            "INNER_MACRO_RMSE": np.nan,
            "BEST_CANDIDATE": np.nan,
        })
        for pid, yy, pp in zip(ids_te, yte, pred_mean):
            pred_rows.append({
                ID: pid, MUNI: heldout, "MODEL": "GLOBAL_MEAN",
                "REAL": float(yy), "PRED": float(pp),
                "ERROR": float(pp - yy),
            })

        print(
            f"{'GLOBAL_MEAN':20s} RMSE={met['RMSE']:.6f} | "
            f"BIAS={met['BIAS']:+.6f}"
        )

        for model_name, cols in specs.items():
            Xtr = data.iloc[idx_tr][cols].reset_index(drop=True)
            Xte = data.iloc[idx_te][cols].reset_index(drop=True)

            best_params, best_inner, best_idx, tuning = tune_nested(
                Xtr, ytr, gtr, model_name, heldout
            )
            tuning_parts.append(tuning)

            param_rows.append({
                "OUTER_HELDOUT": heldout,
                "MODEL": model_name,
                "N_FEATURES": len(cols),
                "BEST_CANDIDATE": best_idx,
                "INNER_MACRO_RMSE": best_inner,
                "BEST_PARAMS": json.dumps(best_params, sort_keys=True),
            })

            seed = stable_seed(SEED, "FINAL", heldout, model_name)
            model = make_model(model_name, best_params, seed)
            model.fit(Xtr, ytr)
            pred = model.predict(Xte)

            met = {
                "RMSE": rmse(yte, pred),
                "MAE": mae(yte, pred),
                "BIAS": bias(yte, pred),
                "CENTERED_RMSE": centered_rmse(yte, pred),
                "SPEARMAN_WITHIN": spearman_within(yte, pred),
            }

            result_rows.append({
                MUNI: heldout,
                "N_TEST": len(yte),
                "MODEL": model_name,
                **met,
                "INNER_MACRO_RMSE": best_inner,
                "BEST_CANDIDATE": best_idx,
            })

            for pid, yy, pp in zip(ids_te, yte, pred):
                pred_rows.append({
                    ID: pid, MUNI: heldout, "MODEL": model_name,
                    "REAL": float(yy), "PRED": float(pp),
                    "ERROR": float(pp - yy),
                })

            if model_name.startswith("XGB"):
                imp_parts.append(
                    extract_xgb_importance(
                        model, cols, heldout, model_name
                    )
                )

            cr = (
                f"{met['CENTERED_RMSE']:.6f}"
                if np.isfinite(met["CENTERED_RMSE"])
                else "NA"
            )
            rho = (
                f"{met['SPEARMAN_WITHIN']:+.3f}"
                if np.isfinite(met["SPEARMAN_WITHIN"])
                else "NA"
            )

            print(
                f"{model_name:20s} inner={best_inner:.6f} | "
                f"RMSE={met['RMSE']:.6f} | "
                f"BIAS={met['BIAS']:+.6f} | "
                f"cRMSE={cr} | rho={rho}"
            )

    results = pd.DataFrame(result_rows)
    predictions = pd.DataFrame(pred_rows)
    params_df = pd.DataFrame(param_rows)
    tuning_all = pd.concat(tuning_parts, ignore_index=True)
    importances = pd.concat(imp_parts, ignore_index=True)

    summary = summarize(results, predictions)

    top_imp = (
        importances.groupby(
            ["MODEL", "FEATURE"],
            as_index=False,
        )
        .agg(
            MEAN_IMPORTANCE_NORM=("IMPORTANCE_NORM", "mean"),
            MEDIAN_IMPORTANCE_NORM=("IMPORTANCE_NORM", "median"),
            N_OUTER_MODELS=("OUTER_HELDOUT", "nunique"),
        )
        .sort_values(
            ["MODEL", "MEAN_IMPORTANCE_NORM"],
            ascending=[True, False],
        )
    )

    print("\n" + "=" * 132)
    print("RESULTADOS POR MUNICIPIO — EXP14")
    print("=" * 132)
    print(
        results.sort_values([MUNI, "RMSE"]).to_string(
            index=False,
            float_format=lambda x: f"{x:.6f}",
        )
    )

    print("\n" + "=" * 132)
    print("RESUMEN MODELOS — TRAYECTORIAS")
    print("=" * 132)
    print(
        summary.to_string(
            index=False,
            float_format=lambda x: f"{x:.6f}",
        )
    )

    # --------------------------------------------------------------
    # Lectura automática
    # --------------------------------------------------------------
    def row(name):
        return summary[summary["MODEL"].eq(name)].iloc[0]

    ra = row("RIDGE_ALL")
    rt = row("RIDGE_TRAJ")
    rap = row("RIDGE_ALL_PLUS_TRAJ")
    xa = row("XGB_ALL")
    xt = row("XGB_TRAJ")
    xap = row("XGB_ALL_PLUS_TRAJ")

    d_ridge_add = float(
        ra["MACRO_RMSE_ALL"] - rap["MACRO_RMSE_ALL"]
    )
    d_xgb_add = float(
        xa["MACRO_RMSE_ALL"] - xap["MACRO_RMSE_ALL"]
    )
    d_xgb_vs_ridge = float(
        rap["MACRO_RMSE_ALL"] - xap["MACRO_RMSE_ALL"]
    )

    d_ridge_add_core = float(
        ra["MACRO_RMSE_CORE"] - rap["MACRO_RMSE_CORE"]
    )
    d_xgb_add_core = float(
        xa["MACRO_RMSE_CORE"] - xap["MACRO_RMSE_CORE"]
    )

    print("\n" + "=" * 132)
    print("LECTURA AUTOMÁTICA CONSERVADORA")
    print("=" * 132)

    print(
        f"RIDGE: ALL -> ALL+TRAJ mejora ALL9 = {d_ridge_add:+.6f}; "
        f"CORE = {d_ridge_add_core:+.6f}"
    )
    print(
        f"XGB:   ALL -> ALL+TRAJ mejora ALL9 = {d_xgb_add:+.6f}; "
        f"CORE = {d_xgb_add_core:+.6f}"
    )
    print(
        f"XGB_ALL_PLUS_TRAJ vs RIDGE_ALL_PLUS_TRAJ = "
        f"{d_xgb_vs_ridge:+.6f} "
        "(positivo = XGB gana)"
    )

    if d_xgb_add > 0 and d_xgb_add_core > 0:
        print(
            "Trayectorias apoyadas para XGBoost en ALL9 y CORE: "
            "la nueva representación aporta señal incremental."
        )
    elif d_xgb_add > 0 or d_xgb_add_core > 0:
        print(
            "Resultado mixto para XGBoost: trayectoria mejora una agregación "
            "pero no la otra. No declarar éxito robusto."
        )
    else:
        print(
            "Trayectorias no mejoran XGBoost frente a ALL en ninguna "
            "de las dos agregaciones principales."
        )

    if (
        xap["MACRO_CENTERED_RMSE_CORE"]
        < xap["MACRO_RMSE_CORE"] - 0.10
    ):
        print(
            "El gap RMSE CORE vs Centered-RMSE CORE sigue siendo grande: "
            "persiste un componente fuerte de calibración/domain shift."
        )

    if np.isfinite(xap["MEAN_SPEARMAN_CORE"]):
        print(
            f"Spearman medio CORE XGB_ALL_PLUS_TRAJ = "
            f"{xap['MEAN_SPEARMAN_CORE']:+.3f}"
        )

    # --------------------------------------------------------------
    # Guardar
    # --------------------------------------------------------------
    results.to_csv(
        outdir / "05_Resultados_Por_Municipio.csv",
        index=False, encoding="utf-8-sig",
    )
    summary.to_csv(
        outdir / "06_Resumen_Modelos.csv",
        index=False, encoding="utf-8-sig",
    )
    params_df.to_csv(
        outdir / "07_Mejores_Hiperparametros.csv",
        index=False, encoding="utf-8-sig",
    )
    tuning_all.to_csv(
        outdir / "08_Tuning_Inner_LOGO.csv",
        index=False, encoding="utf-8-sig",
    )
    predictions.to_csv(
        outdir / "09_Predicciones_LOGO.csv",
        index=False, encoding="utf-8-sig",
    )
    importances.to_csv(
        outdir / "10_Importancias_XGB.csv",
        index=False, encoding="utf-8-sig",
    )
    top_imp.to_csv(
        outdir / "11_Top_Importancias_XGB.csv",
        index=False, encoding="utf-8-sig",
    )

    with open(outdir / "12_Resumen.txt", "w", encoding="utf-8") as f:
        f.write("EXPERIMENTO 14 — TRAYECTORIAS TEMPORALES\n\n")
        f.write(
            f"ALL={len(all_cols)}\n"
            f"TRAJ={len(traj_cols)}\n"
            f"CONTEXT={len(context_cols)}\n"
            f"TRAJ_CONTEXT={len(traj_context_cols)}\n"
            f"ALL_PLUS_TRAJ={len(all_plus_traj_cols)}\n\n"
        )
        f.write("COBERTURA\n")
        f.write(coverage.to_string(index=False))
        f.write("\n\nRESUMEN\n")
        f.write(summary.to_string(index=False))
        f.write("\n\nDELTAS\n")
        f.write(
            f"RIDGE ALL->ALL+TRAJ ALL9 {d_ridge_add:+.6f}\n"
            f"RIDGE ALL->ALL+TRAJ CORE {d_ridge_add_core:+.6f}\n"
            f"XGB ALL->ALL+TRAJ ALL9 {d_xgb_add:+.6f}\n"
            f"XGB ALL->ALL+TRAJ CORE {d_xgb_add_core:+.6f}\n"
            f"XGB vs RIDGE ALL+TRAJ {d_xgb_vs_ridge:+.6f}\n"
        )

    print(f"\nArchivos guardados en:\n{outdir}")
    print("\nPÁSAME ESTAS SECCIONES:")
    print("  1) ALL/TRAJ/ALL+TRAJ + COBERTURA DE TRAYECTORIAS")
    print("  2) RESULTADOS POR MUNICIPIO — EXP14")
    print("  3) RESUMEN MODELOS — TRAYECTORIAS")
    print("  4) LECTURA AUTOMÁTICA CONSERVADORA")
    print("  5) Si falla discovery: 02_Auditoria_Raw_Files.csv")


if __name__ == "__main__":
    main()
