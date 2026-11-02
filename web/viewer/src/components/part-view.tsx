// A 3D part: the mesh /api/mesh serves, in three.js. Drag turns it (damped, so it keeps gliding a little), right-drag
// moves it, the wheel zooms toward the pointer, a double-click frames it again. The scene lives as long as the view:
// switching parts or versions swaps the mesh and glides the camera to the new framing, nothing flashes.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import * as THREE from "three"
import { OrbitControls } from "three/addons/controls/OrbitControls.js"
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js"

export interface Mesh { positions: number[]; indices: number[]; edges: number[][] }
export interface ViewHandle { zoomIn(): void; zoomOut(): void; fit(): void; canvas(): HTMLCanvasElement | null }

interface Scene {
  show(m: Mesh): void
  fit(animate: boolean): void
  dolly(f: number): void
  canvas(): HTMLCanvasElement
  dispose(): void
}

const ease = (t: number) => 1 - Math.pow(1 - t, 3)

function makeScene(el: HTMLDivElement, onZoom: (pct: number) => void): Scene {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })  // kept for "Save picture"
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.domElement.style.cssText = "width:100%;height:100%;display:block;touch-action:none"
  el.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e6)
  camera.up.set(0, 0, 1)
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8890a0, 1.6))
  const sun = new THREE.DirectionalLight(0xffffff, 1.6)
  scene.add(sun)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.rotateSpeed = 0.9
  controls.zoomToCursor = true
  const group = new THREE.Group()
  scene.add(group)

  let framed = 0, fitDist = 1, moved = false, tween: null | { t0: number; from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3] } = null
  controls.addEventListener("start", () => { moved = true; tween = null })
  controls.addEventListener("change", () => onZoom(Math.round(fitDist / camera.position.distanceTo(controls.target) * 100)))

  const size = () => {
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return
    renderer.setSize(r.width, r.height, false)
    camera.aspect = r.width / r.height
    camera.updateProjectionMatrix()
    if (framed && !moved) fit(false)  // a resized view is re-framed until the user moves the camera themselves
  }
  const ro = new ResizeObserver(size)
  ro.observe(el)

  let raf = 0
  const loop = (now: number) => {
    raf = requestAnimationFrame(loop)
    if (tween) {
      const k = ease(Math.min(1, (now - tween.t0) / 450))
      camera.position.lerpVectors(tween.from[0], tween.to[0], k)
      controls.target.lerpVectors(tween.from[1], tween.to[1], k)
      if (k >= 1) tween = null
    }
    controls.update()
    sun.position.copy(camera.position)
    renderer.render(scene, camera)
  }
  raf = requestAnimationFrame(loop)

  function fit(animate: boolean) {
    const box = new THREE.Box3().setFromObject(group)
    if (box.isEmpty()) return
    const c = box.getCenter(new THREE.Vector3()), r = box.getSize(new THREE.Vector3()).length() || 1
    // the bounding sphere (radius r/2) fits the narrower of the two fields of view, with a 25 % margin
    const half = Math.PI / 360 * camera.fov, hHalf = Math.atan(Math.tan(half) * camera.aspect)
    fitDist = (r / 2) / Math.sin(Math.min(half, hHalf)) * 1.25
    const dir = moved || framed ? camera.position.clone().sub(controls.target).normalize() : new THREE.Vector3(1, -1.3, 0.9).normalize()
    const pos = c.clone().add(dir.multiplyScalar(fitDist))
    camera.near = r / 100; camera.far = r * 100; camera.updateProjectionMatrix()
    if (animate && framed) tween = { t0: performance.now(), from: [camera.position.clone(), controls.target.clone()], to: [pos, c] }
    else { camera.position.copy(pos); controls.target.copy(c) }
    framed = r; moved = false
    onZoom(100)
  }

  function show(m: Mesh) {
    const old = [...group.children]
    let g = new THREE.BufferGeometry()
    g.setAttribute("position", new THREE.Float32BufferAttribute(m.positions, 3))
    g.setIndex(m.indices)
    g = toCreasedNormals(g, Math.PI / 6)
    const next = new THREE.Group()
    next.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x9fb8d8, metalness: 0.1, roughness: 0.55,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })))
    const seg: number[] = []
    for (const e of m.edges) for (let i = 0; i + 5 < e.length; i += 3) seg.push(e[i], e[i + 1], e[i + 2], e[i + 3], e[i + 4], e[i + 5])
    const lg = new THREE.BufferGeometry()
    lg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3))
    next.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0x1d2330 })))
    group.add(...next.children)
    for (const o of old) {
      group.remove(o)
      o.traverse((x) => { const y = x as THREE.Mesh; y.geometry?.dispose(); (y.material as THREE.Material | undefined)?.dispose?.() })
    }
    // keep the user's camera across versions of a part unless it grew or shrank a lot
    const r = new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3()).length() || 1
    if (!framed || r > framed * 1.2 || r < framed / 1.2) fit(true)
  }

  renderer.domElement.addEventListener("dblclick", () => fit(true))
  size()
  return {
    show, fit,
    dolly(f) {  // zoom about the middle of the view
      const d = camera.position.clone().sub(controls.target)
      tween = { t0: performance.now(), from: [camera.position.clone(), controls.target.clone()],
                to: [controls.target.clone().add(d.multiplyScalar(f)), controls.target.clone()] }
      setTimeout(() => onZoom(Math.round(fitDist / camera.position.distanceTo(controls.target) * 100)), 480)
    },
    canvas() { renderer.render(scene, camera); return renderer.domElement },
    dispose() { cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose(); el.innerHTML = "" },
  }
}

// without WebGL (an old graphics driver, a locked-down browser) it shows the shaded picture /api/png renders instead
export const PartView = forwardRef<ViewHandle, { mesh: Mesh | null; picture: string; onZoom(pct: number): void; className?: string }>(
  function PartView({ mesh, picture, onZoom, className }, ref) {
    const [noGL, setNoGL] = useState(false)
    const el = useRef<HTMLDivElement>(null)
    const scene = useRef<Scene | null>(null)
    const zoomCb = useRef(onZoom)
    zoomCb.current = onZoom
    useEffect(() => {
      try { scene.current = makeScene(el.current!, (p) => zoomCb.current(p)) } catch { setNoGL(true) }
      return () => { scene.current?.dispose(); scene.current = null }
    }, [])
    useEffect(() => { if (mesh) scene.current?.show(mesh) }, [mesh])
    useImperativeHandle(ref, () => ({
      zoomIn: () => scene.current?.dolly(1 / 1.4),
      zoomOut: () => scene.current?.dolly(1.4),
      fit: () => scene.current?.fit(true),
      canvas: () => scene.current?.canvas() ?? null,
    }), [])
    if (noGL) return <img alt="" src={picture} className={className + " object-contain p-6"} />
    return <div ref={el} className={className} />
  },
)
