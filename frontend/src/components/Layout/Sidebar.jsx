import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Atom,
  ChevronRight,
  Settings,
  BarChart3,
  Cpu,
  Layers,
  Droplets,
  ListChecks,
  FlaskConical,
  Target,
  TestTubes,
  Gem,
} from 'lucide-react'
import clsx from 'clsx'
import { ROUTE_KEYS, ROUTE_META } from '../../navigation/routeMeta'
// useAdminCapabilities removed — admin gate removed (v00.99.45)

// v00.99.66: the dedicated FF Parameters sidebar entry was removed — the
// /ff-parameters route now redirects to /molecules, which is the canonical
// FF artifact management surface. navItems stays as a function to keep the
// pre-existing shape in case future entries need conditional rendering.
function buildNavItems() {
  return [
  { type: 'group', label: 'AI Agent' },
  { path: ROUTE_META[ROUTE_KEYS.MLOPS].path, icon: Cpu, label: ROUTE_META[ROUTE_KEYS.MLOPS].sidebarLabel, level: 1 },
  {
    path: ROUTE_META[ROUTE_KEYS.INVERSE_DESIGN].path,
    icon: Target,
    label: ROUTE_META[ROUTE_KEYS.INVERSE_DESIGN].sidebarLabel,
    level: 1,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.BINDER_ANALYSIS].path,
    icon: FlaskConical,
    label: ROUTE_META[ROUTE_KEYS.BINDER_ANALYSIS].sidebarLabel,
    level: 1,
  },
  { type: 'group', label: 'Database' },
  { path: ROUTE_META[ROUTE_KEYS.MOLECULES].path, icon: Atom, label: ROUTE_META[ROUTE_KEYS.MOLECULES].sidebarLabel, level: 1 },
  {
    path: ROUTE_META[ROUTE_KEYS.BINDER_CELLS_DATABASE].path,
    icon: Droplets,
    label: ROUTE_META[ROUTE_KEYS.BINDER_CELLS_DATABASE].sidebarLabel,
    level: 1,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.INTERFACE_MOLECULES_DATABASE].path,
    icon: TestTubes,
    label: ROUTE_META[ROUTE_KEYS.INTERFACE_MOLECULES_DATABASE].sidebarLabel,
    level: 1,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.CRYSTAL_STRUCTURES_DATABASE].path,
    icon: Gem,
    label: ROUTE_META[ROUTE_KEYS.CRYSTAL_STRUCTURES_DATABASE].sidebarLabel,
    level: 1,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.LAYERED_STRUCTURES_DATABASE].path,
    icon: Layers,
    label: ROUTE_META[ROUTE_KEYS.LAYERED_STRUCTURES_DATABASE].sidebarLabel,
    level: 1,
  },
  { type: 'group', label: 'Analysis' },
  { path: ROUTE_META[ROUTE_KEYS.ANALYSIS].path, icon: BarChart3, label: ROUTE_META[ROUTE_KEYS.ANALYSIS].sidebarLabel, level: 1 },
  { type: 'group', label: 'Dynamics' },
  { path: ROUTE_META[ROUTE_KEYS.DASHBOARD].path, icon: LayoutDashboard, label: ROUTE_META[ROUTE_KEYS.DASHBOARD].sidebarLabel, level: 2 },
  { type: 'subgroup', label: 'Single Job' },
  {
    path: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_SINGLE_MOLECULE].path,
    icon: Atom,
    label: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_SINGLE_MOLECULE].sidebarLabel,
    level: 2,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_BINDER_CELL].path,
    icon: Droplets,
    label: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_BINDER_CELL].sidebarLabel,
    level: 2,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_INTERFACE_MOLECULES].path,
    icon: TestTubes,
    label: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_INTERFACE_MOLECULES].sidebarLabel,
    level: 2,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_CRYSTAL_STRUCTURES].path,
    icon: Gem,
    label: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_CRYSTAL_STRUCTURES].sidebarLabel,
    level: 2,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_LAYERED_STRUCTURE].path,
    icon: Layers,
    label: ROUTE_META[ROUTE_KEYS.SINGLE_JOB_LAYERED_STRUCTURE].sidebarLabel,
    level: 2,
  },
  { type: 'subgroup', label: 'Batch Job' },
  {
    path: ROUTE_META[ROUTE_KEYS.BATCH_JOB_SINGLE_MOLECULE].path,
    icon: Atom,
    label: ROUTE_META[ROUTE_KEYS.BATCH_JOB_SINGLE_MOLECULE].sidebarLabel,
    level: 2,
  },
  {
    path: ROUTE_META[ROUTE_KEYS.BATCH_JOB_BINDER_CELL].path,
    icon: ListChecks,
    label: ROUTE_META[ROUTE_KEYS.BATCH_JOB_BINDER_CELL].sidebarLabel,
    level: 2,
  },
  { type: 'group', label: 'Settings' },
  { path: ROUTE_META[ROUTE_KEYS.SETTINGS].path, icon: Settings, label: ROUTE_META[ROUTE_KEYS.SETTINGS].sidebarLabel, level: 1 },
  ]
}

