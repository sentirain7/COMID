import { useState, useEffect } from 'react'
import { X, RefreshCw, AlertTriangle } from 'lucide-react'
import { getMoleculeStructure } from '../api/client'
import { SimpleViewer } from './MoleculeViewer'

/**
 * MoleculePreview - Modal component for 3D molecule structure preview.
 *
 * Displays a molecule's 3D structure in a modal overlay.
 * Uses SimpleViewer from MoleculeViewer for Three.js rendering.
 *
 * @param {string} molId - Molecule ID to display
 * @param {string} molName - Display name for the molecule
 * @param {function} onClose - Callback when modal is closed
 */
function MoleculePreview({ molId, molName, onClose }) {
  const [xyzData, setXyzData] = useState(null)
  const [bonds, setBonds] = useState([])
  const [atomCount, setAtomCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const loadStructure = async () => {
      try {
        setLoading(true)
        setError(null)
        const data = await getMoleculeStructure(molId)
        setXyzData(data.xyz)
        setBonds(data.bonds || [])
        setAtomCount(data.atom_count || 0)
      } catch (err) {
        console.error('Failed to load molecule structure:', err)
        setError(err.response?.data?.detail || err.message || 'Failed to load structure')
      } finally {
        setLoading(false)
      }
    }
    loadStructure()
  }, [molId])

  // Handle escape key to close modal
  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [onClose])

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-xl w-[420px] max-w-[90vw]">
        {/* Header */}
        <div className="flex justify-between items-center p-4 border-b border-slate-700">
          <div>
            <h3 className="text-lg font-semibold text-white">{molName}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-slate-400">{molId}</span>
              {atomCount > 0 && (
                <span className="text-xs text-slate-500">({atomCount} atoms)</span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-700 rounded"
          >
            <X size={20} />
          </button>
        </div>

        {/* 3D Viewer */}
        <div className="h-[320px] relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
              <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
            </div>
          )}

          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
              <div className="text-center p-4">
                <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-2" />
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            </div>
          )}

          {xyzData && !loading && !error && (
            <SimpleViewer xyzData={xyzData} bonds={bonds} />
          )}

          {!xyzData && !loading && !error && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
              <p className="text-slate-400 text-sm">No structure data available</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-700 text-center">
          <p className="text-xs text-slate-500">
            Drag to rotate, scroll to zoom
          </p>
        </div>
      </div>
    </div>
  )
}

export default MoleculePreview
