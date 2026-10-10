import { createRouter, createWebHistory } from 'vue-router';
import { useUIStore } from '@/stores/ui';

const rootRedirect = {
  path: '/',
  redirect: '/dashboard'
};

const dashboardLayout = {
  path: '/',
  component: () => import('@/pages/(main).vue'),
  children: [
    {
      path: 'dashboard',
      component: () => import('@/pages/(main)/dashboard.vue')
    },
    {
      path: 'fenologia',
      component: () => import('@/pages/(main)/fenologia.vue')
    }
  ]
};

const fallbackRoute = {
  path: '/:pathMatch(.*)*',
  redirect: '/dashboard'
};

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [rootRedirect, dashboardLayout, fallbackRoute],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    return { top: 0 };
  }
});

router.beforeEach(() => {
  const uiStore = useUIStore();
  uiStore.isLoading = true;
});

router.afterEach(() => {
  const uiStore = useUIStore();
  uiStore.isLoading = false;
});
