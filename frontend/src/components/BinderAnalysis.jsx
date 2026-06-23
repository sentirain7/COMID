import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  Beaker,
  Layers,
  Droplets,
  ArrowUpDown,
  Link2,
  Clock,
  FlaskConical,
  Trash2,
} from 'lucide-react'
import { NotificationBanner, PageHeader } from './shared'
import { useBinderStudies, useDeleteBinderStudy } from '../hooks/useApi'
import {
  BINDER_ANALYSIS_STATE_COLORS,
  BINDER_ANALYSIS_STATE_LABELS,
  INTENT_KIND_LABELS,
} from '../lib/constants'
import { ROUTE_KEYS, ROUTE_META } from '../navigation/routeMeta'
import StudyDetail from './binder-analysis/StudyDetail'

const BA_PATH = ROUTE_META[ROUTE_KEYS.BINDER_ANALYSIS].path

const STATE_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'intake', label: 'Intake' },
  { value: 'clarifying', label: 'Clarifying' },
  { value: 'planning', label: 'Planning' },
  { value: 'awaiting_confirmation', label: 'Confirm' },
  { value: 'executing', label: 'Executing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const INTENT_ICON_MAP = {
  bulk_property: Beaker,
  interface_adhesion: Layers,
  moisture_effect: Droplets,
  direct_tensile: ArrowUpDown,
  internal_cohesion: Link2,
  aging_comparison: Clock,
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString()
}

function StudyCard({ study, isActive, onDelete }) {
  const stateColor = BINDER_ANALYSIS_STATE_COLORS[study.state] || 'bg-slate-600 text-slate-200'
  const stateLabel = BINDER_ANALYSIS_STATE_LABELS[study.state] || study.state

  const intentKind = study.plan_summary?.intent_kind || null
  const IntentIcon = (intentKind && INTENT_ICON_MAP[intentKind]) || FlaskConical
  const intentLabel = (intentKind && INTENT_KIND_LABELS[intentKind]) || null

  const handleDelete = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onDelete?.(study.study_id)
  }

  return (
    <Link
      to={`${BA_PATH}/${study.study_id}`}
      className={`group block rounded border p-2 transition-colors ${
        isActive
          ? 'border-blue-400/60 bg-slate-700/60'
          : 'border-slate-700/40 bg-slate-800/30 hover:bg-slate-700/40'
      }`}
    >
      <div className="flex items-center gap-2">
        <IntentIcon className="w-3.5 h-3.5 shrink-0 text-slate-500" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[11px] font-medium text-slate-200 leading-tight">
            {study.problem_text || study.study_id}
          </div>
        </div>
        <span className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-medium leading-none ${stateColor}`}>
          {stateLabel}
        </span>
        <button
          type="button"
          onClick={handleDelete}
          className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded text-slate-500 hover:text-red-400 hover:bg-red-900/30 transition-all"
          title="Delete"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
      <div className="mt-0.5 pl-[22px] flex items-center gap-2 text-[9px] text-slate-500">
        {intentLabel && <span>{intentLabel}</span>}
        <span>{formatDate(study.created_at)}</span>
      </div>
    </Link>
  )
}

function BinderAnalysis() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { studyId } = useParams()
  const [stateFilter, setStateFilter] = useState('')

  const {
    data: studies,
    loading: listLoading,
    error: listError,
  } = useBinderStudies({ state: stateFilter || undefined }, 10000)

  const studyList = useMemo(() => studies || [], [studies])
  const activeStudyId = studyId || studyList[0]?.study_id || null

  useEffect(() => {
    if (!studyId && studyList.length > 0) {
      navigate(`${BA_PATH}/${studyList[0].study_id}`, { replace: true })
    }
  }, [studyId, studyList, navigate])

  const { mutateAsync: deleteStudy } = useDeleteBinderStudy()

  const handleDeleteStudy = useCallback(async (targetStudyId) => {
    if (!window.confirm('Delete this study?')) return
    try {
      await deleteStudy(targetStudyId)
      queryClient.removeQueries({ queryKey: ['binder-study-detail', targetStudyId] })
      queryClient.removeQueries({ queryKey: ['binder-study-results', targetStudyId] })
      if (activeStudyId === targetStudyId) {
        navigate(BA_PATH, { replace: true })
      }
    } catch {
      // mutation invalidates cache automatically on success
    }
  }, [deleteStudy, activeStudyId, navigate, queryClient])

  return (
    <div className="space-y-3">
      <PageHeader
        routeKey={ROUTE_KEYS.BINDER_ANALYSIS}
        subtitle="Monitor existing binder analysis studies."
      />

      {listError && (
        <NotificationBanner
          notification={{ type: 'error', message: listError }}
          onDismiss={() => {}}
        />
      )}

      {/* Full-height grid: left sidebar pinned, right scrolls */}
      <div className="grid gap-3 lg:grid-cols-[360px_minmax(0,1fr)] items-start">
        {/* ── Left sidebar ── */}
        <div className="lg:sticky lg:top-[4.5rem] lg:self-start flex flex-col gap-3 lg:h-[calc(100vh-6rem)]">
          {/* Studies — grows to fill, scrolls */}
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-2.5 flex flex-col min-h-0 flex-1">
            <div className="mb-1.5 flex items-center justify-between gap-1.5 shrink-0">
              <h2 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Studies</h2>
              <select
                className="input py-0 px-1.5 text-[10px] leading-5"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value)}
              >
                {STATE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0 -mr-1 pr-1">
              {listLoading ? (
                <p className="text-[11px] text-slate-500 py-3 text-center">Loading...</p>
              ) : studyList.length === 0 ? (
                <p className="text-[11px] text-slate-500 py-3 text-center">No studies found.</p>
              ) : (
                <div className="space-y-1.5">
                  {studyList.map((study) => (
                    <StudyCard
                      key={study.study_id}
                      study={study}
                      isActive={activeStudyId === study.study_id}
                      onDelete={handleDeleteStudy}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Right main ── */}
        <section className="lg:h-[calc(100vh-6rem)] lg:overflow-y-auto">
          {!activeStudyId ? (
            <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-8 text-sm text-slate-400 text-center">
              Select a study to view its analysis.
            </div>
          ) : (
            <StudyDetail studyId={activeStudyId} />
          )}
        </section>
      </div>
    </div>
  )
}

export default BinderAnalysis
