#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tabla de errores honestos para el modelo final de AgroCebada.

Colocar este script al lado de Cebada_197.csv y ejecutar:
    python Calcular_Errores_Cebada_197.py

AUTO: si existe splits_50_ids_EXACTOS.csv (junto al script o en
Experimento_PartialPooling_MismosSplits), reproduce la evaluación original;
si NO existe, aplica leave-one-out por parcela evaluable y lo identifica.

IMPORTANTE: las 59 filas PREDICCION no tienen rendimiento observado,
por lo tanto su error NO se puede medir todavía.
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

# --------------------- Configuración congelada ------------------------------
ID = "ID_POLIGONO"
MUNI = "Municipio"
AREA = "AREA_HA"
Y = "RENDIMIENTO_T_HA"
SET = "CONJUNTO"

LAMBDA_AREA = 0.75
MIN_N_MUNI = 5
MIN_STD_MUNI = 0.05
RMSE_REFERENCIA_50 = 0.481502
TOLERANCIA_REFERENCIA = 5e-6

# "AUTO", "SPLITS_50" o "LOO".
MODO = "AUTO"

# Salidas: nunca sobreescribe los archivos de envío.
OUT_NAME = "Tabla_Errores_Cebada"


def buscar_maestro():
    carpeta = Path(__file__).resolve().parent
    for base in (carpeta, carpeta.parent):
        path = base / "Cebada_197.csv"
        if path.is_file():
            return base, path
    raise FileNotFoundError(
        "No encuentro Cebada_197.csv junto al script ni en su carpeta padre. "
        "Comprueba que sea Cebada_197.csv (197, no 179)."
    )


def buscar_splits(root):
    directorios = [root, root / "Experimento_PartialPooling_MismosSplits"]
    carpeta_script = Path(__file__).resolve().parent
    directorios.extend([carpeta_script, carpeta_script / "Experimento_PartialPooling_MismosSplits"])
    for base in directorios:
        archivo = base / "splits_50_ids_EXACTOS.csv"
        if archivo.is_file():
            return archivo
    return None


