/**
 * v00.99.58 + v00.99.66 — AdminBatchProgress per-molecule cell grid tests.
 *
 * v00.99.66: the component renders one small square per molecule (not a
 * per-segment width bar). Legend items always render (dimmed if 0). These
 * tests target the current cell-grid implementation instead of the
 * historical segment-width design.
 *
 * Pins:
 *   - one cell per molecule, kind drawn from bucket assignment
 *   - bucket sum equals total (no dev `bucket sum ≠ total` warning)
 *   - legend always renders every label, count follows the bucket
 *   - Cancel button only when admin + running
 *   - public batch conflict hides the legend
 *   - legacy payload (no retried_succeeded) falls back to robustFail=0
 */
import { render, screen } from '@testing-library/react'
import AdminBatchProgress from '../ff-parameters/AdminBatchProgress'

function renderBar(progress, props = {}) {
  return render(
    <AdminBatchProgress
      progress={progress}
      onCancel={() => {}}
      cancelDisabled={false}
      {...props}
    />,
  )
}

function cellsByKind(kind) {
  return document.querySelectorAll(`[data-testid="admin-batch-cell-${kind}"]`)
}

describe('AdminBatchProgress — cell grid buckets', () => {
  it('renders one cell per molecule across the expected buckets', () => {
    // baselineOk = completed(12) - retried_succeeded(2) = 10
    // robustOk   = retried_succeeded(2) = 2
    // robustFail = retried(2) - retried_succeeded(2) = 0 → no cells
    // baselineFail = failed(1) - robustFail(0) = 1
    // inProgress = 2
    // pending    = 20 - 12 - 1 - 0 - 2 = 5
    renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 20,
      completed: 12,
      retried: 2,
      retried_succeeded: 2,
      failed: 1,
      skipped: 0,
      in_progress: 2,
    })

    expect(cellsByKind('baselineOk')).toHaveLength(10)
    expect(cellsByKind('robustOk')).toHaveLength(2)
    expect(cellsByKind('robustFail')).toHaveLength(0)
    expect(cellsByKind('baselineFail')).toHaveLength(1)
    expect(cellsByKind('inProgress')).toHaveLength(2)
    expect(cellsByKind('pending')).toHaveLength(5)

    // Total cells equals total molecules — the fundamental invariant.
    const allCells = screen
      .getByTestId('admin-batch-progress-bar')
      .querySelectorAll('[data-testid^="admin-batch-cell-"]')
    expect(allCells).toHaveLength(20)
  })

  it('dims zero-count legend entries instead of hiding them', () => {
    renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 3,
      completed: 3,
      retried: 0,
      retried_succeeded: 0,
      failed: 0,
      skipped: 0,
      in_progress: 0,
    })

    const results = screen.getByTestId('admin-batch-progress-results')
    // All 7 labels are always in the legend (Run Base/Robust split when the
    // backend reports phase-aware counters; this payload doesn't so Running
    // is the unified label).
    expect(results).toHaveTextContent(/Base Pass 3/)
    expect(results).toHaveTextContent(/Robust Pass 0/)
    expect(results).toHaveTextContent(/Base Fail 0/)
    expect(results).toHaveTextContent(/Robust Fail 0/)
    expect(results).toHaveTextContent(/Skipped 0/)
    expect(results).toHaveTextContent(/Running 0/)
    expect(results).toHaveTextContent(/Pending 0/)
  })

  it('splits baseline / robust success / robust fail / baseline fail into distinct labels', () => {
    // completed(6) = baseline 5 + retried_succeeded 1
    // retried(3)   = retried_succeeded(1) + robustFail(2)
    // failed(3)    = robustFail(2) + baselineFail(1)
    renderBar({
      running: false,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 10,
      completed: 6,
      retried: 3,
      retried_succeeded: 1,
      failed: 3,
      skipped: 0,
      in_progress: 0,
    })

    const results = screen.getByTestId('admin-batch-progress-results')
    expect(results).toHaveTextContent(/Base Pass 5/)
    expect(results).toHaveTextContent(/Robust Pass 1/)
    expect(results).toHaveTextContent(/Robust Fail 2/)
    expect(results).toHaveTextContent(/Base Fail 1/)
    // Pending = 10 - 6 - 3 - 0 - 0 = 1
    expect(results).toHaveTextContent(/Pending 1/)
  })
})

