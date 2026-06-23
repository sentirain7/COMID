import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import BatchJobBinderCellResponsePanel from '../BatchJobBinderCellResponsePanel'

const baseResponse = {
  batch_job_id: 'batch-1',
  new: 0,
  duplicates: 0,
  submitted: 0,
  errors: 0,
  blocked: 0,
  similar_job_count: 0,
  jobs: [],
}

describe('BatchJobBinderCellResponsePanel', () => {
  it('shows only summarized FF artifact gate guidance', () => {
    render(
      <MemoryRouter>
        <BatchJobBinderCellResponsePanel
          latestResponse={{
            ...baseResponse,
            blocked: 2,
            ff_blocked_items: [
              {
                item_id: 'SA-Squalane',
                message: "Artifact not found for 'SA-Squalane'. Generate via legacy path.",
              },
              {
                item_id: 'SA-Hopane',
                message: "Artifact not found for 'SA-Hopane'. Generate via legacy path.",
              },
            ],
          }}
          isSubmission={false}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('2 species require FF artifacts before submission.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Manage FF artifacts/i })).toHaveAttribute(
      'href',
      '/molecules?mol_id=SA-Squalane',
    )
    expect(screen.queryByText(/Artifact not found/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/legacy path/i)).not.toBeInTheDocument()
  })

  it('does not show FF artifact guidance when no blocked items exist', () => {
    render(
      <MemoryRouter>
        <BatchJobBinderCellResponsePanel latestResponse={baseResponse} isSubmission={false} />
      </MemoryRouter>,
    )

    expect(screen.queryByText(/require FF artifacts/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Manage FF artifacts/i })).not.toBeInTheDocument()
  })
})