def preparar_maestro(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    requeridas = {ID, MUNI, AREA, Y, SET}
    faltantes = requeridas - set(df.columns)
    if faltantes:
        raise ValueError(f"El maestro no tiene columnas necesarias: {sorted(faltantes)}")
    for col in [ID, MUNI, SET]:
        df[col] = df[col].astype(str).str.strip()
    df[SET] = df[SET].str.upper()
    df[AREA] = pd.to_numeric(df[AREA], errors="coerce")
    df[Y] = pd.to_numeric(df[Y], errors="coerce")
    if df[ID].duplicated().any():
        raise ValueError(f"Existen IDs duplicados: {df.loc[df[ID].duplicated(), ID].tolist()}")
    if df[AREA].isna().any() or (df[AREA] <= 0).any():
        raise ValueError("AREA_HA tiene valores inválidos o no positivos.")
    if not df[SET].isin(["ENTRENAMIENTO", "PREDICCION"]).all():
        raise ValueError("CONJUNTO debe contener ENTRENAMIENTO o PREDICCION.")
    df["LOG_AREA"] = np.log(df[AREA])
    train = df[df[SET] == "ENTRENAMIENTO"].copy()
    pending = df[df[SET] == "PREDICCION"].copy()
    if train[Y].isna().any():
        raise ValueError("Hay rendimientos reales faltantes en ENTRENAMIENTO.")
    if len(train) != 138 or len(pending) != 59:
        print(f"ADVERTENCIA: hay {len(train)} TRAIN y {len(pending)} PREDICCION; "
              "se esperaban 138 y 59.")
    return train, pending


def ajustar_modelo(train):
    """Mismo estimador de la auditoría del campeón, ajustado SOLO en TRAIN."""
    stats = train.groupby(MUNI)[Y].agg(n="count", mean="mean", std="std")
    log_mean = train.groupby(MUNI)["LOG_AREA"].mean()
    area_range = train.groupby(MUNI)["LOG_AREA"].agg(xmin="min", xmax="max")

    aptos = stats.index[(stats["n"] >= MIN_N_MUNI) &
                         (stats["std"] >= MIN_STD_MUNI)].tolist()
    if not aptos:
        beta_raw, std_ref = 0.0, np.nan
    else:
        sub = train[train[MUNI].isin(aptos)].copy()
        xc = sub["LOG_AREA"] - sub[MUNI].map(log_mean)
        yc = sub[Y] - sub[MUNI].map(stats["mean"])
        den = float(np.sum(xc.to_numpy(dtype=float) ** 2))
        beta_raw = float(np.sum(xc.to_numpy(dtype=float) * yc.to_numpy(dtype=float)) / den) if den > 1e-12 else 0.0
        std_ref = float(stats.loc[aptos, "std"].median())

    scales = {}
    for m, s in stats.iterrows():
        if (s["n"] < MIN_N_MUNI or pd.isna(s["std"]) or
                s["std"] < MIN_STD_MUNI or pd.isna(std_ref) or std_ref <= 0):
            scales[m] = 0.0
        else:
            scales[m] = min(1.0, float(s["std"] / std_ref))

    return {
        "stats": stats,
        "means_log": log_mean,
        "ranges_log": area_range,
        "beta": LAMBDA_AREA * beta_raw,
        "scales": scales,
    }


def predecir_modelo(modelo, valid):
    """Predicción sin Y de validación, con clipping de log-área de TRAIN."""
    preds = []
    for _, row in valid.iterrows():
        m = row[MUNI]
        if m not in modelo["stats"].index:
            raise RuntimeError(
                f"El municipio {m} no está representado en este TRAIN. "
                "Esa parcela no puede evaluarse con este modelo municipal."
            )
        media = float(modelo["stats"].loc[m, "mean"])
        limite = modelo["ranges_log"].loc[m]
        log_x = float(np.clip(row["LOG_AREA"], limite["xmin"], limite["xmax"]))
        diferencia = log_x - float(modelo["means_log"].loc[m])
        preds.append(media + modelo["beta"] * modelo["scales"][m] * diferencia)
    return np.asarray(preds, dtype=float)


def crear_filas(valid, pred, split):
    rows = []
    for (_, r), yhat in zip(valid.iterrows(), pred):
        real = float(r[Y])
        error = float(yhat - real)
        rows.append({
            "SPLIT": split, ID: r[ID], MUNI: r[MUNI], AREA: float(r[AREA]),
            "REAL_T_HA": real, "PREDICHO_T_HA": float(yhat),
            "ERROR_PRED_MENOS_REAL_T_HA": error,
            "ERROR_ABSOLUTO_T_HA": abs(error),
            "ERROR_CUADRATICO": error ** 2,
            "ERROR_ABSOLUTO_PCT": 100 * abs(error) / abs(real) if abs(real) > 1e-12 else np.nan,
            "DIRECCION": "SOBREESTIMA" if error > 1e-12 else (
                "SUBESTIMA" if error < -1e-12 else "EXACTO"),
        })
    return rows


def evaluar_splits(train, archivo):
    s = pd.read_csv(archivo, encoding="utf-8-sig")
    faltantes = {ID, "SPLIT", "ROLE"} - set(s.columns)
    if faltantes:
        raise ValueError(f"El archivo de splits no tiene: {sorted(faltantes)}")
    s[ID] = s[ID].astype(str).str.strip()
    s["ROLE"] = s["ROLE"].astype(str).str.strip().str.upper()
    if not s["ROLE"].isin(["TRAIN", "VALID"]).all():
        raise ValueError("ROLE debe ser TRAIN o VALID.")
    grupos = sorted(s["SPLIT"].unique())
    if len(grupos) != 50:
        raise ValueError(f"Se esperaban 50 splits congelados; hay {len(grupos)}.")
    known = set(train[ID])
    if not set(s[ID]).issubset(known):
        raise ValueError("El CSV de splits incluye parcelas no presentes en TRAIN.")

    detalle, rmse_split = [], []
    for k, nombre in enumerate(grupos, 1):
        ss = s[s["SPLIT"] == nombre]
        entrenar = set(ss.loc[ss["ROLE"] == "TRAIN", ID])
        validar = set(ss.loc[ss["ROLE"] == "VALID", ID])
        if entrenar & validar:
            raise ValueError(f"Split {nombre}: mismos IDs en TRAIN y VALID.")
        if not validar or not entrenar:
            raise ValueError(f"Split {nombre}: partición vacía.")
        tr = train[train[ID].isin(entrenar)]
        va = train[train[ID].isin(validar)]
        pred = predecir_modelo(ajustar_modelo(tr), va)
        detalle.extend(crear_filas(va, pred, str(nombre)))
        rmse_split.append(float(np.sqrt(np.mean((pred - va[Y].to_numpy(dtype=float))**2))))
        if k % 10 == 0:
            print(f"Validaciones originales: {k}/50")
    return pd.DataFrame(detalle), rmse_split


def evaluar_loo(train):
    """LOO: una predicción genuinamente fuera de muestra por parcela evaluable.

    Municipios con un único TRAIN se dejan sin evaluación; NO se inventa
    un fallback que cambiaría el modelo campeón.
    """
    muni_counts = train.groupby(MUNI)[ID].transform("count")
    elegibles = train.loc[muni_counts >= 2]
    detalle = []
    for n, (_, row) in enumerate(elegibles.iterrows(), 1):
        valid = train.loc[train[ID] == row[ID]]
        tr = train.loc[train[ID] != row[ID]]
        pred = predecir_modelo(ajustar_modelo(tr), valid)
        detalle.extend(crear_filas(valid, pred, f"LOO_{row[ID]}"))
        if n % 25 == 0:
            print(f"LOO: {n}/{len(elegibles)}")
    return pd.DataFrame(detalle), []


def agrupar_por_parcela(train, detalle):
    resumen_rows = []
    for poligono, grupo in detalle.groupby(ID, sort=False):
        errores = grupo["ERROR_PRED_MENOS_REAL_T_HA"].to_numpy(dtype=float)
        abs_e = np.abs(errores)
        resumen_rows.append({
            ID: poligono,
            "N_VALIDACIONES": len(grupo),
            "PRED_MEDIA_OOF_T_HA": float(grupo["PREDICHO_T_HA"].mean()),
            "ERROR_MEDIO_T_HA": float(np.mean(errores)),
            "MAE_PARCELA_T_HA": float(np.mean(abs_e)),
            "RMSE_PARCELA_T_HA": float(np.sqrt(np.mean(errores**2))),
            "ERROR_ABSOLUTO_PCT_MEDIO": float(grupo["ERROR_ABSOLUTO_PCT"].mean()),
            "SSE_PARCELA": float(np.sum(errores**2)),
        })
    res = pd.DataFrame(resumen_rows)
    tabla = train[[ID, MUNI, AREA, Y]].rename(columns={Y: "REAL_T_HA"}).merge(
        res, on=ID, how="left", validate="one_to_one")
    tabla["ESTADO"] = np.where(tabla["N_VALIDACIONES"].isna(),
                                 "NO_EVALUABLE_MUNICIPIO_SIN_PARES", "EVALUADA")
    tabla["DIRECCION_PROMEDIO"] = np.where(
        tabla["ESTADO"] != "EVALUADA", "SIN_EVALUAR",
        np.where(tabla["ERROR_MEDIO_T_HA"] > 1e-12, "SOBREESTIMA",
                 np.where(tabla["ERROR_MEDIO_T_HA"] < -1e-12, "SUBESTIMA", "EXACTO")))
    tabla = tabla.sort_values(["RMSE_PARCELA_T_HA", ID], ascending=[False, True],
                              na_position="last")
    return tabla


def resumen_municipal(detalle):
    rows = []
    for m, g in detalle.groupby(MUNI):
        e = g["ERROR_PRED_MENOS_REAL_T_HA"].to_numpy(dtype=float)
        rows.append({MUNI: m, "N_PARCELAS_EVALUADAS": g[ID].nunique(),
                     "N_PREDICCIONES_OOF": len(g),
                     "MAE_OOF_T_HA": float(np.mean(np.abs(e))),
                     "RMSE_OOF_T_HA": float(np.sqrt(np.mean(e**2))),
                     "SESGO_PRED_MENOS_REAL_T_HA": float(np.mean(e))})
    return pd.DataFrame(rows).sort_values("RMSE_OOF_T_HA", ascending=False)


def guardar_csv(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")


def main():
    root, master_file = buscar_maestro()
    train, pred_set = preparar_maestro(master_file)
    splits_file = buscar_splits(root)
    if MODO not in ["AUTO", "SPLITS_50", "LOO"]:
        raise ValueError("MODO debe ser AUTO, SPLITS_50 o LOO.")
    if MODO == "SPLITS_50" and splits_file is None:
        raise FileNotFoundError("MODO=SPLITS_50 exige splits_50_ids_EXACTOS.csv.")
    usar_splits = (MODO == "SPLITS_50") or (MODO == "AUTO" and splits_file is not None)
    metodo = "50_SPLITS_ORIGINALES" if usar_splits else "LOO_ALTERNATIVO"
    out = root / OUT_NAME
    out.mkdir(exist_ok=True)

    print("=" * 74)
    print("AUDITORÍA DEL MODELO CAMPEÓN — CEBADA")
    print("=" * 74)
    print("Maestro:", master_file)
    print("Entrenamiento:", len(train), "| Sin rendimiento:", len(pred_set))
    print("Método:", metodo)
    print("Salida:", out)

    if usar_splits:
        print("Archivo de particiones:", splits_file)
        detalle, por_fold = evaluar_splits(train, splits_file)
    else:
        print("AVISO: no se encontró archivo de 50 splits; usaré LOO.")
        print("LOO es una evaluación DIFERENTE. NO permite reproducir RMSE 0.481502.")
        detalle, por_fold = evaluar_loo(train)

    if detalle.empty:
        raise RuntimeError("Ninguna parcela pudo evaluarse.")

    tabla = agrupar_por_parcela(train, detalle)
    muni = resumen_municipal(detalle)
    errores = detalle["ERROR_PRED_MENOS_REAL_T_HA"].to_numpy(dtype=float)
    rmse_pooled = float(np.sqrt(np.mean(errores**2)))
    mae_pooled = float(np.mean(np.abs(errores)))
    rmse_medio_folds = float(np.mean(por_fold)) if por_fold else np.nan
    diferencia_referencia = rmse_medio_folds - RMSE_REFERENCIA_50 if por_fold else np.nan
    coincide = bool(abs(diferencia_referencia) <= TOLERANCIA_REFERENCIA) if por_fold else False
    resumen = pd.DataFrame([{
        "METODO": metodo,
        "N_ENTRENAMIENTO": len(train),
        "N_PREDICCION_SIN_Y": len(pred_set),
        "N_PARCELAS_EVALUADAS": int(detalle[ID].nunique()),
        "N_PARCELAS_NO_EVALUABLES": int(tabla["ESTADO"].ne("EVALUADA").sum()),
        "N_PREDICCIONES_OOF": len(detalle),
        "MAE_OOF_T_HA": mae_pooled,
        "RMSE_POOLED_OOF_T_HA": rmse_pooled,
        "RMSE_MEDIO_50_FOLDS_T_HA": rmse_medio_folds,
        "RMSE_REFERENCIA_OFICIAL": RMSE_REFERENCIA_50 if usar_splits else np.nan,
        "DIFERENCIA_RMSE_REFERENCIA": diferencia_referencia,
        "REPRODUCE_RMSE_OFICIAL": coincide if usar_splits else "NO_APLICA",
    }])

    guardar_csv(tabla, out / "01_Tabla_Errores_Por_Parcela.csv")
    guardar_csv(resumen, out / "02_Resumen_Metricas.csv")
    guardar_csv(muni, out / "03_Errores_Por_Municipio.csv")
    guardar_csv(detalle, out / "04_Predicciones_Validacion_Detalladas.csv")
    guardar_csv(tabla[tabla["ESTADO"] == "EVALUADA"].head(11),
                out / "05_Top11_Parcelas_Dificiles.csv")

    print("\nRESULTADOS")
    print(f"Parcelas evaluadas: {detalle[ID].nunique()} / {len(train)}")
    print(f"Predicciones fuera de muestra: {len(detalle)}")
    print(f"MAE OOF: {mae_pooled:.6f} t/ha")
    print(f"RMSE pooled OOF: {rmse_pooled:.6f} t/ha")
    if usar_splits:
        print(f"RMSE MEDIO DE 50 FOLDS: {rmse_medio_folds:.6f} t/ha")
        if coincide:
            print("SANITY CHECK: reproduce la métrica oficial 0.481502 (redondeada).")
        else:
            print("ALERTA: RMSE diferente a 0.481502; verificar maestro y splits.")
            print("NO llamar oficial a esta evaluación hasta resolverlo.")
    else:
        print("NO es comparable directamente al benchmark oficial de 50 splits.")
    print("\nTOP 11 de mayor RMSE por parcela:")
    print(tabla[[ID, MUNI, "REAL_T_HA", "PRED_MEDIA_OOF_T_HA",
                 "ERROR_MEDIO_T_HA", "RMSE_PARCELA_T_HA", "N_VALIDACIONES"]]
          .head(11).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    sin_eval = tabla[tabla["ESTADO"] != "EVALUADA"]
    if not sin_eval.empty:
        print("\nSin evaluación (único entrenamiento en municipio):", ", ".join(sin_eval[ID]))
    print("\nTABLAS GUARDADAS EN:", out)
    print("\nNOTA: los 59 casos PREDICCION no tienen rendimiento real:")
    print("sus errores no se pueden calcular con el CSV de envío.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:", exc, file=sys.stderr)
        raise
