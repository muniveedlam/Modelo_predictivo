<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import VueApexCharts from 'vue3-apexcharts';

type Parcel = Record<string, any>;
const data = ref<any>(null);
const geo = ref<any>(null);
const loadError = ref('');
const state = ref('');
const municipality = ref('');
const search = ref('');
const mapMetric = ref('rendimientoTHa');
const selectedId = ref('');
const mapZoom = ref(1);
const mapFocusId = ref('');
const satelliteEnabled = ref(true);
const metricItems = [
  { title: 'Rendimiento (t/ha)', value: 'rendimientoTHa' },
  { title: 'Elevación (m)', value: 'elevacionM' },
  { title: 'Pendiente (°)', value: 'pendienteGrados' },
  { title: 'NDVI máximo', value: 'ndviMax' }
];
onMounted(async () => {
  try {
    const [a, b] = await Promise.all([
      fetch('/data/dashboard.json').then((r) => { if (!r.ok) throw new Error('No se encontró dashboard.json'); return r.json(); }),
      fetch('/data/parcelas.geojson').then((r) => { if (!r.ok) throw new Error('No se encontró parcelas.geojson'); return r.json(); })
    ]);
    data.value = a;
    geo.value = b;
    selectedId.value = a.parcelas?.[0]?.id || '';
  } catch (e: any) {
    loadError.value = e?.message || 'No fue posible cargar los datos del tablero.';
  }
});
watch(state, () => { municipality.value = ''; });
const states = computed(() => data.value?.estados || []);
const municipalities = computed(() => state.value ? (data.value?.municipiosPorEstado?.[state.value] || []) : [...new Set((data.value?.parcelas || []).map((p: Parcel) => p.municipio))].sort());
const filtered = computed<Parcel[]>(() => (data.value?.parcelas || []).filter((p: Parcel) =>
  (!state.value || p.estado === state.value) &&
  (!municipality.value || p.municipio === municipality.value) &&
  (!search.value || p.id.toLowerCase().includes(search.value.toLowerCase()))
));
const filteredIds = computed(() => new Set(filtered.value.map((p) => p.id)));
const chosen = computed<Parcel | null>(() => filtered.value.find((p) => p.id === selectedId.value) || filtered.value[0] || null);
watch(filtered, (rows) => {
  if (rows.length && !rows.some((p) => p.id === selectedId.value)) selectedId.value = rows[0].id;
  mapFocusId.value = '';
  mapZoom.value = 1;
}, { deep: true });
const sum = (rows: Parcel[], key: string) => rows.reduce((n, p) => n + (Number(p[key]) || 0), 0);
const area = computed(() => sum(filtered.value, 'areaHa'));
const production = computed(() => sum(filtered.value, 'produccionEstimadaT'));
const weightedYield = computed(() => area.value ? production.value / area.value : 0);
const meanOf = (rows: Parcel[], key: string) => {
  const vals = rows.map((p) => Number(p[key])).filter(Number.isFinite);
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
};
const ndviMax = computed(() => filtered.value.length ? Math.max(...filtered.value.map((p) => Number(p.ndviMax) || 0)) : 0);
const ndviMean = computed(() => meanOf(filtered.value, 'ndviMean'));
const observedCount = computed(() => filtered.value.filter((p) => p.fuenteRendimiento === 'Observado').length);
const estimatedCount = computed(() => filtered.value.filter((p) => p.fuenteRendimiento === 'Estimado').length);
const monthly = computed(() => {
  const rows = (data.value?.mensual || []).filter((r: any) => filteredIds.value.has(r.id));
  return [4, 5, 6, 7, 8, 9, 10].map((m) => {
    const group = rows.filter((r: any) => r.mes === m);
    const avg = (key: string) => {
      const vals = group.map((r: any) => Number(r[key])).filter(Number.isFinite);
      return vals.length ? vals.reduce((a: number, b: number) => a + b, 0) / vals.length : null;
    };
    return { label: group[0]?.mesLabel || ['Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct'][m - 4], planet: avg('planetNdvi'), sentinel: avg('sentinel2Ndvi'), rain: avg('precipitacionMm'), tmax: avg('tmaxC'), tmin: avg('tminC') };
  });
});
const monthlyOptions = computed(() => ({
  chart: { type: 'line', height: 300, toolbar: { show: false }, fontFamily: 'Public Sans, sans-serif' },
  colors: ['#287a52', '#d5a545'],
  stroke: { curve: 'smooth', width: 3 },
  markers: { size: 3, strokeWidth: 0 },
  xaxis: { categories: monthly.value.map((m) => m.label), labels: { style: { colors: '#77847c' } } },
  yaxis: { min: 0, max: 1, tickAmount: 4, labels: { formatter: (v: number) => v.toFixed(1) } },
  grid: { borderColor: '#edf1ed', strokeDashArray: 4 },
  legend: { position: 'top' }, dataLabels: { enabled: false }, tooltip: { y: { formatter: (v: number) => v.toFixed(3) } }
}));
const monthlySeries = computed(() => [
  { name: 'NDVI Planet', data: monthly.value.map((m) => m.planet) },
  { name: 'NDVI Sentinel-2', data: monthly.value.map((m) => m.sentinel) }
]);
const weatherOptions = computed(() => ({
  chart: { type: 'line', height: 270, toolbar: { show: false }, fontFamily: 'Public Sans, sans-serif' },
  colors: ['#4c89b8', '#ec9b52', '#727e89'],
  stroke: { curve: 'smooth', width: [0, 3, 3] },
  plotOptions: { bar: { columnWidth: '38%', borderRadius: 3 } },
  xaxis: { categories: monthly.value.map((m) => m.label) },
  yaxis: [
    {
      seriesName: 'Precipitación',
      tickAmount: 5,
      decimalsInFloat: 0,
      labels: { minWidth: 28, maxWidth: 36, formatter: (v: number) => String(Math.round(v)) },
      title: { text: 'Lluvia (mm)' }
    },
    {
      seriesName: ['T. máxima', 'T. mínima'],
      opposite: true,
      tickAmount: 5,
      decimalsInFloat: 0,
      labels: { minWidth: 28, maxWidth: 36, formatter: (v: number) => String(Math.round(v)) },
      title: { text: 'Temperatura (°C)' }
    }
  ],
  grid: { borderColor: '#edf1ed', strokeDashArray: 4 },
  dataLabels: { enabled: false }, legend: { position: 'top' },
  tooltip: { y: { formatter: (v: number) => v.toFixed(1) } }
}));
const weatherSeries = computed(() => [
  { name: 'Precipitación', type: 'column', data: monthly.value.map((m) => m.rain) },
  { name: 'T. máxima', type: 'line', data: monthly.value.map((m) => m.tmax) },
  { name: 'T. mínima', type: 'line', data: monthly.value.map((m) => m.tmin) }
]);
const grouped = (key: string) => {
  const buckets = new Map<string, Parcel[]>();
  filtered.value.forEach((p) => buckets.set(p[key], [...(buckets.get(p[key]) || []), p]));
  return [...buckets.entries()].map(([name, rows]) => ({ name, parcels: rows.length, area: sum(rows, 'areaHa'), production: sum(rows, 'produccionEstimadaT'), yield: sum(rows, 'produccionEstimadaT') / (sum(rows, 'areaHa') || 1) }));
};
const municipalitiesByProduction = computed(() => grouped('municipio').sort((a, b) => b.production - a.production).slice(0, 7));
const stateSummary = computed(() => grouped('estado').sort((a, b) => b.yield - a.yield));
const muniOptions = computed(() => ({
  chart: { type: 'bar', height: 275, toolbar: { show: false }, fontFamily: 'Public Sans, sans-serif' },
  colors: ['#287a52'], plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: '58%' } },
  xaxis: { categories: municipalitiesByProduction.value.map((m) => m.name), labels: { formatter: (v: string) => Number(v).toFixed(0) + ' t' } },
  grid: { borderColor: '#edf1ed', strokeDashArray: 4 }, dataLabels: { enabled: false },
  tooltip: { y: { formatter: (v: number) => v.toFixed(1) + ' t estimadas' } }
}));
const muniSeries = computed(() => [{ name: 'Producción estimada', data: municipalitiesByProduction.value.map((m) => m.production) }]);
const stateOptions = computed(() => ({
  chart: { type: 'bar', height: 260, toolbar: { show: false }, fontFamily: 'Public Sans, sans-serif' },
  colors: ['#8caa6a'], plotOptions: { bar: { horizontal: true, borderRadius: 4, barHeight: '48%' } },
  xaxis: { categories: stateSummary.value.map((s) => s.name), labels: { formatter: (v: string) => Number(v).toFixed(1) } },
  grid: { borderColor: '#edf1ed', strokeDashArray: 4 }, dataLabels: { enabled: false },
  tooltip: { y: { formatter: (v: number) => v.toFixed(2) + ' t/ha' } }
}));
const stateSeries = computed(() => [{ name: 'Rendimiento ponderado', data: stateSummary.value.map((s) => s.yield) }]);
const donutOptions = computed(() => ({
  chart: { type: 'donut', height: 235, fontFamily: 'Public Sans, sans-serif' },
  labels: ['Rendimiento observado', 'Rendimiento estimado'],
  colors: ['#287a52', '#e7b450'], legend: { position: 'bottom' },
  dataLabels: { enabled: true }, stroke: { width: 3, colors: ['#fff'] },
  plotOptions: { pie: { donut: { size: '68%', labels: { show: true, total: { show: true, label: 'Parcelas', formatter: () => String(filtered.value.length) } } } } }
}));
const donutSeries = computed(() => [observedCount.value, estimatedCount.value]);
const hardParcels = computed(() => (data.value?.anomalias || []).filter((p: Parcel) => filteredIds.value.has(p.id)).slice(0, 11));
const num = (v: any, digits = 2) => v === null || v === undefined || v === '' ? '—' : Number.isFinite(Number(v)) ? Number(v).toLocaleString('es-MX', { maximumFractionDigits: digits }) : '—';
const metricValue = (p: Parcel) => Number(p?.[mapMetric.value]);
const worldX = (lon: number) => (lon + 180) / 360;
const worldY = (lat: number) => {
  const safeLat = Math.max(-85.05112878, Math.min(85.05112878, lat));
  const sin = Math.sin(safeLat * Math.PI / 180);
  return 0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI);
};
const bounds = computed(() => {
  const pts: number[][] = [];
  const visit = (coords: any): void => { if (Array.isArray(coords) && typeof coords[0] === 'number') pts.push([worldX(coords[0]), worldY(coords[1])]); else if (Array.isArray(coords)) coords.forEach(visit); };
  (geo.value?.features || []).forEach((f: any) => visit(f.geometry?.coordinates));
  if (!pts.length) return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
  return { minX: Math.min(...pts.map((p) => p[0])), maxX: Math.max(...pts.map((p) => p[0])), minY: Math.min(...pts.map((p) => p[1])), maxY: Math.max(...pts.map((p) => p[1])) };
});
const mapProjection = computed(() => {
  const centerX = (bounds.value.minX + bounds.value.maxX) / 2;
  const centerY = (bounds.value.minY + bounds.value.maxY) / 2;
  const scale = Math.min(660 / (bounds.value.maxX - bounds.value.minX || 1), 400 / (bounds.value.maxY - bounds.value.minY || 1));
  return { centerX, centerY, scale };
});
const mapX = (p: number[]) => 350 + (worldX(p[0]) - mapProjection.value.centerX) * mapProjection.value.scale;
const mapY = (p: number[]) => 220 + (worldY(p[1]) - mapProjection.value.centerY) * mapProjection.value.scale;
const projectedPath = (geom: any) => {
  const ringPath = (ring: number[][]) => ring.map((p, i) => (i ? 'L' : 'M') + mapX(p).toFixed(1) + ',' + mapY(p).toFixed(1)).join(' ') + ' Z';
  const polygons = geom?.type === 'Polygon' ? [geom.coordinates] : geom?.type === 'MultiPolygon' ? geom.coordinates : [];
  return polygons.map((poly: any[]) => poly.map((ring: number[][]) => ringPath(ring)).join(' ')).join(' ');
};
const projectedCenter = (geom: any) => {
  const ring = geom?.type === 'Polygon' ? geom.coordinates?.[0] : geom?.coordinates?.[0]?.[0];
  if (!ring?.length) return { cx: 0, cy: 0 };
  const lon = ring.reduce((n: number, p: number[]) => n + p[0], 0) / ring.length;
  const lat = ring.reduce((n: number, p: number[]) => n + p[1], 0) / ring.length;
  return { cx: mapX([lon, lat]), cy: mapY([lon, lat]) };
};
const colorFor = (value: number) => {
  const vals = filtered.value.map(metricValue).filter(Number.isFinite);
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 1;
  const t = hi === lo ? 0.55 : Math.max(0, Math.min(1, (value - lo) / (hi - lo)));
  const stops = [[238, 243, 225], [171, 202, 139], [75, 137, 85], [34, 91, 61]];
  const k = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(k)), f = k - i;
  const rgb = stops[i].map((c, j) => Math.round(c + (stops[i + 1][j] - c) * f));
  return 'rgb(' + rgb.join(',') + ')';
};
const mapFeatures = computed(() => (geo.value?.features || []).map((f: any) => {
  const id = String(f.properties?.ID_POLIGON || f.properties?.id || f.id || '');
  const p = data.value?.parcelas?.find((row: Parcel) => row.id === id);
  return { id, path: projectedPath(f.geometry), ...projectedCenter(f.geometry), parcel: p, visible: filteredIds.value.has(id), color: p ? colorFor(metricValue(p)) : '#dce5dc' };
}));
const mapFocus = computed(() => {
  const selected = mapFocusId.value ? mapFeatures.value.find((f: any) => f.id === mapFocusId.value) : null;
  if (selected) return { cx: selected.cx, cy: selected.cy };
  const visible = mapFeatures.value.filter((f: any) => f.visible);
  return visible.length ? { cx: visible.reduce((n: number, f: any) => n + f.cx, 0) / visible.length, cy: visible.reduce((n: number, f: any) => n + f.cy, 0) / visible.length } : { cx: 350, cy: 220 };
});
const mapTransform = computed(() => 'translate(350 220) scale(' + mapZoom.value + ') translate(' + (-mapFocus.value.cx) + ' ' + (-mapFocus.value.cy) + ')');
const imageryTiles = computed(() => {
  if (!satelliteEnabled.value || !geo.value) return [];
  const z = Math.min(19, 10 + Math.floor(Math.log2(Math.max(1, mapZoom.value))));
  const count = 2 ** z;
  const screenLeft = mapFocus.value.cx - 350 / mapZoom.value;
  const screenRight = mapFocus.value.cx + 350 / mapZoom.value;
  const screenTop = mapFocus.value.cy - 220 / mapZoom.value;
  const screenBottom = mapFocus.value.cy + 220 / mapZoom.value;
  const worldLeft = mapProjection.value.centerX + (screenLeft - 350) / mapProjection.value.scale;
  const worldRight = mapProjection.value.centerX + (screenRight - 350) / mapProjection.value.scale;
  const worldTop = mapProjection.value.centerY + (screenTop - 220) / mapProjection.value.scale;
  const worldBottom = mapProjection.value.centerY + (screenBottom - 220) / mapProjection.value.scale;
  const xStart = Math.max(0, Math.floor(Math.min(worldLeft, worldRight) * count));
  const xEnd = Math.min(count - 1, Math.floor(Math.max(worldLeft, worldRight) * count));
  const yStart = Math.max(0, Math.floor(Math.min(worldTop, worldBottom) * count));
  const yEnd = Math.min(count - 1, Math.floor(Math.max(worldTop, worldBottom) * count));
  const toMapX = (x: number) => 350 + (x - mapProjection.value.centerX) * mapProjection.value.scale;
  const toMapY = (y: number) => 220 + (y - mapProjection.value.centerY) * mapProjection.value.scale;
  const tiles = [];
  for (let y = yStart; y <= yEnd; y++) for (let x = xStart; x <= xEnd; x++) {
    const left = toMapX(x / count), right = toMapX((x + 1) / count);
    const top = toMapY(y / count), bottom = toMapY((y + 1) / count);
    tiles.push({ key: `${z}-${y}-${x}`, url: `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`, x: left, y: top, width: right - left, height: bottom - top });
  }
  return tiles;
});
const zoomIn = () => { mapZoom.value = Math.min(12, Number((mapZoom.value * 1.45).toFixed(2))); };
const zoomOut = () => { mapZoom.value = Math.max(1, Number((mapZoom.value / 1.45).toFixed(2))); };
const focusParcel = () => { if (chosen.value) { mapFocusId.value = chosen.value.id; mapZoom.value = Math.max(mapZoom.value, 5); } };
const resetMap = () => { mapFocusId.value = ''; mapZoom.value = 1; };
const clearFilters = () => { state.value = ''; municipality.value = ''; search.value = ''; };
</script>
<template>
  <v-container fluid class="agro-page pa-0">
    <div v-if="loadError" class="load-error">
      <b class="load-alert-mark">!</b>
      <div><strong>No se pudieron cargar los datos.</strong><div>{{ loadError }} Ejecuta primero el generador de datos y vuelve a iniciar el tablero.</div></div>
    </div>
    <template v-else-if="data">
      <section class="hero">
        <div class="hero-copy">
          <div class="eyebrow"><span class="live-dot"></span> MONITOREO AGRÍCOLA · {{ data.metadata.ciclo }}</div>
          <h1>RAPL AgroTech</h1>
          <p>Análisis predictivo del rendimiento de cebada con datos de satélite, clima y relieve.</p>
          <div class="hero-pills">
            <span><b class="tiny-symbol">⌖</b> {{ states.length }} estados · {{ data.metricas.parcelas }} parcelas</span>
            <span><b class="tiny-symbol">◉</b> Satélite, clima y relieve</span>
          </div>
        </div>
        <div class="hero-stamp">
          <div class="stamp-icon"><span class="grain-symbol">❧</span></div>
          <div><strong>Rendimiento de cebada</strong><small>Tablero de análisis predictivo</small></div>
        </div>
      </section>

      <section class="filter-bar">
        <div class="filter-intro"><span class="filter-icon"><b class="filter-symbol">≡</b></span><div><strong>Explora tus parcelas</strong><small>Filtra por territorio o ID</small></div></div>
        <v-select v-model="state" :items="states" label="Estado" density="comfortable" variant="outlined" hide-details clearable class="filter-select" />
        <v-select v-model="municipality" :items="municipalities" label="Municipio" density="comfortable" variant="outlined" hide-details clearable class="filter-select" :disabled="!municipalities.length" />
        <v-text-field v-model="search" label="Buscar parcela" placeholder="Ej. AGC_025" density="comfortable" variant="outlined" hide-details clearable class="filter-search" />
        <v-btn variant="text" color="primary" class="clear-button" @click="clearFilters">Limpiar</v-btn>
        <div class="filter-count"><strong>{{ filtered.length }}</strong><span>parcelas</span></div>
      </section>

      <div class="section-label"><span>RESUMEN DEL TERRITORIO</span><i></i><small>{{ state || 'Todos los estados' }}{{ municipality ? ' · ' + municipality : '' }}</small></div>
      <v-row class="kpi-row">
        <v-col cols="12" sm="6" xl="3">
          <v-card class="metric-card">
            <div class="metric-head"><span class="metric-icon green"><b class="metric-symbol">↗</b></span><span class="metric-tag">T/HA</span></div>
            <div class="metric-value">{{ num(weightedYield, 2) }}<span>t/ha</span></div><div class="metric-label">Rendimiento ponderado</div>
            <div class="metric-foot">Promedio ajustado por superficie</div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" xl="3">
          <v-card class="metric-card">
            <div class="metric-head"><span class="metric-icon gold"><b class="metric-symbol">Σ</b></span><span class="metric-tag">TOTALES</span></div>
            <div class="metric-value">{{ num(production, 0) }}<span>t</span></div><div class="metric-label">Producción observada + estimada</div>
            <div class="metric-foot">Incluye {{ estimatedCount }} parcelas estimadas</div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" xl="3">
          <v-card class="metric-card">
            <div class="metric-head"><span class="metric-icon blue"><b class="metric-symbol">▦</b></span><span class="metric-tag">HECTÁREAS</span></div>
            <div class="metric-value">{{ num(area, 1) }}<span>ha</span></div><div class="metric-label">Superficie seleccionada</div>
            <div class="metric-foot">Elevación media {{ num(meanOf(filtered, 'elevacionM'), 0) }} m</div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" xl="3">
          <v-card class="metric-card ndvi-card">
            <div class="metric-head"><span class="metric-icon lime"><b class="metric-symbol">✳</b></span><span class="metric-tag">VEGETACIÓN</span></div>
            <div class="ndvi-values"><div><strong>{{ num(ndviMax, 3) }}</strong><small>NDVI máximo</small></div><span></span><div><strong>{{ num(ndviMean, 3) }}</strong><small>NDVI medio</small></div></div>
            <div class="metric-foot">Índices agregados por parcela</div>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="content-row">
        <v-col cols="12" xl="8">
          <v-card class="panel map-panel">
            <div class="panel-header">
              <div><div class="panel-kicker">VISTA ESPACIAL</div><h2>Parcelas y relieve</h2><p>Selecciona un polígono para consultar su ficha.</p></div>
              <v-select v-model="mapMetric" :items="metricItems" density="compact" variant="outlined" hide-details class="map-select" />
            </div>
            <div class="map-wrap">
              <div v-if="!geo" class="map-loading">Cargando geometrías...</div>
              <svg v-else viewBox="0 0 700 440" role="img" aria-label="Mapa interactivo de parcelas de cebada" class="parcel-map">
                <g :transform="mapTransform">
                <image v-for="tile in imageryTiles" :key="tile.key" :href="tile.url" :x="tile.x" :y="tile.y" :width="tile.width" :height="tile.height" preserveAspectRatio="none" class="satellite-tile" />
                <path v-for="shape in mapFeatures" :key="shape.id" v-show="shape.visible" :d="shape.path" :fill="shape.color" :class="{ active: chosen?.id === shape.id }" class="parcel-shape" @click="selectedId = shape.id">
                  <title>{{ shape.id }} · {{ shape.parcel?.municipio }} · {{ num(shape.parcel?.[mapMetric], 2) }}</title>
                </path>
                <circle v-for="shape in mapFeatures" :key="shape.id + '-marker'" v-show="shape.visible" :cx="shape.cx" :cy="shape.cy" :r="3.1 / mapZoom" :fill="shape.color" stroke="#fff" stroke-width="1" class="parcel-marker" @click="selectedId = shape.id"><title>{{ shape.id }} · {{ shape.parcel?.municipio }}</title></circle>
                </g>
              </svg>
              <div v-if="!filtered.length" class="map-empty">No hay parcelas para esos filtros.</div>
              <div class="map-controls"><v-btn size="small" variant="tonal" color="primary" aria-label="Acercar mapa" @click="zoomIn">+</v-btn><span>{{ Math.round(mapZoom * 100) }}%</span><v-btn size="small" variant="tonal" color="primary" aria-label="Alejar mapa" @click="zoomOut">−</v-btn><v-btn size="small" variant="text" color="primary" @click="focusParcel">Enfocar parcela</v-btn><v-btn size="small" variant="text" color="secondary" @click="resetMap">Ver todo</v-btn></div>
              <v-btn size="small" variant="tonal" :color="satelliteEnabled ? 'primary' : 'secondary'" class="map-layer-toggle" @click="satelliteEnabled = !satelliteEnabled">{{ satelliteEnabled ? 'Satélite' : 'Fondo claro' }}</v-btn>
              <div class="map-legend"><small>{{ metricItems.find((m) => m.value === mapMetric)?.title }}</small><div class="legend-gradient"></div><div class="legend-labels"><span>Bajo</span><span>Alto</span></div></div>
              <a v-if="satelliteEnabled" class="map-attribution" href="https://www.arcgis.com/home/item.html?id=1d85c0988fc442b7ae30ef90e6530fa9" target="_blank" rel="noopener noreferrer">Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community</a>
            </div>
            <div class="map-foot"><span><i class="map-dot gradient-dot"></i>Color según el indicador seleccionado</span><span><b class="tiny-symbol">◎</b> Haz clic en una parcela; la ficha indica si es observada o estimada</span></div>
          </v-card>
        </v-col>
        <v-col cols="12" xl="4">
          <v-card class="panel parcel-panel">
            <div class="panel-header">
              <div><div class="panel-kicker">DETALLE DE PARCELA</div><h2>{{ chosen?.id || 'Sin selección' }}</h2><p>{{ chosen ? chosen.municipio + ', ' + chosen.estado : 'Elige una parcela en el mapa.' }}</p></div>
              <v-chip v-if="chosen" :color="chosen.fuenteRendimiento === 'Estimado' ? 'warning' : 'success'" size="small" variant="tonal">{{ chosen.fuenteRendimiento }}</v-chip>
            </div>
            <div v-if="chosen" class="parcel-details">
              <div class="detail-primary"><span>Rendimiento</span><strong>{{ num(chosen.rendimientoTHa, 2) }} <small>t/ha</small></strong><em>{{ chosen.fuenteRendimiento === 'Estimado' ? 'Estimación del método actual' : 'Valor medido en la base' }}</em></div>
              <div class="detail-grid">
                <div><span>Producción</span><strong>{{ num(chosen.produccionEstimadaT, 1) }} t</strong></div>
                <div><span>Superficie</span><strong>{{ num(chosen.areaHa, 2) }} ha</strong></div>
                <div><span>Elevación</span><strong>{{ num(chosen.elevacionM, 0) }} m</strong></div>
                <div><span>Pendiente media</span><strong>{{ num(chosen.pendienteGrados, 1) }}°</strong></div>
                <div><span>NDVI máximo</span><strong>{{ num(chosen.ndviMax, 3) }}</strong></div>
                <div><span>NDVI medio</span><strong>{{ num(chosen.ndviMean, 3) }}</strong></div>
              </div>
              <div v-if="chosen.dificilPrediccion" class="parcel-alert"><b class="alert-symbol">!</b><span>Parcela difícil de predecir: tuvo error alto en la validación cruzada.</span></div>
              <div v-else-if="chosen.fuenteRendimiento === 'Estimado'" class="parcel-note"><b class="info-symbol">i</b><span>Sin rendimiento observado; la cifra es una estimación, no una medición.</span></div>
              <div class="detail-bottom"><span>Conjunto: {{ chosen.conjunto || '—' }}</span><span>Validaciones: {{ num(chosen.cvNValidaciones, 0) || '—' }}</span></div>
            </div>
            <div v-else class="no-selection">Ajusta los filtros o selecciona otra parcela.</div>
          </v-card>
          <v-card class="panel donut-panel">
            <div class="panel-header compact"><div><div class="panel-kicker">COBERTURA DE DATOS</div><h2>Observado vs estimado</h2></div></div>
            <div class="donut-content"><VueApexCharts type="donut" height="210" :options="donutOptions" :series="donutSeries" /></div>
            <div class="data-note">La producción total suma rendimiento observado y predicho para completar las 197 parcelas.</div>
          </v-card>
        </v-col>
      </v-row>

      <div class="section-label"><span>COMPORTAMIENTO DEL CICLO</span><i></i><small>Abril — octubre 2025</small></div>
      <v-row class="content-row">
        <v-col cols="12" xl="7">
          <v-card class="panel chart-panel">
            <div class="panel-header"><div><div class="panel-kicker">DESARROLLO VEGETATIVO</div><h2>NDVI mensual</h2><p>Media entre las parcelas incluidas en el filtro.</p></div><span class="chart-unit">Índice NDVI</span></div>
            <VueApexCharts type="line" height="300" :options="monthlyOptions" :series="monthlySeries" />
          </v-card>
        </v-col>
        <v-col cols="12" xl="5">
          <v-card class="panel chart-panel">
            <div class="panel-header"><div><div class="panel-kicker">CONDICIONES AMBIENTALES</div><h2>Lluvia y temperatura</h2><p>Resumen mensual del área filtrada.</p></div></div>
            <VueApexCharts type="line" height="270" :options="weatherOptions" :series="weatherSeries" />
            <div class="source-caption">Clima interpolado por parcela; sirve como contexto de las observaciones satelitales.</div>
          </v-card>
        </v-col>
      </v-row>

      <div class="section-label"><span>DISTRIBUCIÓN DE LA PRODUCCIÓN</span><i></i><small>Agregado espacial</small></div>
      <v-row class="content-row">
        <v-col cols="12" xl="7">
          <v-card class="panel chart-panel">
            <div class="panel-header"><div><div class="panel-kicker">PRINCIPALES MUNICIPIOS</div><h2>¿Dónde se cultiva más?</h2><p>Producción total por municipio, en toneladas estimadas.</p></div></div>
            <VueApexCharts type="bar" height="275" :options="muniOptions" :series="muniSeries" />
          </v-card>
        </v-col>
        <v-col cols="12" xl="5">
          <v-card class="panel chart-panel">
            <div class="panel-header"><div><div class="panel-kicker">COMPARATIVO TERRITORIAL</div><h2>Rendimiento por estado</h2><p>Media ponderada por superficie (t/ha).</p></div></div>
            <VueApexCharts type="bar" height="260" :options="stateOptions" :series="stateSeries" />
            <div class="state-chips"><v-chip v-for="s in stateSummary" :key="s.name" size="small" variant="tonal" color="primary">{{ s.name }} · {{ s.parcels }} parcelas</v-chip></div>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="content-row">
        <v-col cols="12" xl="8">
          <v-card class="panel anomaly-panel">
            <div class="panel-header"><div><div class="panel-kicker">REVISIÓN PRIORITARIA</div><h2>Parcelas con mayor error en validación</h2><p>Ordenadas por RMSE medio en sus particiones fuera de muestra.</p></div><v-chip color="error" variant="tonal" size="small">{{ hardParcels.length }} casos</v-chip></div>
            <div class="table-wrap">
              <table class="anomaly-table"><thead><tr><th>Parcela</th><th>Municipio</th><th>Dato</th><th>RMSE CV (t/ha)</th><th>Error medio (t/ha)</th></tr></thead>
                <tbody><tr v-for="p in hardParcels" :key="p.id" @click="selectedId = p.id">
                  <td><button class="id-button">{{ p.id }}</button></td><td>{{ p.municipio }}</td><td><span class="table-status" :class="p.fuenteRendimiento === 'Estimado' ? 'estimated' : 'observed'">{{ p.fuenteRendimiento }}</span></td><td class="error-number">{{ num(p.cvRmseTHa, 3) }}</td><td>{{ num(p.cvErrorMedioTHa, 3) }}</td>
                </tr><tr v-if="!hardParcels.length"><td colspan="5" class="empty-cell">No hay casos difíciles dentro de este filtro.</td></tr></tbody>
              </table>
            </div>
            <div class="table-foot"><b class="info-symbol">i</b> Los errores CV solo se calculan para parcelas con rendimiento observado; los estimados aún no tienen error medible.</div>
          </v-card>
        </v-col>
        <v-col cols="12" xl="4">
          <v-card class="panel context-panel">
            <div class="context-icon"><span class="context-symbol">▤</span></div>
            <div class="panel-kicker">CONTEXTO DEL PROYECTO</div><h2>El reto de estimar la cosecha</h2>
            <p>El conjunto integra 197 parcelas de cebada en Hidalgo, Puebla y Tlaxcala. Hay rendimiento observado para 138; las 59 restantes se completan con el método predictivo actual.</p>
            <p>La estimación de las parcelas sin etiqueta debe interpretarse con cautela: la validación cruzada resume el comportamiento en parcelas conocidas y no elimina la incertidumbre del ciclo.</p>
            <div class="validation-grid"><div><small>MAE validación cruzada</small><strong>{{ num(data.validacion.maeTHa, 3) }} t/ha</strong></div><div><small>RMSE validación cruzada</small><strong>{{ num(data.validacion.rmseMedioSplitsTHa, 3) }} t/ha</strong></div></div><div class="context-tags"><span>Satélite</span><span>Clima</span><span>Topografía</span></div>
          </v-card>
        </v-col>
      </v-row>

      <footer class="dashboard-footer"><span><b class="tiny-symbol">◈</b> Fuente: {{ data.fuentes.slice(0, 3).join(' · ') }}</span><span>Método: {{ data.validacion.metodo }} · 50 particiones</span></footer>
    </template>
    <div v-else class="loading-page"><v-progress-circular indeterminate color="primary" /><span>Preparando el tablero de parcelas...</span></div>
  </v-container>
