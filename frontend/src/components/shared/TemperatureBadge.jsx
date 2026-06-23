function TemperatureBadge({ tempCode }) {
  if (!tempCode) return null

  const temp = tempCode.slice(1)
  const tempK = parseInt(temp, 10)

  return (
    <span className="badge text-xs bg-cyan-500/20 text-cyan-400 border-cyan-500/30">
      {tempK}K
    </span>
  )
}

export default TemperatureBadge
