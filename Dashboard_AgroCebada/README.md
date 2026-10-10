# RAPL AgroTech

Tablero local para explorar el rendimiento de cebada por estado, municipio y parcela.

Los datos que se muestran se preparan desde la carpeta principal del proyecto con generar_datos_dashboard.py. Para regenerarlos, sigue las instrucciones del README en C:\Users\edu12\Downloads\Modelo_predictivo.

## Iniciar el sitio

Desde esta carpeta, abre una terminal PowerShell y ejecuta:

    npm install
    npm run dev

Abre la dirección local que imprima Vite, normalmente http://localhost:5173.

La pantalla separa las 138 parcelas con rendimiento observado de las 59 con rendimiento estimado. El mapa permite elegir indicador, acercar, enfocar una parcela y volver a la vista completa.
