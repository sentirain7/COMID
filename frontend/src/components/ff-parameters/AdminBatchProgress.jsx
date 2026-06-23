/**
 * v00.99.57 — Admin batch progress bar.
 *
 * Stacked segmented bar + labelled buckets so the operator sees at a
 * glance where every mol is: baseline-succeeded, sqm_robust-recovered,
 * failed, in-flight, or still pending. Segment widths sum to
 * total, so the composition is self-evident without mental arithmetic.
 */
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'

// v00.99.58: each terminal bucket is a distinct segment + label so the
// operator can read outcomes without mental arithmetic.
//   baseline_ok  — succeeded on the default profile
//   robust_ok    — baseline failed, sqm_robust recovered
//   robust_fail  — baseline failed, sqm_robust also failed
//   baseline_fail — non-retryable baseline failure (never escalated)
//   inProgress   — currently running
//   pending      — not yet submitted
const SEGMENT_STYLES = {
  baselineOk: 'bg-emerald-500',
  robustOk: 'bg-indigo-500',
  robustFail: 'bg-red-500',
  baselineFail: 'bg-orange-500',
  inProgress: 'bg-white animate-pulse',
  inProgressBaseline: 'bg-white animate-pulse',
  inProgressRobust: 'bg-slate-200 animate-pulse',
  pending: 'bg-slate-600',
}

const DOT_STYLES = {
  baselineOk: 'bg-emerald-500',
  robustOk: 'bg-indigo-500',
  robustFail: 'bg-red-500',
  baselineFail: 'bg-orange-500',
  inProgress: 'bg-white',
  inProgressBaseline: 'bg-white',
  inProgressRobust: 'bg-slate-200',
  pending: 'bg-slate-600',
}

function Dot({ kind }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        'inline-block w-1.5 h-1.5 rounded-full',
        DOT_STYLES[kind],
      )}
    />
  )
}