function Sidebar() {
  const location = useLocation()
  // Admin gate removed (v00.99.45) — FF Parameters always visible
  const navItems = buildNavItems()

  return (
    <aside className="fixed left-0 top-16 bottom-0 w-72 bg-[#111827] border-r border-[#1f2937] overflow-y-auto">
      <div className="p-4">
        {/* Navigation */}
        <nav className="space-y-0">
          {navItems.map(({ path, icon: Icon, label, disabled, type, level }, index) => {
            if (type === 'group') {
              const hasPreviousGroup = navItems
                .slice(0, index)
                .some((item) => item.type === 'group')
              return (
                <div
                  key={label}
                  className={clsx(
                    'px-4 pt-4 pb-1.5 text-xs font-semibold uppercase tracking-wider text-blue-400',
                    hasPreviousGroup && 'mt-3 border-t border-[#1f2937]'
                  )}
                >
                  {label}
                </div>
              )
            }
            if (type === 'subgroup') {
              return (
                <div
                  key={`${label}-${index}`}
                  className="px-8 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500"
                >
                  {label}
                </div>
              )
            }
            const [targetPathname, targetSearchRaw] = String(path).split('?')
            const targetParams = new URLSearchParams(targetSearchRaw || '')
            const currentParams = new URLSearchParams(location.search || '')
            const hasTargetSearch = targetParams.toString().length > 0
            const isActive =
              location.pathname === targetPathname &&
              (!hasTargetSearch ||
                Array.from(targetParams.entries()).every(([key, value]) => currentParams.get(key) === value))
            if (disabled) {
              return (
                <div
                  key={`${path}-${index}`}
                  className={clsx(
                    'flex items-center gap-3 py-2.5 rounded-lg text-sm text-slate-600 cursor-not-allowed opacity-50',
                    level === 2 ? 'pl-12 pr-4' : level === 1 ? 'pl-8 pr-4' : 'px-4'
                  )}
                  aria-disabled="true"
                  title="Disabled"
                >
                  <Icon className="w-5 h-5" />
                  <span className="flex-1">{label}</span>
                </div>
              )
            }
            return (
              <Link
                key={`${path}-${index}`}
                to={path}
                className={clsx(
                  'flex items-center gap-3 py-2.5 rounded-lg transition-all duration-200 text-sm',
                  level === 2 ? 'pl-12 pr-4' : level === 1 ? 'pl-8 pr-4' : 'px-4',
                  isActive
                    ? 'bg-gradient-to-r from-blue-600/20 to-indigo-600/20 text-white border-l-2 border-blue-500'
                    : 'text-slate-400 hover:bg-[#1f2937] hover:text-white'
                )}
              >
                <Icon className={clsx('w-5 h-5', isActive && 'text-blue-400')} />
                <span className="flex-1">{label}</span>
                {isActive && <ChevronRight className="w-4 h-4 text-blue-400" />}
              </Link>
            )
          })}
        </nav>
      </div>
    </aside>
  )
}

export default Sidebar
