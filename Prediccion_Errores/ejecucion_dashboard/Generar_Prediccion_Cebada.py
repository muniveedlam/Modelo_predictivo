import numpy as np
import pandas as pd
from pathlib import Path


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent

# Si el script está dentro de alguna subcarpeta y no encuentra MASTER,
# automáticamente intenta subir un nivel.
if (SCRIPT_DIR / "Cebada_197.csv").exists():
    PROJECT = SCRIPT_DIR
elif (SCRIPT_DIR.parent / "Master_Cebada_197.csv").exists():
    PROJECT = SCRIPT_DIR.parent
else:
    raise FileNotFoundError(
        "No se encontró Cebada_197.csv "
        "ni en la carpeta del script ni un nivel arriba."
    )


MASTER = PROJECT / "Master_Cebada_197.csv"

OUT = PROJECT / "Prediccion_Final_Cebada"
OUT.mkdir(exist_ok=True)


# Modelo validado
LAMBDA_AREA = 0.75

MIN_N_MUNI = 5
MIN_STD_MUNI = 0.05


ID = "ID_POLIGONO"
MUNI = "Municipio"
AREA = "AREA_HA"
Y = "RENDIMIENTO_T_HA"
SET = "CONJUNTO"


# =============================================================================
# 1. CARGA
# =============================================================================

df = pd.read_csv(MASTER)


required = [
    ID,
    MUNI,
    AREA,
    Y,
    SET,
]

missing = [
    c
    for c in required
    if c not in df.columns
]

if missing:
    raise ValueError(
        f"Faltan columnas: {missing}"
    )


df[ID] = (
    df[ID]
    .astype(str)
    .str.strip()
)

df[MUNI] = (
    df[MUNI]
    .astype(str)
    .str.strip()
)

df[SET] = (
    df[SET]
    .astype(str)
    .str.strip()
)

df[AREA] = pd.to_numeric(
    df[AREA],
    errors="coerce"
)

df[Y] = pd.to_numeric(
    df[Y],
    errors="coerce"
)


if df[AREA].isna().any():
    raise ValueError(
        "Hay AREA_HA faltantes."
    )

if (df[AREA] <= 0).any():

    bad = df.loc[
        df[AREA] <= 0,
        ID
    ].tolist()

    raise ValueError(
        f"Hay áreas <= 0: {bad}"
    )


df["LOG_AREA"] = np.log(
    df[AREA]
)


train = df[
    df[SET].eq(
        "ENTRENAMIENTO"
    )
].copy()

test = df[
    df[SET].eq(
        "PREDICCION"
    )
].copy()


print("=" * 100)
print("PREDICCION FINAL — AGROCEBADA")
print("=" * 100)

print(
    f"\nTrain      : {len(train)}"
)

print(
    f"Prediccion : {len(test)}"
)


if len(train) != 138:
    print(
        f"ADVERTENCIA: esperábamos 138 "
        f"parcelas train y hay {len(train)}"
    )

if len(test) != 59:
    print(
        f"ADVERTENCIA: esperábamos 59 "
        f"parcelas predicción y hay {len(test)}"
    )


# =============================================================================
# 2. ESTADISTICAS MUNICIPALES
# =============================================================================

muni_stats = (

    train
    .groupby(MUNI)[Y]
    .agg(
        n="count",
        mean="mean",
        std="std",
        min="min",
        max="max"
    )
)


print("\n" + "=" * 100)
print("ESTADISTICAS MUNICIPALES TRAIN")
print("=" * 100)

print(
    muni_stats.to_string()
)


# =============================================================================
# 3. CENTRADO DE LOG(AREA)
#
# IMPORTANTE:
# Todo lo relacionado con rendimiento usa únicamente TRAIN.
# =============================================================================

log_area_mean = (

    train
    .groupby(MUNI)[
        "LOG_AREA"
    ]
    .mean()
)


area_ranges = (

    train
    .groupby(MUNI)[
        "LOG_AREA"
    ]
    .agg(
        LOG_AREA_MIN="min",
        LOG_AREA_MAX="max"
    )
)


