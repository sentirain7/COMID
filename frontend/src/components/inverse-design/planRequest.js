import { INVERSE_TARGET_METRICS } from '../../lib/constants'

const METRIC_BY_NAME = INVERSE_TARGET_METRICS.reduce((acc, m) => {
  acc[m.name] = m
  return acc
}, {})

export function getMetricInfo(name) {
  return METRIC_BY_NAME[name] || {}
}

export function isInterfaceMetric(name) {
  return METRIC_BY_NAME[name]?.group === 'Interface'
}

/** Wizard form state → POST /inverse-design/plan request body (§8 ①→②). */
export function buildPlanRequest(form) {
  const body = {
    custom_targets: form.targets.map((t) => ({
      metric_name: t.metric_name,
      target_min: t.target_min,
      target_max: t.target_max,
      direction: t.direction,
    })),
    temperature_k_fixed: form.temperatureK,
    moisture_damage: form.moistureDamage,
  }
  // Inverse-design decision variables: fixed binder_type selection + structure_size
  // (SARA composition is determined by the binder YAML SSOT — not explored).
  // Only the additive type and amount are exploration axes.
  if (form.binderType) body.binder_types = [form.binderType]
  if (form.structureSize) body.structure_size = form.structureSize
  if (form.includeAdditive) {
    body.include_additive = true
    if (form.additiveType) body.additive_type = form.additiveType
    else body.explore_all_additives = true
  }
  const needsAggregates = form.targets.some((t) => isInterfaceMetric(t.metric_name))
  if (needsAggregates && form.aggregates.length > 0) {
    body.aggregate_specs = form.aggregates.map((material) => ({ material }))
  }
  return body
}
