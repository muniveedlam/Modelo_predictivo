# RAPL AgroTech

Tablero interactivo para analizar el rendimiento de cebada por estado, municipio y parcela.

## Carpetas principales

- Base_De_Datos: copias de los insumos de trabajo y archivos derivados.
- Prediccion_Errores: scripts originales del método y una carpeta aislada de ejecución.
- Dashboard_AgroCebada: sitio web basado en Vue/Vuetify, con los datos publicados en public/data.
- Base_Pagina: plantilla original conservada sin cambios.
- generar_datos_dashboard.py: regenera predicciones, validación cruzada y datos del tablero sin modificar los originales.

## Ejecutar en Windows desde VS Code

Abre C:\Users\edu12\Downloads\Modelo_predictivo en VS Code. En la terminal PowerShell ejecuta:

    cd C:\Users\edu12\Downloads\Modelo_predictivo
    python -m pip install pandas numpy
    python .\generar_datos_dashboard.py
    cd .\Dashboard_AgroCebada
    npm install
    npm run dev

Abre en el navegador la dirección local que muestre Vite, normalmente http://localhost:5173.

Para volver a generar los resultados después de reemplazar los datos o scripts, ejecuta otra vez python .\generar_datos_dashboard.py desde la carpeta principal y reinicia el servidor web.

## Qué muestra

- Filtros encadenados por estado, municipio e ID de parcela.
- Mapa de polígonos con control de zoom, enfoque de parcela y selección.
- Producción total, superficie, rendimiento ponderado y elevación.
- NDVI máximo y medio, series mensuales, precipitación y temperatura.
- Producción por municipio y rendimiento por estado.
- Parcelas de mayor error en validación cruzada, con MAE y RMSE del método.

El tablero distingue los 138 rendimientos observados de los 59 estimados. La producción total combina ambos grupos y debe interpretarse como una suma mixta. El error de validación solo se calcula donde existe rendimiento observado; no se puede medir el error real de las 59 parcelas estimadas sin etiquetas.

## Requisitos

- Python 3.10 o posterior con pandas y numpy.
- Node.js y npm.
- No se necesita GeoPandas para preparar el GeoJSON de las parcelas.