# =============================================================================
# 4. MUNICIPIOS ELEGIBLES PARA EFECTO DE AREA
# =============================================================================

eligible = muni_stats.index[

    (muni_stats["n"] >= MIN_N_MUNI)

    &

    (muni_stats["std"] >= MIN_STD_MUNI)

].tolist()


print(
    "\nMunicipios elegibles "
    "para corrección de área:"
)

for m in eligible:
    print(
        f"  - {m}"
    )


# =============================================================================
# 5. ESTIMAR BETA GLOBAL
#
# y_center = rendimiento - media municipal
# x_center = log(area) - media log(area) municipal
# =============================================================================

tr_beta = train[
    train[MUNI].isin(
        eligible
    )
].copy()


tr_beta["X_AREA"] = (

    tr_beta["LOG_AREA"]

    -

    tr_beta[MUNI].map(
        log_area_mean
    )
)


tr_beta["Y_CENTER"] = (

    tr_beta[Y]

    -

    tr_beta[MUNI].map(
        muni_stats["mean"]
    )
)


den = np.sum(
    tr_beta["X_AREA"] ** 2
)


if den <= 1e-12:

    raise ValueError(
        "No hay variación suficiente "
        "para estimar beta de área."
    )


beta_raw = (

    np.sum(
        tr_beta["X_AREA"]
        *
        tr_beta["Y_CENTER"]
    )

    /

    den
)


beta_final = (
    LAMBDA_AREA
    *
    beta_raw
)


# =============================================================================
# 6. ESCALADO POR VARIABILIDAD MUNICIPAL
#
# Municipios muy pequeños o casi constantes:
# corrección = 0.
# =============================================================================

std_reference = (

    muni_stats
    .loc[
        eligible,
        "std"
    ]
    .median()
)


scales = {}


for muni, row in muni_stats.iterrows():

    if (
        row["n"] < MIN_N_MUNI
        or
        pd.isna(row["std"])
        or
        row["std"] < MIN_STD_MUNI
    ):

        scales[muni] = 0.0

    else:

        scales[muni] = min(
            1.0,
            row["std"]
            /
            std_reference
        )


scales = pd.Series(
    scales,
    name="AREA_SCALE",
    dtype=float
)


print("\n" + "=" * 100)
print("PARAMETROS DEL MODELO FINAL")
print("=" * 100)

print(
    f"\nBeta area raw      = {beta_raw:+.6f}"
)

print(
    f"Lambda             = {LAMBDA_AREA:.2f}"
)

print(
    f"Beta contraida     = {beta_final:+.6f}"
)

print(
    f"Std referencia     = {std_reference:.6f}"
)

print(
    "\nEscala por municipio:"
)

print(
    scales.to_string()
)


# =============================================================================
# 7. PREPARAR LAS 59 PARCELAS
# =============================================================================

pred = test.copy()


pred["MEDIA_MUNICIPAL"] = (

    pred[MUNI]
    .map(
        muni_stats["mean"]
    )
)


pred["N_TRAIN_MUNICIPIO"] = (

    pred[MUNI]
    .map(
        muni_stats["n"]
    )
)


pred["STD_TRAIN_MUNICIPIO"] = (

    pred[MUNI]
    .map(
        muni_stats["std"]
    )
)


pred["AREA_SCALE"] = (

    pred[MUNI]
    .map(
        scales
    )
    .fillna(0.0)
)


pred["LOG_AREA_MEAN_TRAIN"] = (

    pred[MUNI]
    .map(
        log_area_mean
    )
)


pred["LOG_AREA_MIN_TRAIN"] = (

    pred[MUNI]
    .map(
        area_ranges[
            "LOG_AREA_MIN"
        ]
    )
)


pred["LOG_AREA_MAX_TRAIN"] = (

    pred[MUNI]
    .map(
        area_ranges[
            "LOG_AREA_MAX"
        ]
    )
)


# =============================================================================
# 8. AUDITORIA MUNICIPIOS SIN TRAIN
# =============================================================================

