#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepara datos locales del tablero AgroCebada.
Lee insumos sin modificarlos, ejecuta copias de los scripts predictivos originales,
calcula métricas y exporta JSON/GeoJSON para la página Vue.
Requiere pandas y numpy. No requiere GeoPandas para convertir PolygonZ.
"""
from pathlib import Path
import csv
import json
import math
import shutil
import struct
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "Base_De_Datos"
SCRIPTS = ROOT / "Prediccion_Errores"
WEB = ROOT / "Dashboard_AgroCebada"
PUBLIC_DATA = WEB / "public" / "data"
RUN = SCRIPTS / "ejecucion_dashboard"
ID = "ID_POLIGONO"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Falta el insumo requerido: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def clean_value(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def copy_sources_and_run_originals():
    """Run the supplied scripts unmodified in a self-contained working directory."""
    RUN.mkdir(parents=True, exist_ok=True)
    cebada = DATA / "Cebada_197.csv"
    splits = DATA / "splits_50_ids_EXACTOS.csv"
    if not cebada.exists() or not splits.exists():
        raise FileNotFoundError("Faltan Cebada_197.csv o splits_50_ids_EXACTOS.csv en Base_De_Datos")
    shutil.copy2(cebada, RUN / "Cebada_197.csv")
    shutil.copy2(cebada, RUN / "Master_Cebada_197.csv")
    shutil.copy2(splits, RUN / "splits_50_ids_EXACTOS.csv")
    for name in ("Generar_Prediccion_Cebada.py", "Errores_Cebada_197.py"):
        source = SCRIPTS / name
        if not source.exists():
            raise FileNotFoundError(f"Falta el script original: {source}")
        shutil.copy2(source, RUN / name)
    logs=[]
    for name in ("Errores_Cebada_197.py", "Generar_Prediccion_Cebada.py"):
        proc = subprocess.run([sys.executable, str(RUN / name)], cwd=RUN,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        logs.append(f"===== {name} (código {proc.returncode}) =====\n{proc.stdout}\n{proc.stderr}")
        if proc.returncode:
            raise RuntimeError(f"Falló {name}. Revisa {RUN / 'log_ejecucion.txt'}\n{proc.stderr[-2500:]}")
    (RUN / "log_ejecucion.txt").write_text("\n".join(logs), encoding="utf-8")
    pred_src = RUN / "Prediccion_Final_Cebada" / "Predicciones_59_Detalladas.csv"
    err_src = RUN / "Tabla_Errores_Cebada" / "01_Tabla_Errores_Por_Parcela.csv"
    metric_src = RUN / "Tabla_Errores_Cebada" / "02_Resumen_Metricas.csv"
    for source, name in ((pred_src,"predicciones_59_metodo_original.csv"),
                         (err_src,"errores_parcela_validacion.csv"),
                         (metric_src,"metricas_validacion_50_splits.csv")):
        if not source.exists():
            raise FileNotFoundError(f"El script no generó {source}")
        shutil.copy2(source, DATA / name)
    return pred_src, err_src, metric_src


def read_dbf(path):
    raw=path.read_bytes()
    record_count=struct.unpack_from("<I",raw,4)[0]
    header_len=struct.unpack_from("<H",raw,8)[0]
    record_len=struct.unpack_from("<H",raw,10)[0]
    cpg=path.with_suffix(".cpg")
    encoding=cpg.read_text(encoding="ascii",errors="ignore").strip() if cpg.exists() else "UTF-8"
    fields=[]; pos=32
    while pos < len(raw) and raw[pos] != 0x0D:
        desc=raw[pos:pos+32]
        if len(desc)<32: break
        name=desc[:11].split(b"\0",1)[0].decode("ascii","ignore").strip()
        ftype=chr(desc[11]); length=desc[16]; decimals=desc[17]
        fields.append((name,ftype,length,decimals)); pos+=32
    rows=[]
    for idx in range(record_count):
        rec=raw[header_len+idx*record_len:header_len+(idx+1)*record_len]
        if len(rec)!=record_len or rec[:1]==b"*":
            continue
        off=1; row={}
        for name,ftype,length,decimals in fields:
            value=rec[off:off+length].decode(encoding,errors="replace").strip(); off+=length
            if not value:
                row[name]=None
            elif ftype in ("N","F"):
                try: row[name]=int(value) if decimals==0 and "." not in value else float(value)
                except ValueError: row[name]=None
            elif ftype=="L":
                row[name]=value.upper() in ("Y","T")
            else:
                row[name]=value
        rows.append(row)
    if len(rows)!=record_count:
        raise ValueError(f"DBF: {record_count} filas declaradas, {len(rows)} leídas")
    return rows


def read_polygonz_shp(path):
    """Read XY rings from the provided ESRI PolygonZ (shape type 15) file."""
    raw=path.read_bytes()
    if len(raw)<100 or struct.unpack_from(">i",raw,0)[0] != 9994:
        raise ValueError("Encabezado shapefile inválido")
    declared_type=struct.unpack_from("<i",raw,32)[0]
    if declared_type not in (5,15):
        raise ValueError(f"Se esperaba Polygon/PolygonZ, se encontró tipo {declared_type}")
    features=[]; off=100
    while off < len(raw):
        rec_no, word_len=struct.unpack_from(">2i",raw,off)
        size=word_len*2
        content=memoryview(raw)[off+8:off+8+size]
        if len(content)!=size: raise ValueError(f"Registro geométrico truncado: {rec_no}")
        typ=struct.unpack_from("<i",content,0)[0]
        if typ==0:
            features.append(None); off+=8+size; continue
        if typ not in (5,15): raise ValueError(f"Tipo geométrico inesperado {typ} en registro {rec_no}")
        n_parts,n_points=struct.unpack_from("<2i",content,36)
        parts=struct.unpack_from("<"+"i"*n_parts,content,44) if n_parts else ()
        points_off=44+4*n_parts
        raw_points=struct.unpack_from("<"+"d"*(2*n_points),content,points_off) if n_points else ()
        points=[(raw_points[i],raw_points[i+1]) for i in range(0,len(raw_points),2)]
        ends=list(parts[1:])+[n_points]
        rings=[]
        for start,end in zip(parts,ends):
            ring=[[float(x),float(y)] for x,y in points[start:end]]
            if ring and ring[0]!=ring[-1]: ring.append(ring[0])
            if len(ring)>=4: rings.append(ring)
        features.append({"type":"Polygon","coordinates":rings} if rings else None)
        off+=8+size
    return features


def build_method_predictions(df):
    """Exact formula used by the supplied Generar_Prediccion_Cebada.py."""
    area="AREA_HA"; y="RENDIMIENTO_T_HA"; muni="Municipio"; split="CONJUNTO"
    d=df.copy()
    for c in (ID,muni,split): d[c]=d[c].astype(str).str.strip()
    d[area]=pd.to_numeric(d[area],errors="coerce"); d[y]=pd.to_numeric(d[y],errors="coerce")
    if d[area].isna().any() or (d[area]<=0).any(): raise ValueError("AREA_HA inválida")
    train=d[d[split].str.upper().eq("ENTRENAMIENTO")].copy()
    test=d[d[split].str.upper().eq("PREDICCION")].copy()
    train["LOG_AREA"]=np.log(train[area]); test["LOG_AREA"]=np.log(test[area])
    stats=train.groupby(muni)[y].agg(n="count",mean="mean",std="std",min="min",max="max")
    log_mean=train.groupby(muni)["LOG_AREA"].mean()
    ranges=train.groupby(muni)["LOG_AREA"].agg(xmin="min",xmax="max")
    eligible=stats.index[(stats.n>=5)&(stats["std"]>=0.05)].tolist()
    if not eligible: raise ValueError("No hay municipios suficientes para el ajuste de área")
    sub=train[train[muni].isin(eligible)].copy()
    xc=sub["LOG_AREA"]-sub[muni].map(log_mean); yc=sub[y]-sub[muni].map(stats["mean"])
    denom=float(np.sum(xc.to_numpy(float)**2))
    if denom<=1e-12: raise ValueError("Variación insuficiente para estimar beta")
    beta_raw=float(np.sum(xc.to_numpy(float)*yc.to_numpy(float))/denom)
    beta=0.75*beta_raw
    std_ref=float(stats.loc[eligible,"std"].median())
    out=[]
    for _,row in test.iterrows():
        m=row[muni]
        if m not in stats.index: raise ValueError(f"Municipio sin entrenamiento: {m}")
        stat=stats.loc[m]; rg=ranges.loc[m]
        logx=float(np.clip(row["LOG_AREA"],rg.xmin,rg.xmax))
        scale=min(1.0,float(stat["std"]/std_ref)) if stat.n>=5 and pd.notna(stat["std"]) and stat["std"]>=0.05 else 0.0
        raw=float(stat["mean"]+beta*scale*(logx-float(log_mean.loc[m])))
        pred=float(np.clip(raw,stat["min"],stat["max"]))
        out.append({ID:row[ID],"PREDICCION_T_HA":pred,"MEDIA_MUNICIPAL":float(stat["mean"]),
                    "N_TRAIN_MUNICIPIO":int(stat.n),"CORRECCION_AREA":float(pred-stat["mean"]),
                    "FUENTE":"MODELO_MUNICIPIO_AREA"})
    return pd.DataFrame(out)


def main():
    PUBLIC_DATA.mkdir(parents=True,exist_ok=True)
    pred_path,err_path,metric_path=copy_sources_and_run_originals()
    ceb=read_csv(DATA/"Cebada_197.csv")
    master=read_csv(DATA/"tabla_maestra_modelo_v2.csv")
    monthly=read_csv(DATA/"candidatos_temporales_mensuales.csv")
    climate=read_csv(DATA/"clima_bilineal_candidato.csv")
    cv_errors=read_csv(err_path)
    cv_metric=read_csv(metric_path).iloc[0].to_dict()
    predictions=read_csv(pred_path)
    pred_verify=build_method_predictions(ceb)
    exact=predictions[[ID,"PREDICCION_T_HA"]].merge(pred_verify,on=ID,suffixes=("_script","_replica"),validate="one_to_one")
    maxdiff=float((pd.to_numeric(exact.PREDICCION_T_HA_script)-pd.to_numeric(exact.PREDICCION_T_HA_replica)).abs().max())
    if maxdiff>1e-6: raise ValueError(f"La réplica del método difiere del script por {maxdiff}")

    # Join municipal/state attributes to the actual tested model outputs by parcel ID.
    for d in (ceb,master,monthly,climate,cv_errors,predictions):
        if ID in d: d[ID]=d[ID].astype(str).str.strip()
    for frame,label in ((ceb,"Cebada"),(master,"Modelo v2")):
        if frame[ID].duplicated().any(): raise ValueError(f"IDs duplicados en {label}")
    if set(ceb[ID])!=set(master[ID]) or len(ceb)!=197 or len(master)!=197:
        raise ValueError("Los CSV deben contener exactamente las mismas 197 parcelas")
    source=data=ceb.merge(master.drop(columns=["AREA_HA","RENDIMIENTO_T_HA","CONJUNTO"]),on=ID,
                          how="inner",validate="one_to_one",suffixes=("","_v2"))
    source=source.merge(predictions[[ID,"PREDICCION_T_HA"]],on=ID,how="left",validate="one_to_one")
    source["AREA_HA"]=pd.to_numeric(source["AREA_HA"],errors="coerce")
    source["RENDIMIENTO_T_HA"]=pd.to_numeric(source["RENDIMIENTO_T_HA"],errors="coerce")
    source["RENDIMIENTO_MOSTRADO_T_HA"]=source["RENDIMIENTO_T_HA"].where(source["RENDIMIENTO_T_HA"].notna(),source["PREDICCION_T_HA"])
    source["FUENTE_RENDIMIENTO"]=np.where(source["RENDIMIENTO_T_HA"].notna(),"Observado","Estimado")
    source["PRODUCCION_ESTIMADA_T"]=source["AREA_HA"]*source["RENDIMIENTO_MOSTRADO_T_HA"]

    attributes=read_dbf(DATA/"parcelas.dbf")
    geometries=read_polygonz_shp(DATA/"parcelas.shp")
    if len(attributes)!=197 or len(geometries)!=197: raise ValueError("La capa espacial debe tener 197 filas y geometrías")
    spatial=pd.DataFrame(attributes)
    required={"ID_POLIGON","Municipio","Estado","CONJUNTO"}
    if required-set(spatial.columns): raise ValueError(f"Campos espaciales faltantes: {sorted(required-set(spatial.columns))}")
    spatial=spatial.rename(columns={"ID_POLIGON":ID,"Municipio":"Municipio_GEO","Estado":"Estado","CONJUNTO":"CONJUNTO_GEO"})
    spatial[ID]=spatial[ID].astype(str).str.strip()
    spatial["geometry"]=geometries
    if spatial[ID].duplicated().any() or set(spatial[ID])!=set(source[ID]): raise ValueError("Los IDs del shapefile no coinciden con los CSV")
    source=source.merge(spatial[[ID,"Municipio_GEO","Estado","CONJUNTO_GEO","geometry"]],on=ID,validate="one_to_one")
    mismatch=source["Municipio"].fillna("").astype(str).str.strip()!=source["Municipio_GEO"].fillna("").astype(str).str.strip()
    if mismatch.any(): raise ValueError(f"Municipios no coinciden para IDs: {source.loc[mismatch,ID].tolist()[:8]}")
    mismatch=source["CONJUNTO"].fillna("").astype(str).str.upper()!=source["CONJUNTO_GEO"].fillna("").astype(str).str.upper()
    if mismatch.any(): raise ValueError("CONJUNTO no coincide entre DBF y CSV")

    cv_errors=cv_errors.sort_values("RMSE_PARCELA_T_HA",ascending=False)
    anomaly_ids=set(cv_errors.head(11)[ID].astype(str))
    cvcols=[ID,"N_VALIDACIONES","PRED_MEDIA_OOF_T_HA","ERROR_MEDIO_T_HA","MAE_PARCELA_T_HA","RMSE_PARCELA_T_HA","ERROR_ABSOLUTO_PCT_MEDIO","ESTADO"]
    cv_available=[c for c in cvcols if c in cv_errors.columns]
    source=source.merge(cv_errors[cv_available].drop_duplicates(ID),on=ID,how="left",validate="one_to_one")
    source["ES_DIFICIL_PREDICCION"]=source[ID].isin(anomaly_ids)

    # Parcel records used by the application and GeoJSON polygons used by the SVG map.
    parcels=[]; features=[]
    for _,r in source.iterrows():
        props={
            "id":str(r[ID]),"estado":str(r["Estado"]),"municipio":str(r["Municipio_GEO"]),
            "areaHa":clean_value(r["AREA_HA"]),"rendimientoTHa":clean_value(r["RENDIMIENTO_MOSTRADO_T_HA"]),
            "rendimientoObservadoTHa":clean_value(r["RENDIMIENTO_T_HA"]),"rendimientoEstimadoTHa":clean_value(r["PREDICCION_T_HA"]),
            "fuenteRendimiento":str(r["FUENTE_RENDIMIENTO"]),"produccionEstimadaT":clean_value(r["PRODUCCION_ESTIMADA_T"]),
            "ndviMax":clean_value(r.get("NDVI_max")),"ndviMean":clean_value(r.get("NDVI_mean")),
            "elevacionM":clean_value(r.get("elevacion_media_m")),"pendienteGrados":clean_value(r.get("pendiente_media_grados")),
            "cvNValidaciones":clean_value(r.get("N_VALIDACIONES")),"cvRmseTHa":clean_value(r.get("RMSE_PARCELA_T_HA")),
            "cvMaeTHa":clean_value(r.get("MAE_PARCELA_T_HA")),"cvErrorMedioTHa":clean_value(r.get("ERROR_MEDIO_T_HA")),
            "dificilPrediccion":bool(r["ES_DIFICIL_PREDICCION"]),"conjunto":str(r["CONJUNTO"])
        }
        parcels.append(props)
        geom=r["geometry"]
        if not geom: raise ValueError(f"Geometría vacía para {r[ID]}")
        features.append({"type":"Feature","geometry":geom,"properties":props})
    geojson={"type":"FeatureCollection","name":"parcelas_agrocebada","crs":{"type":"name","properties":{"name":"EPSG:4326"}},"features":features}
    (PUBLIC_DATA/"parcelas.geojson").write_text(json.dumps(geojson,ensure_ascii=False,separators=(",",":")),encoding="utf-8")

    # Monthly candidate indices plus bilinear weather summaries (April–October 2025).
    month_labels={4:"Abr",5:"May",6:"Jun",7:"Jul",8:"Ago",9:"Sep",10:"Oct"}
    m=monthly.set_index(ID); c=climate.set_index(ID)
    month_rows=[]
    for pid in source[ID].astype(str):
        for month,label in month_labels.items():
            def get_num(frame,key):
                return clean_value(frame.loc[pid,key]) if pid in frame.index and key in frame.columns else None
            def climate_num(base):
                key=f"{base}_{month:02d}_bilineal"
                if key not in c.columns: key=f"{base}_{month:02d}"
                return get_num(c,key)
            month_rows.append({"id":pid,"mes":month,"mesLabel":label,
                "planetNdvi":get_num(m,f"planet_ndvi_mes_{month:02d}"),
                "sentinel2Ndvi":get_num(m,f"sentinel2_ndvi_mes_{month:02d}"),
                "landsatVi6t":get_num(m,f"landsat_vi6t_mes_{month:02d}"),
                "precipitacionMm":climate_num("prec_mm"),"tmaxC":climate_num("tmax_c"),"tminC":climate_num("tmin_c")})

    observed=source[source["FUENTE_RENDIMIENTO"].eq("Observado")]
    estimated=source[source["FUENTE_RENDIMIENTO"].eq("Estimado")]
    total_area=float(source["AREA_HA"].sum())
    total_production=float(source["PRODUCCION_ESTIMADA_T"].sum())
    weighted_yield=total_production/total_area if total_area else None
    state_list=sorted(source["Estado"].dropna().astype(str).unique().tolist())
    muni_by_state={str(k):sorted(v.astype(str).unique().tolist()) for k,v in source.groupby("Estado")["Municipio_GEO"]}
    metrics={"parcelas":int(len(source)),"rendimientosObservados":int(len(observed)),"rendimientosEstimados":int(len(estimated)),
        "superficieTotalHa":total_area,"produccionTotalEstimadaT":total_production,
        "produccionObservadaT":float(observed["AREA_HA"].mul(observed["RENDIMIENTO_T_HA"]).sum()),
        "produccionEstimadasT":float(estimated["PRODUCCION_ESTIMADA_T"].sum()),
        "rendimientoPonderadoTHa":weighted_yield,"ndviMaxPromedio":clean_value(source["NDVI_max"].mean()),
        "ndviMeanPromedio":clean_value(source["NDVI_mean"].mean()),
        "parcelasDificilesTop11":int(len(anomaly_ids)),"parcelasConErrorCv":int(source["RMSE_PARCELA_T_HA"].notna().sum()),
        "parcelasSinErrorCv":int(source["RMSE_PARCELA_T_HA"].isna().sum())}
    cv_metrics={"metodo":"Municipio + área logarítmica (beta contraída)",
        "nSplits":50,"nValidaciones":int(cv_metric.get("N_PREDICCIONES_OOF",0)),
        "nParcelasEvaluadas":int(cv_metric.get("N_PARCELAS_EVALUADAS",0)),
        "maeTHa":clean_value(cv_metric.get("MAE_OOF_T_HA")),
        "rmsePooledTHa":clean_value(cv_metric.get("RMSE_POOLED_OOF_T_HA")),
        "rmseMedioSplitsTHa":clean_value(cv_metric.get("RMSE_MEDIO_50_FOLDS_T_HA")),
        "referenciaRmseTHa":clean_value(cv_metric.get("RMSE_REFERENCIA_OFICIAL"))}
    data={"metadata":{"titulo":"AgroCebada · Tablero de rendimiento","ciclo":"Abril–octubre de 2025",
            "fuenteClima":"CHIRPS y CHIRTS-ERA5; interpolación bilineal usada solo para la gráfica mensual",
            "fuenteTopografia":"INEGI CEM 4.0; variables por parcela procedentes de la tabla v2",
            "fuenteNDVI":"Resumen de temporada de Cebada_197.csv",
            "metodoPrediccion":"Se ejecuta el script Generar_Prediccion_Cebada.py sin modificar. Los 138 rendimientos observados se muestran como observados y los 59 restantes como estimados.",
            "fechaPreparacion":"2026-10-02","crs":"EPSG:4326"},
        "metricas":metrics,"validacion":cv_metrics,"estados":state_list,"municipiosPorEstado":muni_by_state,
        "parcelas":parcels,"mensual":month_rows,
        "anomalias":[p for p in parcels if p["dificilPrediccion"]],
        "fuentes":["Dataset Reto AgroCebada 2026","Planet (2025)","Sentinel-2 y Landsat (2022–2025)",
            "CHIRPS (precipitación mensual)","CHIRTS-ERA5 (temperatura)","INEGI CEM 4.0 (elevación y pendiente)"]}
    (PUBLIC_DATA/"dashboard.json").write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    # Document generated model outputs separately in Base_De_Datos as well as the web payload.
    print(f"Parcels: {len(parcels)}; observed: {len(observed)}; estimated: {len(estimated)}")
    print(f"States: {state_list}; area: {total_area:.2f} ha; production: {total_production:.2f} t")
    print(f"Prediction parity vs original script max abs diff: {maxdiff:.12g}")
    print(f"CV MAE/RMSE: {cv_metrics['maeTHa']} / {cv_metrics['rmseMedioSplitsTHa']} t/ha")
    print(f"Anomaly parcels: {len(anomaly_ids)}; GeoJSON features: {len(features)}")
    print("Dashboard data written to",PUBLIC_DATA)

if __name__=="__main__":
    main()
