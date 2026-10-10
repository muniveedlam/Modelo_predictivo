import { DashboardOutlined } from '@ant-design/icons-vue';
import { Plant2Icon } from 'vue-tabler-icons';

export interface menu {
  header?: string;
  title?: string;
  icon?: object;
  to?: string;
  divider?: boolean;
  chip?: string;
  chipColor?: string;
  chipVariant?: string;
  chipIcon?: string;
  children?: menu[];
  disabled?: boolean;
  type?: string;
  subCaption?: string;
}

const sidebarItem: menu[] = [
  { header: 'RAPL AGROTECH' },
  {
    title: 'Tablero de rendimiento',
    icon: DashboardOutlined,
    to: '/dashboard'
  },
  {
    title: 'Fenología del Cultivo',
    icon: Plant2Icon,
    to: '/fenologia'
  }
];

export default sidebarItem;
