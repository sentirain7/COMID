import { useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { ELEMENT_COLORS, normalizeElementSymbol, getElementColorHex } from './elementColors'
import { parseAtomLine } from './xyzParser'

// Create a simple sphere-based 3D viewer using Three.js
// Exported for reuse in MoleculePreview component
export function SimpleViewer({
  xyzData,
  boxSize,
  bonds,
  onLoad,
  showAxes = false,
  zUp = false,
  fitToFrame = false,
  fitPadding = 1.08,
  representation = 'ball_and_stick',
}) {
  const containerRef = useRef(null)
  const rendererRef = useRef(null)
  const sceneRef = useRef(null)
  const cameraRef = useRef(null)
  const animationRef = useRef(null)
  const controlsRef = useRef(null)
  // v00.99.71: generation counter — each effect run gets a unique id. Async
  // import/setup paths check this on every await boundary so out-of-order
  // completions (prior dep-change still resolving after a newer one) do not
  // overwrite the current renderer or touch the DOM post-unmount.
  const genRef = useRef(0)
  const [isLoaded, setIsLoaded] = useState(false)
  const [initError, setInitError] = useState(null)

  // Reset loaded/error state when the structure source changes so the outer
  // loader is visible while the new scene is being constructed.
  useEffect(() => {
    setIsLoaded(false)
    setInitError(null)
  }, [xyzData])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !xyzData) return undefined

    const gen = ++genRef.current
    let disposed = false
    let resizeHandler = null

    // Dynamically import Three.js
    import('three').then(async (THREE) => {
      const { OrbitControls } = await import('three/addons/controls/OrbitControls.js')
      if (disposed || gen !== genRef.current) return

      // Parse XYZ data
      const lines = xyzData.split('\n')
      const nAtoms = parseInt(lines[0])
      const atoms = []

      for (let i = 2; i < 2 + nAtoms && i < lines.length; i++) {
        const atom = parseAtomLine(lines[i])
        if (atom) atoms.push(atom)
      }

      // Clear previous scene
      if (rendererRef.current) {
        cancelAnimationFrame(animationRef.current)
        try {
          if (rendererRef.current.domElement.parentNode === container) {
            container.removeChild(rendererRef.current.domElement)
          }
        } catch { /* container may be detached mid-teardown */ }
        rendererRef.current.dispose()
        rendererRef.current = null
      }

      // Setup scene
      const scene = new THREE.Scene()
      scene.background = new THREE.Color(0x1e293b) // slate-800
      sceneRef.current = scene

      // Setup camera
      const width = container.clientWidth
      const height = container.clientHeight
      const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 5000)
      if (zUp) {
        camera.up.set(0, 0, 1)
      }
      cameraRef.current = camera

      // Setup renderer
      const renderer = new THREE.WebGLRenderer({ antialias: true })
      renderer.setSize(width, height)
      renderer.setPixelRatio(window.devicePixelRatio)
      container.appendChild(renderer.domElement)
      rendererRef.current = renderer

      // Setup controls
      const controls = new OrbitControls(camera, renderer.domElement)
      controls.enableDamping = true
      controls.dampingFactor = 0.05
      controlsRef.current = controls

      // Add lighting
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.5)
      scene.add(ambientLight)
      const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8)
      directionalLight.position.set(100, 100, 100)
      scene.add(directionalLight)

      // Calculate center of atoms
      let centerX = 0, centerY = 0, centerZ = 0
      atoms.forEach(atom => {
        centerX += atom.x
        centerY += atom.y
        centerZ += atom.z
      })
      centerX /= atoms.length || 1
      centerY /= atoms.length || 1
      centerZ /= atoms.length || 1

      let maxDim = 0
      if (boxSize && boxSize.length === 3) {
        maxDim = Math.max(...boxSize)
      } else if (atoms.length > 0) {
        let minX = atoms[0].x
        let maxX = atoms[0].x
        let minY = atoms[0].y
        let maxY = atoms[0].y
        let minZ = atoms[0].z
        let maxZ = atoms[0].z

        atoms.forEach((atom) => {
          minX = Math.min(minX, atom.x)
          maxX = Math.max(maxX, atom.x)
          minY = Math.min(minY, atom.y)
          maxY = Math.max(maxY, atom.y)
          minZ = Math.min(minZ, atom.z)
          maxZ = Math.max(maxZ, atom.z)
        })

        maxDim = Math.max(maxX - minX, maxY - minY, maxZ - minZ)
      }

      if (!Number.isFinite(maxDim) || maxDim <= 0) {
        maxDim = 10
      }

      const halfX = boxSize?.[0] ? Number(boxSize[0]) * 0.5 : maxDim * 0.5
      const halfY = boxSize?.[1] ? Number(boxSize[1]) * 0.5 : maxDim * 0.5
      const halfZ = boxSize?.[2] ? Number(boxSize[2]) * 0.5 : maxDim * 0.5
      const sceneRadius = Math.max(
        Math.sqrt(halfX * halfX + halfY * halfY + halfZ * halfZ),
        maxDim * 0.5,
        2
      )

      const isSpacefill = representation === 'spacefill'
      const isWireframe = representation === 'wireframe'
      const atomRadius = isSpacefill ? 0.62 : 0.38
      const sphereGeometry = new THREE.SphereGeometry(atomRadius, 16, 12)
      const atomsByElement = new Map()
      atoms.forEach((atom, index) => {
        const element = normalizeElementSymbol(atom.element)
        if (!atomsByElement.has(element)) atomsByElement.set(element, [])
        atomsByElement.get(element).push(index)
      })

      const atomDummy = new THREE.Object3D()
      atomsByElement.forEach((indices, element) => {
        const color = ELEMENT_COLORS[element] || ELEMENT_COLORS.X
        const material = isWireframe
          ? new THREE.MeshPhongMaterial({ color, wireframe: true, transparent: true, opacity: 0.92 })
          : new THREE.MeshPhongMaterial({ color })
        const instancedAtoms = new THREE.InstancedMesh(
          sphereGeometry,
          material,
          indices.length
        )

        indices.forEach((atomIndex, instanceIndex) => {
          const atom = atoms[atomIndex]
          atomDummy.position.set(
            atom.x - centerX,
            atom.y - centerY,
            atom.z - centerZ
          )
          atomDummy.updateMatrix()
          instancedAtoms.setMatrixAt(instanceIndex, atomDummy.matrix)
        })

        instancedAtoms.instanceMatrix.needsUpdate = true
        scene.add(instancedAtoms)
      })

      // Render bonds as two half-cylinders (atom-colored) for better 3D visibility.
      const shouldRenderBonds = !isSpacefill && !isWireframe
      if (shouldRenderBonds && bonds && bonds.length > 0) {
        const hasBox = Array.isArray(boxSize) && boxSize.length === 3
        const [lx, ly, lz] = hasBox ? boxSize : [0, 0, 0]
        const halfBondMatricesByColor = new Map()
        const up = new THREE.Vector3(0, 0, 1)
        const dir = new THREE.Vector3()
        const halfVec = new THREE.Vector3()
        const quat = new THREE.Quaternion()
        const dummy = new THREE.Object3D()
        const pushHalfBond = (from, to, colorHex) => {
          const fx = from.x
          const fy = from.y
          const fz = from.z
          const tx = to.x
          const ty = to.y
          const tz = to.z
          const dxHalf = tx - fx
          const dyHalf = ty - fy
          const dzHalf = tz - fz
          const segLength = Math.sqrt(dxHalf * dxHalf + dyHalf * dyHalf + dzHalf * dzHalf)
          if (segLength <= 1e-6) return

          const mx = (fx + tx) * 0.5
          const my = (fy + ty) * 0.5
          const mz = (fz + tz) * 0.5
          dir.set(dxHalf, dyHalf, dzHalf).normalize()
          quat.setFromUnitVectors(up, dir)

          dummy.position.set(mx, my, mz)
          dummy.quaternion.copy(quat)
          dummy.scale.set(1, 1, segLength)
          dummy.updateMatrix()

          if (!halfBondMatricesByColor.has(colorHex)) {
            halfBondMatricesByColor.set(colorHex, [])
          }
          halfBondMatricesByColor.get(colorHex).push(dummy.matrix.clone())
        }

        bonds.forEach(([i, j]) => {
          if (i >= atoms.length || j >= atoms.length) return

          const atom1 = atoms[i]
          const atom2 = atoms[j]

          let dx = atom2.x - atom1.x
          let dy = atom2.y - atom1.y
          let dz = atom2.z - atom1.z

          // Apply minimum-image convention to keep PBC-crossing bonds visible.
          if (hasBox) {
            if (lx > 0) dx -= Math.round(dx / lx) * lx
            if (ly > 0) dy -= Math.round(dy / ly) * ly
            if (lz > 0) dz -= Math.round(dz / lz) * lz
          }

          const bondLength = Math.sqrt(dx * dx + dy * dy + dz * dz)

          // Skip very long bonds (likely PBC artifacts)
          if (bondLength > 5) return

          const ax = atom1.x - centerX
          const ay = atom1.y - centerY
          const az = atom1.z - centerZ
          const bx = atom1.x + dx - centerX
          const by = atom1.y + dy - centerY
          const bz = atom1.z + dz - centerZ
          const mx = (ax + bx) * 0.5
          const my = (ay + by) * 0.5
          const mz = (az + bz) * 0.5

          const colorA = getElementColorHex(atom1.element)
          const colorB = getElementColorHex(atom2.element)
          halfVec.set(mx, my, mz)
          pushHalfBond({ x: ax, y: ay, z: az }, { x: halfVec.x, y: halfVec.y, z: halfVec.z }, colorA)
          pushHalfBond({ x: halfVec.x, y: halfVec.y, z: halfVec.z }, { x: bx, y: by, z: bz }, colorB)
        })

        const bondGeometry = new THREE.CylinderGeometry(0.115, 0.115, 1, 10)
        bondGeometry.rotateX(Math.PI / 2)

        halfBondMatricesByColor.forEach((matrices, colorHex) => {
          if (!matrices.length) return
          const bondMaterial = new THREE.MeshPhongMaterial({
            color: colorHex,
            transparent: true,
            opacity: 0.9,
            shininess: 45,
          })
          const mesh = new THREE.InstancedMesh(bondGeometry, bondMaterial, matrices.length)
          matrices.forEach((matrix, idx) => {
            mesh.setMatrixAt(idx, matrix)
          })
          mesh.instanceMatrix.needsUpdate = true
          scene.add(mesh)
        })
      }

      // Add box wireframe
      if (boxSize) {
        const [lx, ly, lz] = boxSize
        const boxGeometry = new THREE.BoxGeometry(lx, ly, lz)
        const boxMaterial = new THREE.LineBasicMaterial({ color: 0x4a5568, opacity: 0.5, transparent: true })
        const boxEdges = new THREE.EdgesGeometry(boxGeometry)
        const boxWireframe = new THREE.LineSegments(boxEdges, boxMaterial)
        scene.add(boxWireframe)
      }

      if (showAxes) {
        const axisLength = Math.max(maxDim * 0.25, 6)
        const axes = new THREE.AxesHelper(axisLength)
        scene.add(axes)
      }

      // Position camera
      let cameraDistance = Math.max(maxDim * 2.2, 8)
      if (fitToFrame) {
        const aspect = Math.max(width / Math.max(height, 1), 1e-3)
        const fovRad = (camera.fov * Math.PI) / 180
        const fitHeightDistance = sceneRadius / Math.tan(fovRad / 2)
        const fitWidthDistance = fitHeightDistance / aspect
        cameraDistance = Math.max(fitHeightDistance, fitWidthDistance, sceneRadius * 1.25) * fitPadding
      }
      if (zUp) {
        camera.position.set(cameraDistance * 0.8, -cameraDistance * 1.05, cameraDistance * 0.95)
      } else {
        camera.position.set(cameraDistance, cameraDistance * 0.6, cameraDistance)
      }
      camera.lookAt(0, 0, 0)
      controls.target.set(0, 0, 0)
      controls.minDistance = Math.max(sceneRadius * 0.35, 2)
      controls.maxDistance = Math.max(sceneRadius * 10, 60)

      // Guard once more: setup took several microtasks, the component may
      // have been superseded or unmounted in the meantime.
      if (disposed || gen !== genRef.current) {
        try { renderer.dispose() } catch { /* ignore */ }
        return
      }

      // Animation loop
      const animate = () => {
        animationRef.current = requestAnimationFrame(animate)
        controls.update()
        renderer.render(scene, camera)
      }
      animate()

      setIsLoaded(true)
      onLoad?.()

      // Handle resize — stored in outer scope so the useEffect cleanup can
      // remove it even if this function's own closure is not used.
      const handleResize = () => {
        const width = container.clientWidth
        const height = container.clientHeight
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        renderer.setSize(width, height)
      }
      window.addEventListener('resize', handleResize)
      resizeHandler = handleResize
    }).catch((err) => {
      if (disposed || gen !== genRef.current) return
      console.error('[SimpleViewer] init failed:', err)
      setInitError(err?.message || 'Failed to initialize viewer')
    })

    return () => {
      disposed = true
      if (resizeHandler) window.removeEventListener('resize', resizeHandler)
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
        animationRef.current = null
      }
      if (rendererRef.current) {
        try {
          if (
            rendererRef.current.domElement.parentNode === container
          ) {
            container.removeChild(rendererRef.current.domElement)
          }
        } catch { /* container may be detached */ }
        try { rendererRef.current.dispose() } catch { /* ignore */ }
        rendererRef.current = null
      }
      if (controlsRef.current) {
        try { controlsRef.current.dispose?.() } catch { /* ignore */ }
        controlsRef.current = null
      }
    }
  }, [xyzData, boxSize, bonds, onLoad, showAxes, zUp, fitToFrame, fitPadding, representation])

  return (
    <div ref={containerRef} className="relative w-full h-full min-h-[300px]">
      {!isLoaded && !initError && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-800">
          <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
        </div>
      )}
      {initError && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-800 p-4 text-center text-xs text-red-300">
          Viewer init failed: {initError}
        </div>
      )}
      {showAxes && (
        <div className="absolute right-2 bottom-2 rounded bg-slate-900/70 border border-slate-600 px-2 py-1 text-[11px] text-slate-200">
          <span className="text-red-300">X</span> / <span className="text-emerald-300">Y</span> /{' '}
          <span className="text-blue-300">Z</span>
        </div>
      )}
    </div>
  )
}
