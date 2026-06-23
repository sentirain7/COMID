/**
 * ParityPlot split color test.
 *
 * Pins:
 *   - shows the color legend when split labels (train/validation/test) are present
 *   - train_metrics shown separately
 *   - legacy responses without split fall back to residual color (no legend shown)
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ParityPlot from '../Charts/ParityPlot'

const SPLIT_DATA = {
  target: 'density',
  points: [
    { exp_id: 'a', actual: 1.0, predicted: 0.99, residual: 0.01, split: 'train' },
    { exp_id: 'b', actual: 1.05, predicted: 1.04, residual: 0.01, split: 'train' },
    { exp_id: 'c', actual: 0.95, predicted: 0.97, residual: -0.02, split: 'test' },
  ],
  metrics: { rmse: 0.015, r2: 0.98, mae: 0.012, n_points: 3 },
  train_metrics: { rmse: 0.01, r2: 0.99, mae: 0.008, n_points: 2 },
}

const LEGACY_DATA = {
  target: 'density',
  points: [
    { exp_id: 'a', actual: 1.0, predicted: 0.99, residual: 0.01 },
    { exp_id: 'b', actual: 0.95, predicted: 0.97, residual: -0.02 },
  ],
  metrics: { rmse: 0.015, r2: 0.98, mae: 0.012, n_points: 2 },
}

describe('ParityPlot split coloring', () => {
  it('shows split legend and train metrics when split labels present', () => {
    render(<ParityPlot data={SPLIT_DATA} loading={false} error={null} />)
    // 'Train' appears in both the color legend and the metrics (train/validation distinction)
    expect(screen.getAllByText('Train').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Test/Holdout')).toBeTruthy()
    // holdout + train metrics shown separately
    expect(screen.getByText('Holdout')).toBeTruthy()
    expect(screen.getByText(/R²: 0.9900/)).toBeTruthy() // train_metrics r2
  })

  it('falls back without split legend for legacy data', () => {
    render(<ParityPlot data={LEGACY_DATA} loading={false} error={null} />)
    expect(screen.queryByText('Train')).toBeNull()
    expect(screen.getByText('Holdout')).toBeTruthy()
  })

  it('renders empty state', () => {
    render(<ParityPlot data={{ points: [] }} loading={false} error={null} />)
    expect(screen.getByText(/No data for parity plot/)).toBeTruthy()
  })
})
