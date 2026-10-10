from pathlib import Path
import shutil

import pandas as pd

PHENOLOGY_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS_ROOT = PHENOLOGY_ROOT.parents[2]
DATASET_ROOT = DOWNLOADS_ROOT / "DataSet" / "DATASET_RETO_AGRO_2026"
MASTER_PATH = PHENOLOGY_ROOT / "Maestro_Cebada_197.csv"
TRAJECTORY_PATH = PHENOLOGY_ROOT / "02_Trayectorias_Temporales" / "04_Matriz_Trayectorias_138.csv"
GRAPH_OUTPUT = PHENOLOGY_ROOT / "Graficas"
DASHBOARD_OUTPUT = PHENOLOGY_ROOT.parents[1] / "Dashboard_AgroCebada" / "public" / "data" / "fenologia"
CLOUD_MAX = 20.0
SATELLITE_YEAR = 2025

SERIES = [
    ("PRO", "Planet", "NDVI", "ndvi_promedio"),
    ("PRO", "Planet", "EVI", "evi_promedio"),
    ("PRO", "Planet", "MSAVI", "msavi_promedio"),
    ("BASIC", "Sentinel-2", "NDVI", "ndvi_promedio"),
    ("BASIC", "Sentinel-2", "EVI", "evi_promedio"),
]
TRAJECTORIES = [
    ("PRO", "NDVI"),
    ("PRO", "EVI"),
    ("PRO", "MSAVI"),
    ("BASIC", "NDVI"),
    ("BASIC", "EVI"),
]


def period_from_date(dates: pd.Series) -> pd.Series:
    month = dates.dt.month
    day = dates.dt.day
    dekad = pd.Series(1, index=dates.index, dtype="int64")
    dekad.loc[day.between(11, 20)] = 2
    dekad.loc[day.ge(21)] = 3
    return ((month - 4) * 3 + dekad).where(month.between(4, 10))


def period_label(period: int) -> str:
    months = ["Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct"]
    month_index = (int(period) - 1) // 3
    dekad = (int(period) - 1) % 3 + 1
    return f"{months[month_index]} {dekad}"


def load_source(path: Path, file_group: str, satellite: str, indices: list[tuple[str, str]]) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró la fuente satelital: {path}")
    value_columns = [column for _, column in indices]
    columns = list(dict.fromkeys(["ID_POLIGONO", "fecha_captura", "sensor", "porcentaje_nubosidad", *value_columns]))
    frame = pd.read_csv(path, usecols=columns, encoding="utf-8-sig", low_memory=False)
    frame["ID_POLIGONO"] = frame["ID_POLIGONO"].astype("string").str.strip()
    frame["sensor"] = frame["sensor"].astype("string").str.strip()
    frame = frame.loc[frame["sensor"].eq(satellite)].copy()
    frame["fecha"] = pd.to_datetime(frame["fecha_captura"], errors="coerce", dayfirst=True, format="mixed")
    frame = frame.loc[frame["fecha"].dt.year.eq(SATELLITE_YEAR)].copy()
    frame = frame.loc[frame["fecha"].dt.month.between(4, 10)].copy()
    cloud = pd.to_numeric(frame["porcentaje_nubosidad"], errors="coerce")
    frame = frame.loc[cloud.isna() | cloud.le(CLOUD_MAX)].copy()
    frame["PERIODO"] = period_from_date(frame["fecha"]).astype("Int64")
    frame = frame.loc[frame["PERIODO"].between(1, 21)].copy()

    pieces = []
    for index_name, value_column in indices:
        values = pd.to_numeric(frame[value_column], errors="coerce")
        part = frame[["ID_POLIGONO", "PERIODO"]].copy()
        part["VALOR"] = values
        part = part.dropna(subset=["ID_POLIGONO", "PERIODO", "VALOR"])
        part = part.groupby(["ID_POLIGONO", "PERIODO"], as_index=False, observed=True)["VALOR"].mean()
        part["GRUPO_FUENTE"] = file_group
        part["SENSOR"] = satellite
        part["INDICE"] = index_name
        pieces.append(part)
    if not pieces:
        return pd.DataFrame(columns=["ID_POLIGONO", "PERIODO", "VALOR", "GRUPO_FUENTE", "SENSOR", "INDICE"])
    return pd.concat(pieces, ignore_index=True)


