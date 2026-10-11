<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import VueApexCharts from 'vue3-apexcharts';
import { Plant2Icon } from 'vue-tabler-icons';

type CsvRow = Record<string, string>;
type CurveRow = { SENSOR: string; INDICE: string; PERIODO: number; ETIQUETA_PERIODO: string; N_PARCELAS: number; VALOR_MEDIO: number };
type MunicipalityRow = { Municipio: string; INDICE: string; PERIODO: number; ETIQUETA_PERIODO: string; N_PARCELAS_MUNICIPIO: number; VALOR_MEDIO: number };
type PeakRow = { SENSOR: string; INDICE: string; PERIODO_PICO: number; N_PARCELAS: number };
type FeatureRow = { ID_POLIGONO: string; SENSOR: string; INDICE: string; AUC_NORM: number | null; PERIODO_PICO: number | null; AMPLITUD: number | null; PENDIENTE_SUBIDA: number | null; PENDIENTE_DESCENSO: number | null };

const periods = Array.from({ length: 21 }, (_, index) => index + 1);
const periodNames = ['Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct'];
const periodLabel = (period: number) => `${periodNames[Math.floor((period - 1) / 3)]} ${(period - 1) % 3 + 1}`;
const numberValue = (value: string | undefined) => value === undefined || value.trim() === '' || !Number.isFinite(Number(value)) ? null : Number(value);

const loading = ref(true);
const loadError = ref('');
const priorityCurves = ref<CurveRow[]>([]);
const municipalityCurves = ref<MunicipalityRow[]>([]);
const peakDistribution = ref<PeakRow[]>([]);
const temporalFeatures = ref<FeatureRow[]>([]);
const selectedMunicipalIndex = ref('EVI');
const selectedFeatureKey = ref('PRO|NDVI');
const featurePage = ref(1);
const featurePageSize = 10;

function parseCsv(text: string): CsvRow[] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (inQuotes && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      row.push(field);
      field = '';
    } else if ((char === '\n' || char === '\r') && !inQuotes) {
      if (char === '\r' && text[index + 1] === '\n') index += 1;
      row.push(field);
      if (row.some((value) => value.length > 0)) rows.push(row);
      row = [];
      field = '';
    } else {
      field += char;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  const headers = rows.shift()?.map((header, index) => index === 0 ? header.replace(/^\uFEFF/, '').trim() : header.trim()) ?? [];
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ''])));
}

async function fetchCsv(filename: string): Promise<CsvRow[]> {
  const response = await fetch(`/data/fenologia/${filename}`);
  if (!response.ok) throw new Error(`No se pudo cargar ${filename}.`);
  return parseCsv(await response.text());
}

onMounted(async () => {
  try {
    const [curves, municipalities, peaks, features] = await Promise.all([
      fetchCsv('10_Curvas_Prioritarias_Para_Graficas.csv'),
      fetchCsv('11_Curvas_Municipio_Prioritarias.csv'),
      fetchCsv('06_Distribucion_Periodo_Pico.csv'),
      fetchCsv('07_Features_Temporales_Por_Parcela.csv')
    ]);
    priorityCurves.value = curves.map((row) => ({
      SENSOR: row.SENSOR,
      INDICE: row.INDICE,
      PERIODO: Number(row.PERIODO),
      ETIQUETA_PERIODO: row.ETIQUETA_PERIODO,
      N_PARCELAS: Number(row.N_PARCELAS),
      VALOR_MEDIO: Number(row.VALOR_MEDIO)
    }));
    municipalityCurves.value = municipalities.map((row) => ({
      Municipio: row.Municipio,
      INDICE: row.INDICE,
      PERIODO: Number(row.PERIODO),
      ETIQUETA_PERIODO: row.ETIQUETA_PERIODO,
      N_PARCELAS_MUNICIPIO: Number(row.N_PARCELAS_MUNICIPIO),
      VALOR_MEDIO: Number(row.VALOR_MEDIO)
    }));
    peakDistribution.value = peaks.map((row) => ({
      SENSOR: row.SENSOR,
      INDICE: row.INDICE,
      PERIODO_PICO: Number(row.PERIODO_PICO),
      N_PARCELAS: Number(row.N_PARCELAS)
    }));
    temporalFeatures.value = features.map((row) => ({
      ID_POLIGONO: row.ID_POLIGONO,
      SENSOR: row.SENSOR,
      INDICE: row.INDICE,
      AUC_NORM: numberValue(row.AUC_NORM),
      PERIODO_PICO: numberValue(row.PERIODO_PICO),
      AMPLITUD: numberValue(row.AMPLITUD),
      PENDIENTE_SUBIDA: numberValue(row.PENDIENTE_SUBIDA),
      PENDIENTE_DESCENSO: numberValue(row.PENDIENTE_DESCENSO)
    }));
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : 'No se pudieron cargar los datos de fenología.';
  } finally {
    loading.value = false;
  }
});

