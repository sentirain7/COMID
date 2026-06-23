/**
 * COMID Logotype
 *
 * AI-Driven Computational Platform for Nanoscale Construction Material Inverse Design
 * COMID = COmplex Multiphase Integrated Dynamics
 *
 * Design concept:
 * - Same slate-400 (#94a3b8) as the sidebar menu items
 * - Gothic typeface (sans-serif)
 * - Left-aligned
 * - Clean, modern feel
 */

function NacmidLogotype({ className = "" }) {
  return (
    <svg
      viewBox="0 0 100 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <defs>
        {/* Subtle glow effect */}
        <filter id="nacmidGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.5" result="blur" />
          <feColorMatrix
            in="blur"
            type="matrix"
            values="0 0 0 0 0.58
                    0 0 0 0 0.64
                    0 0 0 0 0.72
                    0 0 0 0.4 0"
            result="glow"
          />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Main text - slate-400 (#94a3b8) */}
      <text
        x="0"
        y="18"
        textAnchor="start"
        filter="url(#nacmidGlow)"
        style={{
          fontSize: '18px',
          fontFamily: '"Pretendard Variable", "Noto Sans KR", system-ui, -apple-system, sans-serif',
          fontWeight: 700,
          letterSpacing: '0.06em',
          fill: '#94a3b8',
        }}
      >
        COMID
      </text>
    </svg>
  )
}

export default NacmidLogotype