if pred[
    "MEDIA_MUNICIPAL"
].isna().any():

    bad = (

        pred.loc[
            pred[
                "MEDIA_MUNICIPAL"
            ].isna(),
            MUNI
        ]
        .unique()
        .tolist()
    )

    raise ValueError(
        "Hay municipios de predicción "
        f"sin entrenamiento: {bad}"
    )


# =============================================================================
# 9. CLIPPING DEL AREA
#
# No extrapolamos la pendiente fuera del rango de áreas observado
# en TRAIN para ese municipio.
# =============================================================================

pred["LOG_AREA_CLIPPED"] = np.maximum(

    pred[
        "LOG_AREA_MIN_TRAIN"
    ],

    np.minimum(

        pred["LOG_AREA"],

        pred[
            "LOG_AREA_MAX_TRAIN"
        ]
    )
)


pred["AREA_CLIPPED_HA"] = np.exp(
    pred[
        "LOG_AREA_CLIPPED"
    ]
)


pred["FUE_CLIPPED"] = (

    np.abs(
        pred["LOG_AREA"]
        -
        pred["LOG_AREA_CLIPPED"]
    )

    >
    1e-12
)


# =============================================================================
# 10. CORRECCION POR AREA
# =============================================================================

pred["DELTA_LOG_AREA"] = (

    pred[
        "LOG_AREA_CLIPPED"
    ]

    -

    pred[
        "LOG_AREA_MEAN_TRAIN"
    ]
)


pred["CORRECCION_AREA"] = (

    beta_final

    *

    pred["AREA_SCALE"]

    *

    pred["DELTA_LOG_AREA"]
)


# =============================================================================
# 11. PREDICCION
# =============================================================================

pred["PREDICCION_T_HA"] = (

    pred[
        "MEDIA_MUNICIPAL"
    ]

    +

    pred[
        "CORRECCION_AREA"
    ]
)


# =============================================================================
# 12. CONTROL CONSERVADOR
#
# No permitimos que la predicción salga fuera del rango de rendimiento
# observado en ese municipio.
#
# En la práctica las correcciones son pequeñas, pero queda auditado.
# =============================================================================

pred["Y_MIN_MUNICIPIO"] = (

    pred[MUNI]
    .map(
        muni_stats["min"]
    )
)


pred["Y_MAX_MUNICIPIO"] = (

    pred[MUNI]
    .map(
        muni_stats["max"]
    )
)


pred["PRED_ANTES_CLIP_Y"] = (
    pred[
        "PREDICCION_T_HA"
    ]
)


pred["PREDICCION_T_HA"] = np.maximum(

    pred[
        "Y_MIN_MUNICIPIO"
    ],

    np.minimum(

        pred[
            "PREDICCION_T_HA"
        ],

        pred[
            "Y_MAX_MUNICIPIO"
        ]
    )
)


pred["Y_FUE_CLIPPED"] = (

    np.abs(
        pred[
            "PRED_ANTES_CLIP_Y"
        ]

        -

        pred[
            "PREDICCION_T_HA"
        ]
    )

    >
    1e-12
)


# =============================================================================
# 13. NIVEL DE CONFIANZA DESCRIPTIVO
#
# NO modifica la predicción.
#
# Sólo sirve para identificar dónde tenemos poca evidencia.
# =============================================================================

def confidence_label(n):

    if pd.isna(n):
        return "SIN_TRAIN"

    if n >= 30:
        return "ALTA"

    if n >= 10:
        return "MEDIA"

    if n >= 5:
        return "BAJA"

    return "MUY_BAJA"


pred["CONFIANZA_ESTRUCTURAL"] = (

    pred[
        "N_TRAIN_MUNICIPIO"
    ]
    .apply(
        confidence_label
    )
)


# =============================================================================
# 14. SALIDA DETALLADA
# =============================================================================

