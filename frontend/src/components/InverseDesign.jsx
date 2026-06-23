import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageHeader } from './shared'
import { ROUTE_KEYS } from '../navigation/routeMeta'
import { useApproveInversePlan, usePreviewInversePlan } from '../hooks/useApi'
import TargetPropertiesForm from './inverse-design/TargetPropertiesForm'
import DesignPlanReview from './inverse-design/DesignPlanReview'
import PipelineMonitor from './inverse-design/PipelineMonitor'
import TargetVsActualPanel from './inverse-design/TargetVsActualPanel'
import { buildPlanRequest } from './inverse-design/planRequest'
import {
  INVERSE_TARGET_METRICS,
  FALLBACK_BINDER_TYPE_NAMES,
  STRUCTURE_SIZE_OPTIONS,
} from '../lib/constants'

const STEPS = ['① Targets', '② Plan review', '③ Progress', '④ Results']

const INITIAL_FORM = {
  targets: [
    {
      metric_name: INVERSE_TARGET_METRICS[0].name,
      direction: 'maximize',
      target_min: null,
      target_max: null,
    },
  ],
  temperatureK: 298.0,
  aggregates: [],
  binderType: FALLBACK_BINDER_TYPE_NAMES[0],
  structureSize: STRUCTURE_SIZE_OPTIONS[0],
  includeAdditive: false,
  additiveType: null,
  moistureDamage: false,
}

function StepIndicator({ current }) {
  return (
    <div className="flex gap-2 text-sm">
      {STEPS.map((label, i) => (
        <span
          key={label}
          className={`px-2 py-1 rounded ${
            i === current
              ? 'bg-sky-600 text-white'
              : i < current
                ? 'bg-slate-700 text-emerald-300'
                : 'bg-slate-800 text-slate-500'
          }`}
        >
          {label}
        </span>
      ))}
    </div>
  )
}

/**
 * Inverse design wizard (plan §8) — ① target input → ② plan review/approval →
 * ③ progress (3s polling) → ④ target vs actual results (including mean±SE ensemble).
 * The `?pipeline=<id>` query lets you re-enter an in-progress pipeline.
 */
function InverseDesign() {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlPipelineId = searchParams.get('pipeline')

  const [step, setStep] = useState(urlPipelineId ? 2 : 0)
  const [form, setForm] = useState(INITIAL_FORM)
  const [planResult, setPlanResult] = useState(null)
  const [pipelineId, setPipelineId] = useState(urlPipelineId)
  const [approval, setApproval] = useState(null)

  const previewMutation = usePreviewInversePlan()
  const approveMutation = useApproveInversePlan()

  const handlePreview = () => {
    previewMutation.mutate(buildPlanRequest(form), {
      onSuccess: (data) => {
        setPlanResult(data)
        setStep(1)
      },
    })
  }

  const handleApprove = () => {
    approveMutation.mutate(
      { plan: planResult.plan, plan_hash: planResult.plan_hash },
      {
        onSuccess: (data) => {
          setApproval(data)
          setPipelineId(data.pipeline_id)
          setSearchParams({ pipeline: data.pipeline_id }, { replace: true })
          setStep(2)
        },
      },
    )
  }

  const errorText = (err) =>
    err?.response?.data?.detail?.message || err?.response?.data?.detail || err?.message

  return (
    <div className="space-y-6">
      <PageHeader
        routeKey={ROUTE_KEYS.INVERSE_DESIGN}
        subtitle="Target properties → composition/additive inverse design → automated DOE (deterministic pipeline)"
      >
        <StepIndicator current={step} />
      </PageHeader>

      {step === 0 && (
        <TargetPropertiesForm
          value={form}
          onChange={setForm}
          onSubmit={handlePreview}
          submitting={previewMutation.isPending}
          error={previewMutation.isError ? errorText(previewMutation.error) : null}
        />
      )}

      {step === 1 && planResult && (
        <DesignPlanReview
          plan={planResult.plan}
          planHash={planResult.plan_hash}
          onApprove={handleApprove}
          onBack={() => setStep(0)}
          approving={approveMutation.isPending}
          error={approveMutation.isError ? errorText(approveMutation.error) : null}
        />
      )}

      {step === 2 && pipelineId && (
        <div className="space-y-3">
          {approval && (
            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(approval.counts || {}).map(([action, count]) => (
                <span key={action} className="bg-slate-700/50 rounded px-2 py-1 text-slate-200">
                  {action}: {count}
                </span>
              ))}
            </div>
          )}
          <PipelineMonitor pipelineId={pipelineId} onShowResults={() => setStep(3)} />
        </div>
      )}

      {step === 3 && pipelineId && (
        <div className="space-y-3">
          <TargetVsActualPanel pipelineId={pipelineId} />
          <button
            type="button"
            onClick={() => setStep(2)}
            className="px-4 py-2 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm"
          >
            ← Back to progress
          </button>
        </div>
      )}
    </div>
  )
}

export default InverseDesign