const prioritySpecs = [
  { sensor: 'Planet', index: 'NDVI', label: 'Planet · NDVI', color: '#277a52' },
  { sensor: 'Planet', index: 'EVI', label: 'Planet · EVI', color: '#d49a2a' },
  { sensor: 'Planet', index: 'MSAVI', label: 'Planet · MSAVI', color: '#5d9a70' },
  { sensor: 'Sentinel-2', index: 'NDVI', label: 'Sentinel-2 · NDVI', color: '#4e8db7' },
  { sensor: 'Sentinel-2', index: 'EVI', label: 'Sentinel-2 · EVI', color: '#9272b2' }
];
const prioritySeries = computed(() => prioritySpecs.map((spec) => ({
  name: spec.label,
  data: periods.map((period) => priorityCurves.value.find((row) => row.SENSOR === spec.sensor && row.INDICE === spec.index && row.PERIODO === period)?.VALOR_MEDIO ?? null)
})));
const priorityOptions = computed(() => ({
  chart: { type: 'line' as const, toolbar: { show: false }, fontFamily: 'Inter, sans-serif', zoom: { enabled: false } },
  colors: prioritySpecs.map((spec) => spec.color),
  stroke: { curve: 'smooth' as const, width: 3 },
  markers: { size: 3, strokeWidth: 0, hover: { size: 5 } },
  dataLabels: { enabled: false },
  grid: { borderColor: '#e9eee9', strokeDashArray: 4 },
  legend: { position: 'bottom' as const, fontSize: '12px', markers: { size: 5 } },
  xaxis: { categories: periods.map(periodLabel), tickPlacement: 'on', labels: { rotate: -35, style: { colors: '#718076', fontSize: '11px' } } },
  yaxis: { labels: { formatter: (value: number) => value.toFixed(2), style: { colors: '#718076' } }, title: { text: 'Valor medio del índice' } },
  tooltip: { shared: true, intersect: false }
}));

const municipalityNames = computed(() => [...new Set(municipalityCurves.value.filter((row) => row.INDICE === selectedMunicipalIndex.value).map((row) => row.Municipio))].sort((a, b) => a.localeCompare(b, 'es')));
const municipalityColors = ['#277a52', '#d49a2a', '#4e8db7', '#9272b2', '#db7956', '#5d9a70', '#7d8791', '#b07a9a'];
const municipalitySeries = computed(() => municipalityNames.value.map((municipality) => ({
  name: municipality,
  data: periods.map((period) => municipalityCurves.value.find((row) => row.Municipio === municipality && row.INDICE === selectedMunicipalIndex.value && row.PERIODO === period)?.VALOR_MEDIO ?? null)
})));
const municipalityOptions = computed(() => ({
  chart: { type: 'line' as const, toolbar: { show: false }, fontFamily: 'Inter, sans-serif', zoom: { enabled: false } },
  colors: municipalityColors,
  stroke: { curve: 'smooth' as const, width: 3 },
  markers: { size: 3, strokeWidth: 0, hover: { size: 5 } },
  dataLabels: { enabled: false },
  grid: { borderColor: '#e9eee9', strokeDashArray: 4 },
  legend: { position: 'bottom' as const, fontSize: '12px', markers: { size: 5 } },
  xaxis: { categories: periods.map(periodLabel), labels: { rotate: -35, style: { colors: '#718076', fontSize: '11px' } } },
  yaxis: { labels: { formatter: (value: number) => value.toFixed(2), style: { colors: '#718076' } }, title: { text: `${selectedMunicipalIndex.value} medio` } },
  tooltip: { shared: true, intersect: false }
}));