describe('AdminBatchProgress — Cancel button', () => {
  it('renders Cancel only when admin + running', () => {
    renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 3,
      completed: 1,
      in_progress: 1,
    })
    expect(screen.getByTestId('admin-batch-cancel')).toBeInTheDocument()
  })

  it('hides the legend during a public batch conflict', () => {
    renderBar({
      running: true,
      batch_kind: 'public',
      generation_profile: 'baseline',
      total: 3,
      completed: 1,
    })
    // Cancel never fires on a public batch.
    expect(screen.queryByTestId('admin-batch-cancel')).toBeNull()
    // Legend is hidden — the operator has no admin-side lever to pull.
    expect(screen.queryByTestId('admin-batch-progress-results')).toBeNull()
    // The component still mounts (so the progress count stays visible).
    expect(screen.getByTestId('admin-batch-progress')).toBeInTheDocument()
  })

  it('does not render Cancel once the admin batch finishes', () => {
    renderBar({
      running: false,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 3,
      completed: 3,
      in_progress: 0,
    })
    expect(screen.queryByTestId('admin-batch-cancel')).toBeNull()
  })

  it('hides Cancel the moment done === total even if running=true is still lingering', () => {
    // v00.99.60: release_batch_slot lags the last future by 100~500ms;
    // the UI must not wait for running=false to stop signalling activity.
    const { container } = renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 3,
      completed: 3,
      retried_succeeded: 0,
      failed: 0,
      skipped: 0,
      in_progress: 0,
    })
    expect(screen.queryByTestId('admin-batch-cancel')).toBeNull()
    // Spinner (Loader2) is also gated by the same derived flag.
    expect(container.querySelector('.animate-spin')).toBeNull()
  })

  it('keeps Cancel + spinner while done < total even with lingering running=true', () => {
    const { container } = renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 3,
      completed: 1,
      retried_succeeded: 0,
      failed: 0,
      skipped: 0,
      in_progress: 2,
    })
    expect(screen.getByTestId('admin-batch-cancel')).toBeInTheDocument()
    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })
})

describe('AdminBatchProgress — legacy payload fallback', () => {
  // v00.99.66 bucket-sum fix: legacy payloads without `retried_succeeded`
  // used to assign robustFail = retried, which double-counted retries that
  // had already landed in `completed` (→ baselineOk). Bucket sum then
  // exceeded total. With the fix, isLegacyPayload forces robustFail = 0.
  it('does not double-count retried molecules when retried_succeeded is absent', () => {
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    renderBar({
      running: true,
      batch_kind: 'admin',
      generation_profile: 'baseline',
      total: 5,
      completed: 2,        // includes the 1 retried+succeeded mol
      retried: 1,          // old backend reports this…
      // retried_succeeded intentionally omitted (legacy backend)
      failed: 0,
      skipped: 0,
      in_progress: 1,
    })

    // baselineOk(2) + robustOk(0) + robustFail(0) + baselineFail(0)
    //   + skipped(0) + inProgress(1) + pending(2) === total(5)
    // Pre-fix: robustFail=1 → sum 6, which is > total and triggers the
    // dev warning below. Post-fix: no warning.
    expect(consoleWarn).not.toHaveBeenCalled()

    // Cells are one per molecule (see AdminBatchProgress cells[] loop), so
    // the rendered cell count equals total when buckets don't double-count.
    const cells = screen
      .getByTestId('admin-batch-progress-bar')
      .querySelectorAll('[data-testid^="admin-batch-cell-"]')
    expect(cells).toHaveLength(5)

    // Robust cells must be absent for legacy payloads (no split signal).
    expect(cellsByKind('robustFail')).toHaveLength(0)
    expect(cellsByKind('robustOk')).toHaveLength(0)

    consoleWarn.mockRestore()
  })

  it('renders nothing for an empty progress payload', () => {
    const { container } = renderBar(null)
    expect(container).toBeEmptyDOMElement()
  })
})
