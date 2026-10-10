<script setup lang="ts">
import { useCustomizerStore } from '../../../stores/customizer';
import { MenuFoldOutlined } from '@ant-design/icons-vue';
const customizer = useCustomizerStore();
</script>

<template>
  <v-app-bar elevation="0" height="60" class="agro-header">
    <v-btn class="hidden-md-and-down text-secondary mr-3" color="darkText" icon rounded="sm" variant="text" size="small" aria-label="Contraer menú" @click.stop="customizer.SET_MINI_SIDEBAR(!customizer.mini_sidebar)">
      <MenuFoldOutlined :style="{ fontSize: '16px' }" />
    </v-btn>
    <v-btn class="hidden-lg-and-up text-secondary ms-3" color="darkText" icon rounded="sm" variant="text" size="small" aria-label="Abrir menú" @click.stop="customizer.SET_SIDEBAR_DRAWER">
      <MenuFoldOutlined :style="{ fontSize: '16px' }" />
    </v-btn>
    <div class="header-title"><strong>RAPL AgroTech</strong><span>Datos territoriales de cebada</span></div>
    <v-spacer />
    <div class="header-status"><i></i><span>Dataset listo</span></div>
    <div class="header-cycle">CICLO 2025</div>
  </v-app-bar>
</template>

<style scoped>
.header-title strong,.header-title span { display:block; }
.header-title strong { color:#304238; font-size:12px; font-weight:650; }
.header-title span { margin-top:2px; color:#89948c; font-size:9px; }
.header-status { display:flex; align-items:center; gap:7px; color:#607568; font-size:10px; }
.header-status i { width:7px; height:7px; border-radius:50%; background:#5f9a62; box-shadow:0 0 0 3px #edf5ec; }
.header-cycle { margin-left:18px; padding:7px 9px; border-radius:6px; color:#687b6e; background:#f1f5ef; font-size:8px; font-weight:700; letter-spacing:.8px; }
</style>
