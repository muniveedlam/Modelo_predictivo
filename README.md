RAPL AgroTech
Tablero interactivo para analizar el rendimiento de cebada, monitoreo fenológico multitemporal y contexto agroclimático por estado, municipio y parcela.

Carpetas principales
Base_De_Datos: copias de los insumos de trabajo, geometrías de parcelas, series climáticas y datos de trayectorias fenológicas decádicas.
Prediccion_Errores: scripts originales del método predictivo y validación cruzada con una carpeta aislada de ejecución.
Dashboard_AgroCebada: sitio web basado en Vue 3, Vuetify y Vite, con vistas de Tablero y Fenología, alimentado por datos publicados en public/data.
Base_Pagina: plantilla original conservada sin cambios.
generar_datos_dashboard.py: regenera predicciones, métricas de validación y datos del tablero sin modificar los archivos maestros.
Ejecutar en Windows desde VS Code
Abre C:\Users\edu12\Downloads\Modelo_predictivo en VS Code. En la terminal PowerShell ejecuta:

cd C:\Users\edu12\Downloads\Modelo_predictivo
python -m pip install pandas numpy
python .\generar_datos_dashboard.py
cd .\Dashboard_AgroCebada
npm install
npm run dev
Abre en el navegador la dirección local que muestre Vite, normalmente http://localhost:5173.

Para volver a generar los resultados después de reemplazar los datos o scripts, ejecuta otra vez python .\generar_datos_dashboard.py desde la carpeta principal y reinicia el servidor web.

Qué muestra
Tablero Principal (Rendimiento y Territorio)
Filtros encadenados por estado, municipio e ID de parcela.
Mapa vectorial interactivo con polígonos de las parcelas, capa satelital Esri, control de zoom y enfoque.
Métricas clave: producción total, superficie acumulada, rendimiento ponderado y elevación media.
NDVI máximo y medio, series mensuales satelitales (Planet y Sentinel-2).
Condiciones ambientales: gráfica combinada de precipitación y temperaturas (máxima y mínima) con selector para alternar entre el promedio general o el desglose por estado (General, Hidalgo, Puebla, Tlaxcala).
Distribución de la producción por municipio y rendimiento ponderado por estado.
Identificación de las 11 parcelas con mayor error en validación cruzada, junto con MAE y RMSE del método.
Módulo de Fenología Satelital
Curvas decádicas (periodos de 10 días entre abril y octubre de 2025) de índices satelitales prioritarios: Planet (NDVI, EVI, MSAVI) y Sentinel-2 (NDVI, EVI).
Comparativo territorial de trayectorias fenológicas (EVI / MSAVI) en municipios con al menos 5 parcelas de entrenamiento.
Distribución del periodo pico de vigor vegetativo según el sensor e índice seleccionado.
Tabla de rasgos temporales derivados por parcela: área bajo la curva normalizada (AUC_norm), periodo pico, amplitud, pendiente de subida (crecimiento) y pendiente de descenso (senescencia).
El tablero distingue los 138 rendimientos observados de los 59 estimados. La producción total combina ambos grupos y debe interpretarse como una suma mixta. El error de validación solo se calcula donde existe rendimiento observado; no se puede medir el error real de las 59 parcelas estimadas sin etiquetas.

Requisitos
Python 3.10 o posterior con pandas y numpy.
Node.js y npm.
No se necesita GeoPandas para preparar el GeoJSON de las parcelas.
