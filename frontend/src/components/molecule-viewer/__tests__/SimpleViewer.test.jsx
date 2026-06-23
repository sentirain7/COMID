/**
 * v00.99.71 — SimpleViewer lifecycle regression.
 *
 * The prior implementation placed the cleanup inside a `.then()` callback,
 * which means React never saw it. After this fix the useEffect body returns
 * the cleanup directly, so:
 *   - resize listeners don't leak across xyzData changes.
 *   - `isLoaded` resets so the outer loader is visible during re-init.
 *   - stale async setup paths (superseded by a newer dep change) do not
 *     overwrite the current renderer or touch the DOM post-unmount.
 */
import { render, act } from '@testing-library/react'
import { vi } from 'vitest'
import { SimpleViewer } from '../SimpleViewer'

// three and OrbitControls are heavy; stub them with just enough surface for
// the effect to complete a frame.
const rendererInstances = []
vi.mock('three', () => {
  class Vector3 { constructor() {} set() { return this } normalize() { return this } }
  class Quaternion { setFromUnitVectors() { return this } copy() { return this } }
  class Object3D {
    constructor() { this.position = new Vector3(); this.quaternion = new Quaternion(); this.scale = new Vector3(); this.matrix = {} }
    updateMatrix() {}
  }
  class Color {}
  class Scene { constructor() {} add() {} }
  class PerspectiveCamera {
    constructor() { this.up = new Vector3(); this.position = new Vector3(); this.aspect = 1; this.fov = 75 }
    lookAt() {}
    updateProjectionMatrix() {}
  }
  class WebGLRenderer {
    constructor() {
      this.domElement = document.createElement('canvas')
      this.disposeCalls = 0
      rendererInstances.push(this)
    }
    setSize() {}
    setPixelRatio() {}
    render() {}
    dispose() { this.disposeCalls++ }
  }
  class InstancedMesh { constructor() { this.instanceMatrix = { needsUpdate: false } } setMatrixAt() {} }
  class BufferGeometry {}
  class SphereGeometry extends BufferGeometry {}
  class CylinderGeometry extends BufferGeometry { rotateX() {} }
  class BoxGeometry extends BufferGeometry {}
  class EdgesGeometry extends BufferGeometry { constructor() { super() } }
  class LineBasicMaterial {}
  class LineSegments {}
  class AmbientLight {}
  class DirectionalLight { constructor() { this.position = new Vector3() } }
  class AxesHelper {}
  class MeshPhongMaterial {}
  return {
    default: {},
    Vector3, Quaternion, Object3D, Color, Scene, PerspectiveCamera,
    WebGLRenderer, InstancedMesh, BufferGeometry, SphereGeometry,
    CylinderGeometry, BoxGeometry, EdgesGeometry, LineBasicMaterial,
    LineSegments, AmbientLight, DirectionalLight, AxesHelper,
    MeshPhongMaterial,
  }
})

vi.mock('three/addons/controls/OrbitControls.js', () => {
  class OrbitControls {
    constructor() {
      this.enableDamping = false
      this.dampingFactor = 0
      this.target = { set: () => {} }
      this.minDistance = 0
      this.maxDistance = 0
    }
    update() {}
    dispose() {}
  }
  return { OrbitControls }
})

const sampleXyz = '1\nframe\nC 0.0 0.0 0.0\n'

function waitForSetup() {
  // Three microtask turns cover: import('three') → .then → import controls → .then → inner setup.
  return act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve()
  })
}

describe('SimpleViewer lifecycle', () => {
  beforeEach(() => {
    rendererInstances.length = 0
  })

  it('removes resize listener on unmount', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { unmount } = render(<SimpleViewer xyzData={sampleXyz} />)
    await waitForSetup()

    const addedResize = addSpy.mock.calls.filter((c) => c[0] === 'resize').length
    expect(addedResize).toBeGreaterThanOrEqual(1)

    unmount()
    const removedResize = removeSpy.mock.calls.filter((c) => c[0] === 'resize').length
    expect(removedResize).toBeGreaterThanOrEqual(addedResize)
  })

  it('disposes the renderer on unmount', async () => {
    const { unmount } = render(<SimpleViewer xyzData={sampleXyz} />)
    await waitForSetup()
    expect(rendererInstances.length).toBe(1)
    unmount()
    expect(rendererInstances[0].disposeCalls).toBeGreaterThanOrEqual(1)
  })

  it('does not leak listeners across xyzData changes', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { rerender, unmount } = render(<SimpleViewer xyzData={sampleXyz} />)
    await waitForSetup()
    const afterFirst = addSpy.mock.calls.filter((c) => c[0] === 'resize').length

    rerender(<SimpleViewer xyzData={'2\nframe\nC 0 0 0\nO 1 0 0\n'} />)
    await waitForSetup()
    rerender(<SimpleViewer xyzData={'1\nframe\nH 2 0 0\n'} />)
    await waitForSetup()

    unmount()
    const totalAdd = addSpy.mock.calls.filter((c) => c[0] === 'resize').length
    const totalRemove = removeSpy.mock.calls.filter((c) => c[0] === 'resize').length
    // Every add must be matched by a remove by the time the component is gone.
    expect(totalRemove).toBeGreaterThanOrEqual(totalAdd)
    expect(totalAdd).toBeGreaterThan(afterFirst)
  })
})