</template>

<style scoped>
.agro-page { max-width: 1680px; margin: 0 auto; padding: 12px 8px 30px !important; color: #25382e; }
.hero { position: relative; display: flex; align-items: center; justify-content: space-between; min-height: 186px; padding: 32px 38px; margin-bottom: 20px; overflow: hidden; border-radius: 18px; background: linear-gradient(115deg,#173f2c 0%,#285d3e 58%,#497950 100%); color: #fff; }
.hero:after { content: ""; position: absolute; right: 210px; top: -120px; width: 410px; height: 410px; border: 1px solid rgba(255,255,255,.09); border-radius: 50%; box-shadow: 0 0 0 35px rgba(255,255,255,.025),0 0 0 78px rgba(255,255,255,.025); pointer-events: none; }
.hero-copy,.hero-stamp { position: relative; z-index: 1; }
.eyebrow,.panel-kicker { font-size: 10px; font-weight: 700; letter-spacing: 1.35px; }
.eyebrow { display: flex; align-items: center; gap: 9px; color: #d0e2c5; }
.live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: #dbb656; box-shadow: 0 0 0 4px rgba(219,182,86,.18); }
.hero h1 { margin: 12px 0 5px; font-size: clamp(27px,3vw,38px); font-weight: 650; letter-spacing: -.8px; line-height: 1.12; }
.hero p { margin: 0; color: #e0ebde; font-size: 13px; }
.hero-pills { display: flex; gap: 18px; margin-top: 19px; color: #e0ebde; font-size: 11px; }
.hero-pills span,.map-foot span,.dashboard-footer span { display: inline-flex; align-items: center; gap: 6px; }
.hero-stamp { display: flex; gap: 12px; align-items: center; padding: 12px 16px; border: 1px solid rgba(255,255,255,.2); border-radius: 13px; background: rgba(255,255,255,.08); backdrop-filter: blur(4px); }
.grain-symbol { font-size:29px; line-height:1; transform:rotate(-35deg); }.stamp-icon { display: grid; place-items: center; width: 42px; height: 42px; color: #e8c46e; background: rgba(255,255,255,.1); border-radius: 11px; }
.hero-stamp strong,.hero-stamp small { display: block; }
.hero-stamp strong { font-size: 13px; }
.hero-stamp small { margin-top: 3px; color: #dce8dc; font-size: 10px; }
.filter-bar { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border: 1px solid #e9eee8; border-radius: 14px; background: #fff; box-shadow: 0 4px 18px rgba(35,61,43,.035); }
.filter-intro { display: flex; align-items: center; gap: 9px; min-width: 178px; }
.filter-intro strong,.filter-intro small { display: block; }
.filter-intro strong { font-size: 12px; }
.filter-intro small { margin-top: 2px; color: #859188; font-size: 10px; }
.filter-symbol { font-size:23px; line-height:1; font-weight:600; }.tiny-symbol { color:inherit; font-size:12px; font-weight:700; }.filter-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #287a52; background: #edf5ed; }
.filter-select { max-width: 210px; }
.filter-search { max-width: 235px; }
.filter-bar :deep(.v-field) { border-radius: 9px; font-size: 12px; }
.filter-bar :deep(.v-field__input) { min-height: 40px; }
.clear-button { font-size: 11px; }
.filter-count { margin-left: auto; min-width: 62px; text-align: center; border-left: 1px solid #e9eee8; }
.filter-count strong,.filter-count span { display: block; }
.filter-count strong { color: #287a52; font-size: 16px; }
.filter-count span { color: #89948c; font-size: 9px; }
.section-label { display: flex; align-items: center; gap: 11px; margin: 23px 2px 10px; color: #77857a; font-size: 9px; font-weight: 750; letter-spacing: 1.15px; }
.section-label i { height: 1px; flex: 1; background: #e6ece6; }
.section-label small { font-size: 10px; font-weight: 450; letter-spacing: 0; white-space: nowrap; }
.kpi-row { margin-top: 0 !important; margin-bottom: 16px; row-gap: 16px; }
.content-row { margin-top: 16px !important; row-gap: 16px; }
.metric-card,.panel { height: 100%; border: 1px solid #e9eee8 !important; border-radius: 14px !important; box-shadow: 0 4px 18px rgba(35,61,43,.035) !important; }
.metric-card { min-height: 154px; padding: 17px 18px 14px; }
.metric-head { display: flex; align-items: center; justify-content: space-between; }
.metric-symbol { font-size:20px; line-height:1; font-weight:700; }.metric-icon { display: grid; place-items: center; width: 35px; height: 35px; border-radius: 11px; }
.metric-icon.green { color: #287a52; background: #eaf4eb; }.metric-icon.gold { color: #b48025; background: #fbf2dc; }.metric-icon.blue { color: #4a7f9b; background: #eaf3f7; }.metric-icon.lime { color: #688b38; background: #f0f5e4; }
.metric-tag { color: #9aa49d; font-size: 8px; font-weight: 700; letter-spacing: .9px; }
.metric-value { margin-top: 11px; color: #273b2f; font-size: 26px; font-weight: 650; letter-spacing: -.6px; line-height: 1.05; }
.metric-value span { margin-left: 5px; color: #718177; font-size: 11px; font-weight: 500; letter-spacing: 0; }
.metric-label { margin-top: 5px; font-size: 11px; font-weight: 600; }
.metric-foot { margin-top: 8px; color: #87938a; font-size: 9px; }
.ndvi-values { display: flex; align-items: center; gap: 16px; margin-top: 12px; }
.ndvi-values div { display: flex; flex-direction: column; gap: 2px; }.ndvi-values strong { font-size: 20px; font-weight: 650; }.ndvi-values small { color: #849087; font-size: 9px; }.ndvi-values>span { height: 27px; width: 1px; background: #e7ece6; }
.ndvi-card .metric-foot { margin-top: 9px; }
.panel { padding: 19px 20px; background: #fff; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.panel-kicker { color: #8b9a8e; font-size: 8px; letter-spacing: 1.2px; }
.panel-header h2,.context-panel h2 { margin: 4px 0 0; color: #2a3d31; font-size: 16px; font-weight: 650; letter-spacing: -.2px; }
.panel-header p { margin: 4px 0 0; color: #87938a; font-size: 10px; }
.map-panel { min-height: 540px; }
.map-select { width: 190px; max-width: 42%; }
.map-select :deep(.v-field) { border-radius: 8px; font-size: 10px; }
.map-wrap { position: relative; height: 410px; overflow: hidden; border-radius: 11px; background: radial-gradient(ellipse at 50% 45%,#f8fbf6 0%,#f2f7f1 62%,#eff4ee 100%); }
.parcel-map { display: block; width: 100%; height: 100%; padding: 8px; }
.satellite-tile { pointer-events: none; }
.parcel-shape { fill-opacity: .68; stroke: #fff; stroke-width: 1.25; vector-effect: non-scaling-stroke; cursor: pointer; transition: opacity .15s,stroke .15s; }
.parcel-shape:hover { stroke: #d7a635; stroke-width: 2.8; }
.parcel-shape.active { stroke: #173f2c; stroke-width: 2.8; }.parcel-marker { cursor:pointer; vector-effect:non-scaling-stroke; }.parcel-marker:hover { stroke:#173f2c; stroke-width:2; }
.map-controls { position:absolute; z-index:2; top:12px; left:12px; display:flex; align-items:center; gap:4px; padding:4px; border:1px solid #e6ece3; border-radius:8px; background:rgba(255,255,255,.95); box-shadow:0 2px 10px rgba(30,60,39,.07); }.map-controls span { min-width:36px; color:#68786d; text-align:center; font-size:8px; }.map-controls :deep(.v-btn) { min-width:28px; height:28px; padding:0 7px; font-size:10px; }.map-legend { position: absolute; right: 14px; bottom: 12px; width: 120px; padding: 8px 10px; border: 1px solid #e6ece3; border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: 0 2px 10px rgba(30,60,39,.07); }
.map-layer-toggle { position:absolute; z-index:2; top:12px; right:12px; height:30px !important; border:1px solid rgba(230,236,227,.9); background:rgba(255,255,255,.95); font-size:10px; }
.map-attribution { position:absolute; z-index:2; left:12px; bottom:12px; max-width:calc(100% - 160px); padding:5px 7px; border-radius:5px; background:rgba(255,255,255,.86); color:#536158; font-size:8px; text-decoration:none; }
.map-attribution:hover { text-decoration:underline; }
.map-legend small { color: #647268; font-size: 9px; }.legend-gradient { height: 7px; margin-top: 6px; border-radius: 5px; background: linear-gradient(90deg,#eef3e1,#abca8b,#4b8955,#225b3d); }.legend-labels { display: flex; justify-content: space-between; margin-top: 3px; color: #8b978e; font-size: 8px; }
.map-foot { display: flex; gap: 17px; margin-top: 12px; color: #77857b; font-size: 9px; }
.map-dot { width: 8px; height: 8px; border-radius: 50%; }.map-dot.actual { background: #287a52; }.map-dot.predicted { background: #dfb24e; }
.map-loading,.map-empty { position: absolute; display: grid; place-items: center; inset: 0; color: #7f8c82; font-size: 12px; pointer-events: none; }
.parcel-panel { height: auto; min-height: 324px; }
.parcel-details { margin-top: 18px; }
.detail-primary { display: flex; flex-direction: column; padding: 14px; border-radius: 11px; background: linear-gradient(110deg,#edf5ed,#f5f8ed); }
.detail-primary>span { color: #728176; font-size: 10px; }.detail-primary strong { margin: 3px 0 0; color: #23593b; font-size: 26px; }.detail-primary strong small { font-size: 11px; font-weight: 500; }.detail-primary em { color: #87948a; font-size: 9px; font-style: normal; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 10px; padding: 16px 3px; }
.detail-grid div span,.detail-grid div strong { display: block; }.detail-grid div span { color: #8a968d; font-size: 9px; }.detail-grid div strong { margin-top: 3px; font-size: 11px; font-weight: 650; }
.alert-symbol,.info-symbol { display:grid; flex:none; place-items:center; width:16px; height:16px; border-radius:50%; font-size:10px; font-weight:700; }.alert-symbol { color:#995347; background:#f7dcd4; }.info-symbol { color:#806926; background:#f3e6bd; }.parcel-alert,.parcel-note { display: flex; align-items: flex-start; gap: 7px; padding: 9px; border-radius: 8px; font-size: 9px; }.parcel-alert { color: #995347; background: #fff0eb; }.parcel-note { color: #806926; background: #fcf6e7; }
.detail-bottom { display: flex; justify-content: space-between; margin-top: 12px; color: #929c94; font-size: 8px; }
.no-selection { display: grid; min-height: 200px; place-items: center; color: #909b92; font-size: 11px; }
.donut-panel { height: auto; min-height: 236px; margin-top: 14px; padding-bottom: 13px; }
.panel-header.compact { margin-bottom: 0; }.donut-content { height: 175px; }.donut-content :deep(.apexcharts-canvas) { margin: -9px auto 0; }
.data-note,.source-caption { color: #929c94; font-size: 8px; line-height: 1.45; }.data-note { padding: 8px 9px; border-radius: 7px; background: #f7f9f6; }.chart-panel { min-height: 340px; }.chart-panel :deep(.apexcharts-canvas) { margin: 0 auto; }.chart-unit { padding: 6px 9px; border-radius: 6px; color: #607569; background: #f0f5ef; font-size: 9px; white-space: nowrap; }.source-caption { margin-top: -2px; }
.state-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }.state-chips :deep(.v-chip) { font-size: 8px; }
.anomaly-panel { padding-bottom: 12px; }.table-wrap { overflow-x: auto; }.anomaly-table { width: 100%; border-collapse: collapse; white-space: nowrap; text-align: left; }.anomaly-table th { padding: 9px 10px; border-bottom: 1px solid #e9eee8; color: #8b978e; font-size: 8px; font-weight: 650; }.anomaly-table td { padding: 10px; border-bottom: 1px solid #f0f3ef; color: #59685d; font-size: 9px; }.anomaly-table tbody tr { cursor: pointer; }.anomaly-table tbody tr:hover { background: #f8faf7; }.id-button { padding: 0; border: 0; color: #287a52; background: none; font-weight: 700; cursor: pointer; }.table-status { padding: 3px 6px; border-radius: 5px; font-size: 8px; }.table-status.observed { color: #367452; background: #edf5ed; }.table-status.estimated { color: #996e24; background: #fcf4df; }.error-number { color: #a25143 !important; font-weight: 650; }.empty-cell { text-align: center !important; }.table-foot { display: flex; gap: 6px; align-items: center; margin-top: 11px; color: #8d988f; font-size: 8px; }
.context-panel { padding: 22px; background: linear-gradient(145deg,#fff 45%,#f4f7ec); }.context-symbol { font-size:22px; font-weight:700; }.context-icon { display: grid; place-items: center; width: 42px; height: 42px; margin-bottom: 15px; border-radius: 12px; color: #66863f; background: #eff5e5; }.context-panel h2 { max-width: 260px; font-size: 18px; line-height: 1.35; }.context-panel p { margin: 12px 0 0; color: #718076; font-size: 10px; line-height: 1.7; }.validation-grid { display:grid; grid-template-columns:1fr 1fr; gap:7px; margin-top:16px; }.validation-grid div { padding:9px; border-radius:8px; background:#f6f8f3; }.validation-grid small,.validation-grid strong { display:block; }.validation-grid small { color:#859087; font-size:8px; }.validation-grid strong { margin-top:4px; color:#385c40; font-size:11px; }.context-tags { display: flex; gap: 6px; margin-top: 17px; }.context-tags span { padding: 5px 8px; border-radius: 6px; color: #55745b; background: #eef4eb; font-size: 8px; }
.dashboard-footer { display: flex; justify-content: space-between; gap: 12px; padding: 13px 4px 0; color: #909b92; font-size: 8px; }
.loading-page { display: grid; min-height: 58vh; place-content: center; justify-items: center; gap: 12px; color: #7f8c82; font-size: 12px; }
.load-alert-mark { display:grid; flex:none; place-items:center; width:25px; height:25px; border-radius:50%; color:#a25143; background:#f8e1da; font-weight:700; }.load-error { display: flex; gap: 12px; align-items: flex-start; margin: 60px auto; max-width: 620px; padding: 22px; border: 1px solid #f0d8d2; border-radius: 12px; color: #78493f; background: #fff7f4; font-size: 12px; }.load-error strong { display: block; margin-bottom: 5px; }
@media (max-width: 800px) {
  .agro-page { padding: 4px 0 20px !important; }.hero { align-items: flex-start; min-height: auto; padding: 24px 20px; }.hero-stamp { display: none; }.hero:after { right: -170px; }.hero-pills { flex-direction: column; gap: 6px; }.filter-bar { align-items: stretch; flex-wrap: wrap; gap: 8px; }.filter-intro { flex: 1 1 100%; }.filter-select,.filter-search { flex: 1 1 42%; max-width: none; min-width: 145px; }.filter-count { min-width: 50px; }.map-panel { min-height: auto; }.map-wrap { height: 310px; }.map-foot { flex-wrap: wrap; gap: 8px 13px; }.panel { padding: 15px; }.dashboard-footer { flex-direction: column; }.section-label { margin-top: 18px; }.kpi-row { margin-bottom: 12px; row-gap: 12px; }.content-row { margin-top: 12px !important; row-gap: 12px; }
}
</style>