def trajectory_features(matrix: pd.DataFrame) -> pd.DataFrame:
    rows = []
    feature_map = {
        "AUC_NORM": "AUC_NORM",
        "PEAK_PERIOD": "PERIODO_PICO",
        "AMPLITUDE": "AMPLITUD",
        "RISE_SLOPE": "PENDIENTE_SUBIDA",
        "DECLINE_SLOPE": "PENDIENTE_DESCENSO",
    }
    matrix["ID_POLIGONO"] = matrix["ID_POLIGONO"].astype("string").str.strip()
    for source_group, index_name in TRAJECTORIES:
        prefix = f"TRAJ__{source_group}__{index_name}__"
        source_columns = {target: f"{prefix}{source}" for source, target in feature_map.items()}
        absent = [column for column in source_columns.values() if column not in matrix.columns]
        if absent:
            raise ValueError(f"Faltan columnas del experimento temporal: {', '.join(absent)}")
        part = matrix[["ID_POLIGONO", *source_columns.values()]].copy()
        part = part.rename(columns={column: target for target, column in source_columns.items()})
        for column in feature_map.values():
            part[column] = pd.to_numeric(part[column], errors="coerce")
        part["SENSOR"] = source_group
        part["INDICE"] = index_name
        rows.append(part[["ID_POLIGONO", "SENSOR", "INDICE", *feature_map.values()]])
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    for path in (MASTER_PATH, TRAJECTORY_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró el archivo del modelo: {path}")

    master = pd.read_csv(MASTER_PATH, usecols=["ID_POLIGONO", "CONJUNTO", "Municipio"], encoding="utf-8-sig")
    master["ID_POLIGONO"] = master["ID_POLIGONO"].astype("string").str.strip()
    master["CONJUNTO"] = master["CONJUNTO"].astype("string").str.strip().str.upper()
    training = master.loc[master["CONJUNTO"].eq("ENTRENAMIENTO"), ["ID_POLIGONO", "Municipio"]].drop_duplicates("ID_POLIGONO").copy()
    training["Municipio"] = training["Municipio"].astype("string").str.strip()
    if len(training) != 138:
        raise ValueError(f"El maestro no contiene las 138 parcelas de entrenamiento esperadas; encontré {len(training)}.")
    training_ids = set(training["ID_POLIGONO"])

    pro_path = DATASET_ROOT / "Conjunto_datos_PRO_AgroCebada.csv"
    basic_path = DATASET_ROOT / "Conjunto_datos_BASICO_AgroCebada2026.csv"
    raw = pd.concat([
        load_source(pro_path, "PRO", "Planet", [("NDVI", "ndvi_promedio"), ("EVI", "evi_promedio"), ("MSAVI", "msavi_promedio")]),
        load_source(basic_path, "BASIC", "Sentinel-2", [("NDVI", "ndvi_promedio"), ("EVI", "evi_promedio")]),
    ], ignore_index=True)
    raw = raw.loc[raw["ID_POLIGONO"].isin(training_ids)].copy()
    if raw.empty:
        raise ValueError("No quedaron observaciones satelitales para las parcelas de entrenamiento.")

    expected = {(sensor, index) for _, sensor, index, _ in SERIES}
    found = set(zip(raw["SENSOR"], raw["INDICE"]))
    if expected - found:
        missing = sorted(expected - found)
        raise ValueError(f"La fuente no contiene estas series requeridas: {missing}")

    curves = raw.groupby(["SENSOR", "INDICE", "PERIODO"], as_index=False, observed=True).agg(
        VALOR_MEDIO=("VALOR", "mean"),
        N_PARCELAS=("ID_POLIGONO", "nunique"),
    )
    curves["ETIQUETA_PERIODO"] = curves["PERIODO"].map(period_label)
    curves = curves[["SENSOR", "INDICE", "PERIODO", "ETIQUETA_PERIODO", "N_PARCELAS", "VALOR_MEDIO"]]
    curves = curves.sort_values(["SENSOR", "INDICE", "PERIODO"], kind="stable")

    muni_n = training.groupby("Municipio", dropna=False)["ID_POLIGONO"].nunique()
    allowed_municipalities = set(muni_n.loc[muni_n.ge(5)].index.dropna())
    planet_curves = raw.loc[raw["SENSOR"].eq("Planet") & raw["INDICE"].isin(["EVI", "MSAVI"])].merge(
        training, on="ID_POLIGONO", how="inner", validate="many_to_one"
    )
    planet_curves = planet_curves.loc[planet_curves["Municipio"].isin(allowed_municipalities)].copy()
    municipal = planet_curves.groupby(["Municipio", "INDICE", "PERIODO"], as_index=False, observed=True).agg(
        N_PARCELAS_MUNICIPIO=("ID_POLIGONO", "nunique"),
        VALOR_MEDIO=("VALOR", "mean"),
    )
    municipal["ETIQUETA_PERIODO"] = municipal["PERIODO"].map(period_label)
    municipal = municipal[["Municipio", "INDICE", "PERIODO", "ETIQUETA_PERIODO", "N_PARCELAS_MUNICIPIO", "VALOR_MEDIO"]]
    municipal = municipal.sort_values(["Municipio", "INDICE", "PERIODO"], kind="stable")

    matrix = pd.read_csv(TRAJECTORY_PATH, encoding="utf-8-sig", low_memory=False)
    matrix["ID_POLIGONO"] = matrix["ID_POLIGONO"].astype("string").str.strip()
    matrix = matrix.loc[matrix["ID_POLIGONO"].isin(training_ids)].copy()
    features = trajectory_features(matrix)
    peaks = features.dropna(subset=["PERIODO_PICO"]).groupby(
        ["SENSOR", "INDICE", "PERIODO_PICO"], as_index=False, observed=True
    ).agg(N_PARCELAS=("ID_POLIGONO", "nunique"))
    peaks = peaks.sort_values(["SENSOR", "INDICE", "PERIODO_PICO"], kind="stable")
    features = features.sort_values(["SENSOR", "INDICE", "ID_POLIGONO"], kind="stable")

    outputs = {
        "10_Curvas_Prioritarias_Para_Graficas.csv": curves,
        "11_Curvas_Municipio_Prioritarias.csv": municipal,
        "06_Distribucion_Periodo_Pico.csv": peaks,
        "07_Features_Temporales_Por_Parcela.csv": features,
    }
    GRAPH_OUTPUT.mkdir(parents=True, exist_ok=True)
    DASHBOARD_OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        destination = GRAPH_OUTPUT / name
        frame.to_csv(destination, index=False, encoding="utf-8-sig")
        shutil.copy2(destination, DASHBOARD_OUTPUT / name)
        print(f"{name}: {len(frame)} filas")
    print(f"Ventana: abril-octubre de {SATELLITE_YEAR}; periodos de 10 días; nubosidad <= {CLOUD_MAX}% o sin dato.")
    print("Población: 138 parcelas de entrenamiento del maestro.")
    print(f"Municipios para la segunda curva: {len(allowed_municipalities)} (n>=5 parcelas de entrenamiento).")
    print(f"Base de datos: {GRAPH_OUTPUT}")
    print(f"Datos web: {DASHBOARD_OUTPUT}")


if __name__ == "__main__":
    main()
