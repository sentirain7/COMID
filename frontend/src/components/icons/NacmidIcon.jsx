/**
 * COMID Custom Logo Icon
 *
 * AI-Driven Computational Platform for Nanoscale Construction Material Inverse Design
 * COMID = COmplex Multiphase Integrated Dynamics
 *
 * Design concept:
 * - Three-tier layered structure (construction material layers)
 * - Molecular nodes and connecting lines (MD simulation)
 * - Blue/purple gradient
 */

function NacmidIcon({ className = "" }) {
  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <defs>
        {/* Layer gradient - blue/purple */}
        <linearGradient id="iconLayerGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#60a5fa" />
          <stop offset="100%" stopColor="#a78bfa" />
        </linearGradient>

        {/* Node gradient */}
        <linearGradient id="iconNodeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#e0e7ff" />
        </linearGradient>

        {/* Glow effect */}
        <filter id="iconGlow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="1.5" result="blur" />
          <feColorMatrix
            in="blur"
            type="matrix"
            values="0 0 0 0 0.4
                    0 0 0 0 0.6
                    0 0 0 0 1
                    0 0 0 0.4 0"
            result="glow"
          />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>

        {/* Drop shadow */}
        <filter id="iconShadow" x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="2" stdDeviation="2" floodColor="#000000" floodOpacity="0.3" />
        </filter>
      </defs>

      {/* Background - dark slate rounded rectangle */}
      <rect
        x="2"
        y="2"
        width="44"
        height="44"
        rx="10"
        fill="#1e293b"
        filter="url(#iconShadow)"
      />

      {/* Inner border highlight */}
      <rect
        x="3"
        y="3"
        width="42"
        height="42"
        rx="9"
        fill="none"
        stroke="url(#iconLayerGrad)"
        strokeWidth="0.5"
        opacity="0.5"
      />

      {/* Layered structure - 3 layers (construction materials) */}
      <g filter="url(#iconGlow)">
        {/* Top layer */}
        <rect x="8" y="10" width="32" height="6" rx="2" fill="url(#iconLayerGrad)" opacity="0.9" />

        {/* Middle layer */}
        <rect x="8" y="20" width="32" height="6" rx="2" fill="url(#iconLayerGrad)" opacity="0.7" />

        {/* Bottom layer */}
        <rect x="8" y="30" width="32" height="6" rx="2" fill="url(#iconLayerGrad)" opacity="0.5" />
      </g>

      {/* Molecular connecting lines (inter-layer bonds) */}
      <g stroke="white" strokeWidth="1.5" opacity="0.6">
        <line x1="16" y1="16" x2="16" y2="20" />
        <line x1="24" y1="16" x2="24" y2="20" />
        <line x1="32" y1="16" x2="32" y2="20" />
        <line x1="16" y1="26" x2="16" y2="30" />
        <line x1="24" y1="26" x2="24" y2="30" />
        <line x1="32" y1="26" x2="32" y2="30" />
      </g>

      {/* Molecular nodes (atom positions) */}
      <g filter="url(#iconGlow)">
        {/* Top nodes */}
        <circle cx="16" cy="13" r="2.5" fill="url(#iconNodeGrad)" />
        <circle cx="24" cy="13" r="2.5" fill="url(#iconNodeGrad)" />
        <circle cx="32" cy="13" r="2.5" fill="url(#iconNodeGrad)" />

        {/* Middle nodes */}
        <circle cx="16" cy="23" r="2" fill="white" opacity="0.8" />
        <circle cx="24" cy="23" r="2" fill="white" opacity="0.8" />
        <circle cx="32" cy="23" r="2" fill="white" opacity="0.8" />

        {/* Bottom nodes */}
        <circle cx="16" cy="33" r="1.8" fill="white" opacity="0.6" />
        <circle cx="24" cy="33" r="1.8" fill="white" opacity="0.6" />
        <circle cx="32" cy="33" r="1.8" fill="white" opacity="0.6" />
      </g>

      {/* Diagonal connections (inter-molecular interactions) */}
      <g stroke="white" strokeWidth="0.8" opacity="0.3">
        <line x1="16" y1="13" x2="24" y2="23" />
        <line x1="24" y1="13" x2="32" y2="23" />
        <line x1="24" y1="13" x2="16" y2="23" />
        <line x1="32" y1="13" x2="24" y2="23" />
        <line x1="16" y1="23" x2="24" y2="33" />
        <line x1="24" y1="23" x2="32" y2="33" />
        <line x1="24" y1="23" x2="16" y2="33" />
        <line x1="32" y1="23" x2="24" y2="33" />
      </g>
    </svg>
  )
}

export default NacmidIcon