const trajectorySpecs = [
  { source: 'PRO', index: 'NDVI', label: 'PRO · NDVI' },
  { source: 'PRO', index: 'EVI', label: 'PRO · EVI' },
  { source: 'PRO', index: 'MSAVI', label: 'PRO · MSAVI' },
  { source: 'BASIC', index: 'NDVI', label: 'BASIC · NDVI' },
  { source: 'BASIC', index: 'EVI', label: 'BASIC · EVI' }
];
const peakSeries = computed(() => trajectorySpecs.map((spec) => ({
  name: spec.label,
  data: periods.map((period) => peakDistribution.value.find((row) => row.SENSOR === spec.source && row.INDICE === spec.index && row.PERIODO_PICO === period)?.N_PARCELAS ?? 0)
})));
const peakOptions = computed(() => ({
  chart: { type: 'bar' as const, toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
  colors: ['#277a52', '#d49a2a', '#5d9a70', '#4e8db7', '#9272b2'],
  plotOptions: { bar: { columnWidth: '62%', borderRadius: 3 } },
  dataLabels: { enabled: false },
  grid: { borderColor: '#e9eee9', strokeDashArray: 4 },
  legend: { position: 'bottom' as const, fontSize: '11px' },
  xaxis: { categories: periods.map(periodLabel), labels: { rotate: -45, style: { colors: '#718076', fontSize: '10px' } }, title: { text: 'Periodo de máximo espectral' } },
  yaxis: { min: 0, forceNiceScale: true, title: { text: 'Parcelas' }, labels: { style: { colors: '#718076' } } },
  tooltip: { shared: true, intersect: false }
}));

const featureChoices = trajectorySpecs.map((spec) => ({ title: spec.label, value: `${spec.source}|${spec.index}` }));
const filteredFeatures = computed(() => {
  const [source, index] = selectedFeatureKey.value.split('|');
  return temporalFeatures.value.filter((row) => row.SENSOR === source && row.INDICE === index).sort((a, b) => a.ID_POLIGONO.localeCompare(b.ID_POLIGONO, 'en', { numeric: true }));
});
const featurePageCount = computed(() => Math.max(1, Math.ceil(filteredFeatures.value.length / featurePageSize)));
const pagedFeatures = computed(() => filteredFeatures.value.slice((featurePage.value - 1) * featurePageSize, featurePage.value * featurePageSize));
watch(selectedFeatureKey, () => { featurePage.value = 1; });
const formatNumber = (value: number | null, digits = 3) => value === null ? '—' : value.toFixed(digits);

</script>

<template>
  <v-container fluid class="phenology-page">
    <header class="page-heading">
      <div class="heading-icon" aria-hidden="true"><Plant2Icon :size="28" :stroke-width="1.8" /></div>
      <div>
        <p class="eyebrow">RAPL AGROTECH</p>
        <h1>Fenología del Cultivo</h1>
        <p class="heading-description">Curvas satelitales y rasgos temporales de las parcelas de cebada.</p>
      </div>
    </header>

    <div v-if="loading" class="message-card">Cargando las curvas y características temporales…</div>
    <div v-else-if="loadError" class="message-card error-message">{{ loadError }}</div>
    <template v-else>
      <section class="phenology-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">SERIES PRIORITARIAS</p>
            <h2>Curvas satelitales</h2>
            <p class="section-description">Planet NDVI, EVI y MSAVI; Sentinel‑2 NDVI y EVI.</p>
          </div>
        </div>
        <v-card class="data-card" rounded="xl" elevation="0">
          <VueApexCharts type="line" height="340" :options="priorityOptions" :series="prioritySeries" />
          <p class="data-note">Promedios por parcela y periodo de 10 días (Mes/Etapa). Abril–octubre de 2025; nubosidad máxima de 20% cuando está disponible.</p>
        </v-card>
      </section>

      <section class="phenology-section">
        <div class="section-heading section-heading-controls">
          <div>
            <p class="eyebrow">COMPARATIVO TERRITORIAL</p>
            <h2>Curvas por municipio</h2>
            <p class="section-description">Planet EVI o MSAVI en municipios con al menos cinco parcelas de entrenamiento.</p>
          </div>
          <label class="select-label">Índice
            <select v-model="selectedMunicipalIndex" class="data-select">
              <option value="EVI">EVI</option>
              <option value="MSAVI">MSAVI</option>
            </select>
          </label>
        </div>
        <v-card class="data-card" rounded="xl" elevation="0">
          <VueApexCharts type="line" height="340" :options="municipalityOptions" :series="municipalitySeries" />
          <p class="data-note">El criterio n≥5 se calcula con parcelas del conjunto de entrenamiento. Se muestran los promedios por municipio y periodo (Mes/Etapa).</p>
        </v-card>
      </section>

      <section class="phenology-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">RASGOS TEMPORALES POR PARCELA</p>
            <h2>Distribución del pico y características de trayectoria</h2>
            <p class="section-description">La distribución del periodo pico y las cinco medidas por parcela del archivo de trayectorias del experimento.</p>
          </div>
        </div>
        <div class="combined-grid">
          <v-card class="data-card peak-card" rounded="xl" elevation="0">
            <h3>Periodo del máximo espectral</h3>
            <p class="card-description">Número de parcelas cuyo máximo ocurre en cada periodo.</p>
            <VueApexCharts type="bar" height="310" :options="peakOptions" :series="peakSeries" />
          </v-card>
          <v-card class="data-card features-card" rounded="xl" elevation="0">
            <div class="feature-header">
              <div>
                <h3>Características temporales</h3>
                <p class="card-description">AUC, periodo pico, amplitud y pendientes por parcela.</p>
              </div>
              <select v-model="selectedFeatureKey" class="data-select feature-select" aria-label="Fuente e índice">
                <option v-for="option in featureChoices" :key="option.value" :value="option.value">{{ option.title }}</option>
              </select>
            </div>
            <div class="table-scroll">
              <table class="feature-table">
                <thead>
                  <tr><th>Parcela</th><th>AUC</th><th>Pico</th><th>Amplitud</th><th>Subida</th><th>Descenso</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in pagedFeatures" :key="`${row.SENSOR}-${row.INDICE}-${row.ID_POLIGONO}`">
                    <td>{{ row.ID_POLIGONO }}</td>
                    <td>{{ formatNumber(row.AUC_NORM) }}</td>
                    <td>{{ row.PERIODO_PICO === null ? '—' : periodLabel(row.PERIODO_PICO) }}</td>
                    <td>{{ formatNumber(row.AMPLITUD) }}</td>
                    <td>{{ formatNumber(row.PENDIENTE_SUBIDA, 4) }}</td>
                    <td>{{ formatNumber(row.PENDIENTE_DESCENSO, 4) }}</td>
                  </tr>
                  <tr v-if="pagedFeatures.length === 0"><td colspan="6" class="empty-cell">Sin características disponibles para esta serie.</td></tr>
                </tbody>
              </table>
            </div>
            <div class="table-pagination">
              <span>{{ filteredFeatures.length }} parcelas</span>
              <div>
                <button type="button" :disabled="featurePage <= 1" @click="featurePage -= 1">Anterior</button>
                <span>{{ featurePage }} / {{ featurePageCount }}</span>
                <button type="button" :disabled="featurePage >= featurePageCount" @click="featurePage += 1">Siguiente</button>
              </div>
            </div>
          </v-card>
        </div>
        <p class="data-note section-note">Las columnas BASIC y PRO conservan los grupos de sensores definidos en el experimento; no se reinterpretan como sensores individuales.</p>
      </section>


         <!-- SECCIÓN 1: ¿PARA QUÉ SIRVE? (FLUJO DE 5 PASOS) -->
      <section class="phenology-section">
        <v-card class="info-card" rounded="xl" elevation="0">
          <div class="card-kicker">¿PARA QUÉ SIRVE?</div>
          <h2 class="card-main-title">Observación  e información </h2>
          <p class="card-subtitle">
            Seguir una parcela durante varios meses permite distinguir cultivos que podrían parecer similares en una sola fecha, pero que evolucionan de manera diferente.
          </p>

          <div class="flow-container">
            <div class="flow-box">
              <span class="step-num">01</span>
              <strong>Observaciones satelitales</strong>
            </div>
            <div class="flow-arrow">→</div>

            <div class="flow-box">
              <span class="step-num">02</span>
              <strong>Evolución en el tiempo</strong>
            </div>
            <div class="flow-arrow">→</div>

            <div class="flow-box">
              <span class="step-num">03</span>
              <strong>Medidas de la trayectoria</strong>
            </div>
            <div class="flow-arrow">→</div>

            <div class="flow-box">
              <span class="step-num">04</span>
              <strong>Clima y terreno</strong>
            </div>
            <div class="flow-arrow">→</div>

            <div class="flow-box">
              <span class="step-num">05</span>
              <strong>Estimación del rendimiento</strong>
            </div>
          </div>
        </v-card>
      </section>

      <!-- SECCIÓN 2: GLOSARIO RÁPIDO (TABLA DE MEDIDAS) -->
      <section class="phenology-section">
        <v-card class="info-card" rounded="xl" elevation="0">
          <div class="card-kicker">GLOSARIO RÁPIDO</div>
          <h2 class="card-main-title">Guía de Medidas</h2>

          <div class="glossary-list">
            <div class="glossary-item">
              <div class="glossary-term">AUC</div>
              <div class="glossary-def">
                <strong>Señal acumulada</strong>
                <p>Resume cuánto se mantuvo la señal durante el periodo observado.</p>
              </div>
            </div>

            <div class="glossary-item">
              <div class="glossary-term">Pico</div>
              <div class="glossary-def">
                <strong>Máximo espectral</strong>
                <p>Indica en qué periodo la parcela alcanzó el valor más alto del índice.</p>
              </div>
            </div>

            <div class="glossary-item">
              <div class="glossary-term">Amplitud</div>
              <div class="glossary-def">
                <strong>Rango de cambio</strong>
                <p>Diferencia entre el valor máximo y el mínimo de la trayectoria.</p>
              </div>
            </div>

            <div class="glossary-item">
              <div class="glossary-term">Subida</div>
              <div class="glossary-def">
                <strong>Velocidad de incremento</strong>
                <p>Describe qué tan rápido aumenta la señal antes del máximo.</p>
              </div>
            </div>

            <div class="glossary-item">
              <div class="glossary-term">Descenso</div>
              <div class="glossary-def">
                <strong>Velocidad de disminución</strong>
                <p>Describe qué tan rápido disminuye la señal después del máximo.</p>
              </div>
            </div>
          </div>
        </v-card>
      </section>

      <!-- SECCIÓN 3: RECORRIDO DE LECTURA (4 PREGUNTAS EN GRID) -->
      <section class="phenology-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">RECORRIDO DE LECTURA</p>
            <h2>Cuatro preguntas para entender las visualizaciones</h2>
            <p class="section-description">Cada gráfica responde una pregunta diferente.</p>
          </div>
        </div>

        <div class="reading-grid">
          <!-- Tarjeta 01 -->
          <v-card class="reading-card" rounded="xl" elevation="0">
            <div class="pill-badge">
              <span class="badge-num">01</span>
              <span>EVOLUCIÓN TEMPORAL</span>
            </div>
            <h3>Cómo cambia el cultivo con el tiempo</h3>
            
            <div class="reading-block">
              <div class="sub-kicker">QUÉ REPRESENTA</div>
              <p>Cada línea sigue la respuesta observada por un sensor durante varios meses.</p>
            </div>
            <div class="reading-block">
              <div class="sub-kicker">QUÉ OBSERVAR</div>
              <p>Observa cuándo la señal aumenta, cuándo alcanza valores altos y cómo disminuye después.</p>
            </div>
            <div class="notice-box">
              <div class="notice-kicker">CONSIDERA QUE...</div>
              <p>Una señal alta no significa, por sí sola, mayor rendimiento ni una etapa biológica específica.</p>
            </div>
          </v-card>

          <!-- Tarjeta 02 -->
          <v-card class="reading-card" rounded="xl" elevation="0">
            <div class="pill-badge">
              <span class="badge-num">02</span>
              <span>COMPARACIÓN TERRITORIAL</span>
            </div>
            <h3>Cómo cambia entre regiones</h3>
            
            <div class="reading-block">
              <div class="sub-kicker">QUÉ REPRESENTA</div>
              <p>Cada línea resume el comportamiento temporal de las parcelas de un municipio para el mismo índice.</p>
            </div>
            <div class="reading-block">
              <div class="sub-kicker">QUÉ OBSERVAR</div>
              <p>Compara la forma de las curvas, el momento en que cambian y cuándo alcanzan sus valores más altos.</p>
            </div>
            <div class="notice-box">
              <div class="notice-kicker">CONSIDERA QUE...</div>
              <p>Las diferencias muestran patrones regionales; la gráfica por sí sola no explica la causa.</p>
            </div>
          </v-card>

          <!-- Tarjeta 03 -->
          <v-card class="reading-card" rounded="xl" elevation="0">
            <div class="pill-badge">
              <span class="badge-num">03</span>
              <span>MÁXIMO ESPECTRAL</span>
            </div>
            <h3>Cuándo alcanza su mayor señal</h3>
            
            <div class="reading-block">
              <div class="sub-kicker">QUÉ REPRESENTA</div>
              <p>Para cada parcela se identifica el periodo en el que el índice alcanza su valor máximo.</p>
            </div>
            <div class="reading-block">
              <div class="sub-kicker">QUÉ OBSERVAR</div>
              <p>Una barra alta significa que muchas parcelas alcanzaron su máxima señal en fechas similares.</p>
            </div>
            <div class="notice-box">
              <div class="notice-kicker">CONSIDERA QUE...</div>
              <p>El máximo espectral no equivale automáticamente a espigamiento, floración, madurez o cosecha.</p>
            </div>
          </v-card>

          <!-- Tarjeta 04 -->
          <v-card class="reading-card" rounded="xl" elevation="0">
            <div class="pill-badge">
              <span class="badge-num">04</span>
              <span>MEDIDAS TEMPORALES</span>
            </div>
            <h3>Cómo resumimos una trayectoria</h3>
            
            <div class="reading-block">
              <div class="sub-kicker">QUÉ REPRESENTA</div>
              <p>Una curva contiene muchos puntos. Para comparar parcelas, resumimos su forma mediante medidas numéricas.</p>
            </div>
            <div class="reading-block">
              <div class="sub-kicker">QUÉ OBSERVAR</div>
              <p>AUC resume la señal acumulada; el pico indica cuándo ocurrió el máximo; la amplitud mide cuánto cambió; subida y descenso describen la velocidad de cambio.</p>
            </div>
            <div class="notice-box">
              <div class="notice-kicker">CONSIDERA QUE...</div>
              <p>Estas medidas describen la trayectoria satelital; no son valores directos de rendimiento.</p>
            </div>
          </v-card>
        </div>
      </section>
    </template>
  </v-container>


</template>

<style scoped>
.phenology-page { min-height: 100%; padding: 28px 30px 44px; background: #f7f9f7; }
.page-heading { display: flex; align-items: center; gap: 16px; margin: 0 0 30px; }
.heading-icon { display: grid; flex: none; place-items: center; width: 54px; height: 54px; color: #287a52; background: #eaf3ed; border-radius: 14px; }
.eyebrow { margin: 0 0 5px; color: #628071; font-size: 10px; font-weight: 700; letter-spacing: .13em; }
h1,h2,h3,p { margin-top: 0; }
h1 { margin-bottom: 0; color: #173f2c; font-size: clamp(22px, 3vw, 30px); font-weight: 650; line-height: 1.2; }
.heading-description,.section-description,.card-description { margin: 7px 0 0; color: #718076; font-size: 13px; line-height: 1.55; }
.phenology-section { margin-bottom: 28px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin: 0 0 13px; padding: 0 2px; }
.section-heading h2 { margin: 0; color: #173f2c; font-size: 19px; font-weight: 650; }
.data-card { padding: 20px 22px 16px; border: 1px solid #e5ebe6; background: #fff; box-shadow: 0 8px 24px rgba(32, 57, 41, .035); }
.data-note { margin: 6px 2px 0; color: #87948b; font-size: 11px; line-height: 1.5; }
.section-heading-controls { align-items: center; }
.select-label { display: flex; align-items: center; gap: 10px; color: #718076; font-size: 12px; }
.data-select { min-width: 135px; padding: 9px 32px 9px 11px; border: 1px solid #dce5dd; border-radius: 9px; color: #244c36; background: #fff; font: inherit; font-size: 12px; }
.combined-grid { display: grid; grid-template-columns: minmax(0, .92fr) minmax(0, 1.3fr); gap: 18px; align-items: stretch; }
.peak-card h3,.features-card h3 { margin: 0; color: #173f2c; font-size: 15px; font-weight: 650; }
.peak-card .card-description,.features-card .card-description { margin: 5px 0 8px; font-size: 11px; }
.feature-header { display: flex; align-items: start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.feature-select { min-width: 145px; }
.table-scroll { overflow-x: auto; }
.feature-table { width: 100%; border-collapse: collapse; font-size: 11px; white-space: nowrap; }
.feature-table th { padding: 10px 8px; color: #75847a; background: #f7f9f7; text-align: left; font-size: 10px; font-weight: 650; }
.feature-table td { padding: 9px 8px; border-bottom: 1px solid #edf1ed; color: #52675a; }
.feature-table td:first-child { color: #1f6944; font-weight: 650; }
.empty-cell { padding: 24px !important; color: #88948b !important; text-align: center; }
.table-pagination { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 12px; color: #78877d; font-size: 11px; }
.table-pagination > div { display: flex; align-items: center; gap: 9px; }
.table-pagination button { padding: 6px 9px; border: 1px solid #dce5dd; border-radius: 7px; color: #287a52; background: #fff; font: inherit; cursor: pointer; }
.table-pagination button:disabled { color: #aab5ad; cursor: default; }
.message-card { padding: 20px; border: 1px solid #e5ebe6; border-radius: 14px; color: #617267; background: #fff; }
.error-message { color: #9e3c37; border-color: #f0d8d6; }
.section-note { margin: 10px 2px 0; }
@media (max-width: 960px) { .combined-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) {
  .phenology-page { padding: 20px 14px 30px; }
  .page-heading { margin-bottom: 24px; }
  .section-heading-controls { align-items: start; flex-direction: column; }
  .feature-header { flex-direction: column; }
  .data-card { padding: 15px 12px 13px; }
  .table-pagination { align-items: start; flex-direction: column; }
}

/* Tarjetas contenedoras principales */
.info-card {
  padding: 26px 28px;
  border: 1px solid #e5ebe6;
  background: #ffffff;
  box-shadow: 0 4px 18px rgba(32, 57, 41, 0.035);
}

.card-kicker {
  color: #628071;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  margin-bottom: 6px;
}

.card-main-title {
  margin: 0 0 10px;
  color: #173f2c;
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -0.2px;
}

.card-subtitle {
  margin: 0 0 22px;
  color: #6c7d72;
  font-size: 13px;
  line-height: 1.55;
  max-width: 820px;
}

/* 1. Flujo de 5 pasos */
.flow-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  overflow-x: auto;
  padding: 4px 0 10px;
}

.flow-box {
  flex: 1;
  min-width: 145px;
  padding: 18px 16px;
  border: 1px solid #e7ede8;
  border-radius: 14px;
  background: #f8faf8;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-num {
  font-size: 11px;
  font-weight: 700;
  color: #8fa093;
}

.flow-box strong {
  font-size: 12.5px;
  color: #1b4530;
  line-height: 1.35;
}

.flow-arrow {
  color: #9cb1a2;
  font-size: 16px;
  font-weight: 600;
  flex: none;
}

/* 2. Glosario de Trayectoria */
.glossary-list {
  display: flex;
  flex-direction: column;
  margin-top: 14px;
}

.glossary-item {
  display: flex;
  align-items: flex-start;
  padding: 16px 0;
  border-top: 1px solid #eef2ee;
  gap: 32px;
}

.glossary-item:first-child {
  border-top: 1px solid #eef2ee;
}

.glossary-term {
  width: 110px;
  flex: none;
  font-size: 13.5px;
  font-weight: 700;
  color: #1e5a38;
}

.glossary-def strong {
  display: block;
  font-size: 13px;
  color: #173f2c;
  margin-bottom: 3px;
}

.glossary-def p {
  margin: 0;
  color: #6e7f74;
  font-size: 12.5px;
  line-height: 1.5;
}

/* 3. Grid de 4 preguntas */
.reading-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.reading-card {
  padding: 24px 26px;
  border: 1px solid #e5ebe6;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 18px rgba(32, 57, 41, 0.035);
}

.pill-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  color: #1f6944;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  margin-bottom: 12px;
}

.badge-num {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  background: #173f2c;
  color: #ffffff;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
}

.reading-card h3 {
  margin: 0 0 16px;
  color: #173f2c;
  font-size: 17px;
  font-weight: 650;
}

.reading-block {
  margin-bottom: 14px;
}

.sub-kicker {
  font-size: 9.5px;
  font-weight: 700;
  color: #798a7e;
  letter-spacing: 0.08em;
  margin-bottom: 4px;
}

.reading-block p {
  margin: 0;
  color: #55675c;
  font-size: 12.5px;
  line-height: 1.55;
}

.notice-box {
  margin-top: auto;
  padding: 12px 14px;
  background: #f7f9f7;
  border-radius: 10px;
}

.notice-kicker {
  font-size: 9px;
  font-weight: 700;
  color: #637768;
  letter-spacing: 0.08em;
  margin-bottom: 3px;
}

.notice-box p {
  margin: 0;
  color: #67796d;
  font-size: 11.5px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .reading-grid {
    grid-template-columns: 1fr;
  }
}
</style>
