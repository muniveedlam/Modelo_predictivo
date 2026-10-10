<template>
  <div class="brand">
    <RouterLink to="/dashboard" aria-label="RAPL AgroTech">
      <svg viewBox="0 0 40 40" role="img" aria-hidden="true">
        <rect width="40" height="40" rx="12" fill="#eaf4eb" />
        <path d="M20 30V13m0 7c-5 0-8-3-8-8 5 0 8 3 8 8Zm0-3c0-5 3-8 8-8 0 5-3 8-8 8Z" fill="none" stroke="#287a52" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M14 30h12" stroke="#287a52" stroke-width="2.2" stroke-linecap="round" />
      </svg>
      <span>RAPL <strong>AgroTech</strong></span>
    </RouterLink>
  </div>
</template>
<script setup lang="ts">
import { RouterLink } from 'vue-router';
</script>
<style scoped>
.brand a { display:flex; align-items:center; gap:9px; text-decoration:none; color:#25382e; font-size:15px; letter-spacing:-.35px; }
.brand svg { width:36px; height:36px; flex:none; }
.brand strong { color:#287a52; font-weight:700; }
</style>
