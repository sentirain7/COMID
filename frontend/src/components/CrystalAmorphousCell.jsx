import PlaceholderPage from './shared/PlaceholderPage'

function CrystalAmorphousCell() {
  return (
    <PlaceholderPage
      title="Crystal / Amorphous Cell"
      description="Stable structures after NVT+NPT completion for layer-based tensile and energy workflows."
      purposeItems={[
        'Store and manage stabilized structures from Single Job and Batch Job / Binder Cell.',
        'Treat listed structures as fully stabilized reference cells.',
        'Reuse as baseline inputs for layer generation, tensile tests, and energy calculations.',
      ]}
      emptyTitle="Saved Structures"
      emptyMessage="No stabilized structures available yet."
    />
  )
}

export default CrystalAmorphousCell