detail_cols = [

    ID,
    "Estado",
    MUNI,
    AREA,

    "N_TRAIN_MUNICIPIO",

    "MEDIA_MUNICIPAL",

    "STD_TRAIN_MUNICIPIO",

    "AREA_SCALE",

    "DELTA_LOG_AREA",

    "CORRECCION_AREA",

    "FUE_CLIPPED",

    "Y_FUE_CLIPPED",

    "CONFIANZA_ESTRUCTURAL",

    "PREDICCION_T_HA",
]


detail_cols = [
    c
    for c in detail_cols
    if c in pred.columns
]


detail = (

    pred[
        detail_cols
    ]
    .sort_values(
        [
            MUNI,
            ID
        ]
    )
    .reset_index(
        drop=True
    )
)


# =============================================================================
# 15. SUBMISSION
# =============================================================================

submission = (

    pred[
        [
            ID,
            "PREDICCION_T_HA"
        ]
    ]
    .sort_values(
        ID
    )
    .reset_index(
        drop=True
    )
)


# =============================================================================
# 16. RESUMEN MUNICIPAL DE PREDICCIONES
# =============================================================================

summary = (

    pred
    .groupby(MUNI)
    .agg(

        N_PRED=(
            ID,
            "count"
        ),

        N_TRAIN=(
            "N_TRAIN_MUNICIPIO",
            "first"
        ),

        MEDIA_TRAIN=(
            "MEDIA_MUNICIPAL",
            "first"
        ),

        PRED_MEDIA=(
            "PREDICCION_T_HA",
            "mean"
        ),

        PRED_MIN=(
            "PREDICCION_T_HA",
            "min"
        ),

        PRED_MAX=(
            "PREDICCION_T_HA",
            "max"
        ),

        CORRECCION_MEDIA=(
            "CORRECCION_AREA",
            "mean"
        ),

        CORRECCION_MAX_ABS=(
            "CORRECCION_AREA",
            lambda x:
                np.max(
                    np.abs(x)
                )
        ),

        N_AREA_CLIPPED=(
            "FUE_CLIPPED",
            "sum"
        ),

    )
    .reset_index()
    .sort_values(
        "N_PRED",
        ascending=False
    )
)


# =============================================================================
# 17. GUARDAR
# =============================================================================

detail_file = (
    OUT /
    "Predicciones_59_Detalladas.csv"
)

submission_file = (
    OUT /
    "Submission_59.csv"
)

summary_file = (
    OUT /
    "Resumen_Predicciones_Municipio.csv"
)


detail.to_csv(
    detail_file,
    index=False,
    float_format="%.6f"
)


submission.to_csv(
    submission_file,
    index=False,
    float_format="%.6f"
)


summary.to_csv(
    summary_file,
    index=False,
    float_format="%.6f"
)


# =============================================================================
# 18. CONSOLA
# =============================================================================

print("\n" + "=" * 100)
print("RESUMEN DE LAS 59 PREDICCIONES")
print("=" * 100)

print(
    summary.to_string(
        index=False
    )
)


print("\n" + "=" * 100)
print("PREDICCIONES INDIVIDUALES")
print("=" * 100)

print(
    detail.to_string(
        index=False
    )
)


print("\n" + "=" * 100)
print("CONTROLES")
print("=" * 100)

print(
    f"\nParcelas predichas: "
    f"{len(submission)}"
)

print(
    f"Áreas clipped: "
    f"{int(pred['FUE_CLIPPED'].sum())}"
)

print(
    f"Predicciones clipped por yield: "
    f"{int(pred['Y_FUE_CLIPPED'].sum())}"
)

print(
    f"Predicción mínima: "
    f"{pred['PREDICCION_T_HA'].min():.4f}"
)

print(
    f"Predicción máxima: "
    f"{pred['PREDICCION_T_HA'].max():.4f}"
)


print("\n" + "=" * 100)
print("ARCHIVOS")
print("=" * 100)

print(
    detail_file
)

print(
    submission_file
)

print(
    summary_file
)


print(
    "\nMODELO: municipio + log(area) "
    "con beta global contraída, "
    "escalado por variabilidad municipal "
    "y clipping conservador."
)