export default function AdminBatchProgress({ progress, onCancel, cancelDisabled, onReset, resetDisabled, onDismiss }) {
  if (!progress) return null
  const isAdminBatch = progress.batch_kind === 'admin'
  const running = Boolean(progress.running)
  if (!isAdminBatch && !running) return null
  const isPublicConflict = running && !isAdminBatch

  const total = Number(progress.total) || 0
  const completed = Number(progress.completed) || 0
  const failed = Number(progress.failed) || 0
  const skipped = Number(progress.skipped) || 0
  const retried = Number(progress.retried) || 0
  const retriedSucceededRaw = progress.retried_succeeded
  const retriedSucceeded = Number(retriedSucceededRaw) || 0
  const inProgress = Number(progress.in_progress) || 0
  // v00.99.90: profile-specific in-flight counters populated by the
  // orchestrator from a shared phase_map (Manager.dict). Legacy
  // backends omit these fields; fall back to the combined `in_progress`.
  const inProgressBaselineRaw = progress.in_progress_baseline
  const inProgressRobustRaw = progress.in_progress_robust
  const hasPhaseSplit =
    inProgressBaselineRaw !== undefined || inProgressRobustRaw !== undefined
  const inProgressBaseline = Number(inProgressBaselineRaw) || 0
  const inProgressRobust = Number(inProgressRobustRaw) || 0

  // v00.99.57 legacy detection: old backend sends `retried` but not
  // `retried_succeeded`. Surface an informational hint so the operator
  // knows retries were attempted even though we can't split outcomes.
  const isLegacyPayload = retriedSucceededRaw === undefined && retried > 0
  const baselineOk = Math.max(0, completed - retriedSucceeded)
  const robustOk = retriedSucceeded
  // v00.99.66: legacy payload keeps retriedSucceeded at 0 which would make
  // robustFail = retried even though some retries already landed in
  // `completed` (→ baselineOk). That double-counts and pushes bucket sum
  // over total. When retried_succeeded is missing, we cannot split the
  // retried outcomes, so refuse to attribute any to robustFail — the
  // isLegacyPayload hint tells the operator retries were attempted.
  const robustFail = isLegacyPayload
    ? 0
    : Math.max(0, retried - retriedSucceeded)
  // Failures that never went through the sqm_robust escalation (non-retryable
  // baseline errors like ANTECHAMBER_FAILED). `failed` is the total; subtract
  // the retry-final-failed subset to isolate straight baseline failures.
  const baselineFail = Math.max(0, failed - robustFail)
  const pending = Math.max(0, total - completed - failed - skipped - inProgress)
  const done = completed + failed + skipped

  // `percent` feeds the `title=` tooltip on the cell grid.
  const percent = total > 0 ? Math.min(100, (done / total) * 100) : 0

  // v00.99.60: `running` flag alone lags release_batch_slot by 100~500ms
  // after the final future completes (ProcessPoolExecutor cleanup window).
  // Require there's still work left so the spinner / Cancel button stop
  // the moment every mol reached a terminal bucket, rather than waiting
  // for the next 3-second poll to observe running=false.
  const isActuallyRunning = running && total > 0 && done < total

  if (import.meta.env?.DEV && total > 0) {
    const sum = baselineOk + robustOk + robustFail + baselineFail + skipped + inProgress + pending
    if (sum !== total) {
      console.warn(
        `[AdminBatchProgress] bucket sum ${sum} ≠ total ${total}`,
        { baselineOk, robustOk, robustFail, baselineFail, skipped, inProgress, pending },
      )
    }
  }

  // Bar segments — all non-zero buckets including pending.
  // When phase split is available, Running is separated into
  // Baseline Running and Robust Running for distinct bar colors.
  const runningSegments = hasPhaseSplit
    ? [
        { kind: 'inProgressBaseline', n: inProgressBaseline, label: 'Run Base' },
        { kind: 'inProgressRobust', n: inProgressRobust, label: 'Run Robust' },
      ]
    : [{ kind: 'inProgress', n: inProgress, label: 'Running' }]

  const segments = [
    { kind: 'baselineOk', n: baselineOk, label: 'Base Pass' },
    { kind: 'robustOk', n: robustOk, label: 'Robust Pass' },
    { kind: 'robustFail', n: robustFail, label: 'Robust Fail' },
    { kind: 'baselineFail', n: baselineFail, label: 'Base Fail' },
    ...runningSegments,
    { kind: 'pending', n: pending, label: 'Pending' },
  ].filter((s) => s.n > 0)

  // Build per-molecule square array: one cell per molecule, ordered by status.
  const cells = []
  for (const { kind, n } of segments) {
    for (let i = 0; i < n; i++) cells.push(kind)
  }

  // All possible legend items in display order (always show, count may be 0).
  const legendItems = [
    { kind: 'baselineOk', label: 'Base Pass', n: baselineOk },
    { kind: 'robustOk', label: 'Robust Pass', n: robustOk },
    { kind: 'baselineFail', label: 'Base Fail', n: baselineFail },
    { kind: 'robustFail', label: 'Robust Fail', n: robustFail },
    ...(hasPhaseSplit
      ? [
          { kind: 'inProgressBaseline', label: 'Run Base', n: inProgressBaseline },
          { kind: 'inProgressRobust', label: 'Run Robust', n: inProgressRobust },
        ]
      : [{ kind: 'inProgress', label: 'Running', n: inProgress }]),
    { kind: 'pending', label: 'Pending', n: pending },
  ]

  return (
    <div
      className="text-xs"
      data-testid="admin-batch-progress"
      role="progressbar"
      aria-valuenow={done}
      aria-valuemin={0}
      aria-valuemax={total}
    >
      <div className="flex items-center gap-4 rounded border border-slate-700 bg-slate-800/40 px-3 py-1.5">
        {/* Square grid — 2x gap, larger cells */}
        <div
          className="flex flex-wrap gap-0.5"
          data-testid="admin-batch-progress-bar"
          title={`${done}/${total} (${percent.toFixed(0)}%)`}
        >
          {cells.map((kind, i) => (
            <div
              key={i}
              className={clsx('w-2.5 h-2.5 rounded-sm', SEGMENT_STYLES[kind]?.replace(' animate-pulse', ''))}
              data-testid={`admin-batch-cell-${kind}`}
            />
          ))}
        </div>

        {/* Legend + progress + actions — pushed to right */}
        <div className="flex items-center gap-4 ml-auto flex-shrink-0">
          {/* Fixed legend — 2-row grid, always visible (0 = dimmed) */}
          {!isPublicConflict && (
            <div
              className="grid grid-cols-4 gap-x-3 gap-y-0 text-[10px] flex-shrink-0"
              data-testid="admin-batch-progress-results"
            >
              {legendItems.map(({ kind, label, n }) => (
                <span
                  key={kind}
                  className={clsx(
                    'inline-flex items-center gap-0.5 whitespace-nowrap leading-tight',
                    n > 0 ? 'text-slate-300' : 'text-slate-600'
                  )}
                >
                  <Dot kind={kind} />
                  {label} {n}
                </span>
              ))}
            </div>
          )}

          {/* Progress text + actions */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
          {isActuallyRunning && <Loader2 className="h-3 w-3 animate-spin text-slate-400" />}
          <span className="text-[10px] text-slate-400 whitespace-nowrap">
            {done}/{total}
          </span>
          {isActuallyRunning && isAdminBatch && !progress.cancelled && (
            <>
              <button
                type="button"
                onClick={() => onCancel?.({ force: false })}
                disabled={cancelDisabled}
                className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-300 hover:bg-red-500/30 disabled:opacity-40"
                data-testid="admin-batch-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  if (window.confirm('This deletes all lock files and force-terminates the batch. Continue?')) {
                    onCancel?.({ force: true })
                  }
                }}
                disabled={cancelDisabled}
                className="rounded bg-red-600/30 px-1.5 py-0.5 text-[10px] text-red-200 hover:bg-red-600/40 disabled:opacity-40"
                data-testid="admin-batch-force-cancel"
              >
                Force
              </button>
            </>
          )}
          {isActuallyRunning && isAdminBatch && progress.cancelled && onReset && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm('If there is no progress after Cancel, all lock files will be deleted. Continue?')) {
                  onCancel?.({ force: true })
                }
              }}
              disabled={resetDisabled}
              className="rounded bg-orange-500/20 px-1.5 py-0.5 text-[10px] text-orange-300 hover:bg-orange-500/30 disabled:opacity-40"
              data-testid="admin-batch-reset"
            >
              Force Reset
            </button>
          )}
          {/* Stuck state: running=true but no work left (process terminated abnormally) */}
          {!isActuallyRunning && running && isAdminBatch && onCancel && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm('This force-clears the stuck state. All lock files will be deleted. Continue?')) {
                  onCancel?.({ force: true })
                }
              }}
              className="rounded bg-orange-600/30 px-1.5 py-0.5 text-[10px] text-orange-200 hover:bg-orange-600/40"
              data-testid="admin-batch-force-reset-stuck"
            >
              Force Reset
            </button>
          )}
          {!isActuallyRunning && onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300 hover:bg-slate-600"
              data-testid="admin-batch-dismiss"
            >
              Close
            </button>
          )}
        </div>
        </div>
      </div>

    </div>
  )
}
