export const ROUTE_KEYS = Object.freeze({
  DASHBOARD: 'dashboard',
  MLOPS: 'mlops',
  INVERSE_DESIGN: 'inverseDesign',
  MOLECULES: 'molecules',
  FF_PARAMETERS: 'ffParameters',
  BINDER_CELLS_DATABASE: 'binderCellsDatabase',
  INTERFACE_MOLECULES_DATABASE: 'interfaceMoleculesDatabase',
  CRYSTAL_STRUCTURES_DATABASE: 'crystalStructuresDatabase',
  LAYERED_STRUCTURES_DATABASE: 'layeredStructuresDatabase',
  ANALYSIS: 'analysis',
  SINGLE_JOB_SINGLE_MOLECULE: 'singleJobSingleMolecule',
  SINGLE_JOB_BINDER_CELL: 'singleJobBinderCell',
  SINGLE_JOB_INTERFACE_MOLECULES: 'singleJobInterfaceMolecules',
  SINGLE_JOB_CRYSTAL_STRUCTURES: 'singleJobCrystalStructures',
  SINGLE_JOB_LAYERED_STRUCTURE: 'singleJobLayeredStructure',
  BATCH_JOB_SINGLE_MOLECULE: 'batchJobSingleMolecule',
  BATCH_JOB_BINDER_CELL: 'batchJobBinderCell',
  BINDER_ANALYSIS: 'binderAnalysis',
  SETTINGS: 'settings',
})

export const ROUTE_META = Object.freeze({
  [ROUTE_KEYS.DASHBOARD]: {
    path: '/',
    sidebarLabel: 'Dashboard',
    pageTitle: 'Dashboard',
  },
  [ROUTE_KEYS.MLOPS]: {
    path: '/mlops',
    sidebarLabel: 'MLOps',
    pageTitle: 'MLOps',
  },
  [ROUTE_KEYS.INVERSE_DESIGN]: {
    path: '/inverse-design',
    sidebarLabel: 'Inverse Design',
    pageTitle: 'Inverse Design — Property Targets to Composition',
  },
  [ROUTE_KEYS.MOLECULES]: {
    path: '/molecules',
    sidebarLabel: 'Single Molecule & FF',
    pageTitle: 'Single Molecule - FF Parameterization',
  },
  [ROUTE_KEYS.FF_PARAMETERS]: {
    path: '/ff-parameters',
    // v00.99.66: redirect-only alias — canonical surface is /molecules.
    // No page component; App.jsx redirects to ROUTE_KEYS.MOLECULES.
    sidebarLabel: null,
    pageTitle: null,
  },
  [ROUTE_KEYS.BINDER_CELLS_DATABASE]: {
    path: '/binder-cells',
    sidebarLabel: 'Binder Cells',
    pageTitle: 'Binder Cells',
  },
  [ROUTE_KEYS.INTERFACE_MOLECULES_DATABASE]: {
    path: '/interface-molecules',
    sidebarLabel: 'Interface Molecules',
    pageTitle: 'Interface Molecules',
  },
  [ROUTE_KEYS.CRYSTAL_STRUCTURES_DATABASE]: {
    path: '/crystal-structures',
    sidebarLabel: 'Crystal Structures',
    pageTitle: 'Crystal Structures',
  },
  [ROUTE_KEYS.LAYERED_STRUCTURES_DATABASE]: {
    path: '/layered-structures',
    sidebarLabel: 'Layered Structures',
    pageTitle: 'Layered Structures',
  },
  [ROUTE_KEYS.ANALYSIS]: {
    path: '/analysis',
    sidebarLabel: 'Analysis',
    pageTitle: 'Analysis',
  },
  [ROUTE_KEYS.SINGLE_JOB_SINGLE_MOLECULE]: {
    path: '/single-job/single-molecule',
    sidebarLabel: 'Single Molecule',
    pageTitle: 'Single Job / Single Molecule',
  },
  [ROUTE_KEYS.SINGLE_JOB_BINDER_CELL]: {
    path: '/single-job/binder-cell',
    sidebarLabel: 'Binder Cell',
    pageTitle: 'Single Job / Binder Cell',
  },
  [ROUTE_KEYS.SINGLE_JOB_INTERFACE_MOLECULES]: {
    path: '/single-job/interface-molecules',
    sidebarLabel: 'Interface Molecules',
    pageTitle: 'Single Job / Interface Molecules',
  },
  [ROUTE_KEYS.SINGLE_JOB_CRYSTAL_STRUCTURES]: {
    path: '/single-job/crystal-structures',
    sidebarLabel: 'Crystal Structures',
    pageTitle: 'Single Job / Crystal Structures',
  },
  [ROUTE_KEYS.SINGLE_JOB_LAYERED_STRUCTURE]: {
    path: '/single-job/layered-structure',
    sidebarLabel: 'Layered Structure',
    pageTitle: 'Single Job / Layered Structure',
  },
  [ROUTE_KEYS.BATCH_JOB_SINGLE_MOLECULE]: {
    path: '/batch-job/single-molecule',
    sidebarLabel: 'Single Molecule',
    pageTitle: 'Batch Job / Single Molecule',
  },
  [ROUTE_KEYS.BATCH_JOB_BINDER_CELL]: {
    path: '/batch-job/binder-cell',
    sidebarLabel: 'Binder Cell',
    pageTitle: 'Batch Job / Binder Cell',
  },
  [ROUTE_KEYS.BINDER_ANALYSIS]: {
    path: '/binder-analysis',
    sidebarLabel: 'Binder Analysis',
    pageTitle: 'Binder Analysis',
  },
  [ROUTE_KEYS.SETTINGS]: {
    path: '/settings',
    sidebarLabel: 'Settings',
    pageTitle: 'Settings',
  },
})

export function getRouteMeta(routeKey) {
  return ROUTE_META[routeKey] || null
}
