// A 2D drawing: the SVG /api/svg renders, in AutoCAD's model space. The wheel zooms at the cursor, a drag (or the
// middle button) pans, a double-click or a double middle-click shows it all. Another version of the same drawing
// keeps the view; the zoom buttons and "see it all" glide instead of jumping.
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react"
import type { ViewHandle } from "@/components/part-view"

type Box = [number, number, number, number]
const ease = (t: number) => 1 - Math.pow(1 - t, 3)

export const DrawingView = forwardRef<ViewHandle, { svg: string | null; file: string; onZoom(pct: number): void; className?: string }>(
  function DrawingView({ svg, file, onZoom, className }, ref) {
    const host = useRef<HTMLDivElement>(null)
    const st = useRef<{ el: SVGSVGElement | null; base: Box | null; baseKey: string; view: Box | null; anim: number; file: string }>(
      { el: null, base: null, baseKey: "", view: null, anim: 0, file: "" })
    const zoomCb = useRef(onZoom)
    zoomCb.current = onZoom

    const apply = () => {
      const s = st.current
      if (!s.el || !s.view) return
      s.el.setAttribute("viewBox", s.view.join(" "))
      if (s.base) zoomCb.current(Math.round(s.base[2] / s.view[2] * 100))
    }
    const glide = (to: Box) => {
      const s = st.current
      cancelAnimationFrame(s.anim)
      const from = s.view ? [...s.view] as Box : to, t0 = performance.now()
      const step = (now: number) => {
        const k = ease(Math.min(1, (now - t0) / 220))
        s.view = from.map((v, i) => v + (to[i] - v) * k) as Box
        apply()
        if (k < 1) s.anim = requestAnimationFrame(step)
      }
      s.anim = requestAnimationFrame(step)
    }
    const fit = () => { if (st.current.base) glide([...st.current.base] as Box) }
    const zoomBy = (f: number) => {  // about the middle of what is shown
      const v = st.current.view
      if (!v) return
      const [x, y, w, h] = v, cx = x + w / 2, cy = y + h / 2
      glide([cx - w * f / 2, cy - h * f / 2, w * f, h * f])
    }

    useImperativeHandle(ref, () => ({ zoomIn: () => zoomBy(1 / 1.5), zoomOut: () => zoomBy(1.5), fit, canvas: () => null }), [])

    useEffect(() => {
      const s = st.current, box = host.current!
      if (!svg) return
      const doc = new DOMParser().parseFromString(svg, "image/svg+xml")
      const el = doc.documentElement as unknown as SVGSVGElement
      el.querySelectorAll("script, foreignObject").forEach((n) => n.remove())
      const sheet = el.querySelector(":scope > rect")  // the render's white paper: the lines sit on the dotted canvas
      if (sheet && sheet.getAttribute("x") === "0" && sheet.getAttribute("y") === "0") sheet.remove()
      el.removeAttribute("width"); el.removeAttribute("height")
      el.setAttribute("preserveAspectRatio", "xMidYMid meet")
      el.setAttribute("class", "drawing-svg")
      const key = el.getAttribute("viewBox") || "0 0 100 100"
      const other = file !== s.file  // another drawing: framed afresh, and it fades in
      if (other || key !== s.baseKey || !s.view) { s.baseKey = key; s.base = key.split(/\s+/).map(Number) as Box; s.view = [...s.base] as Box }
      if (other) el.setAttribute("class", "drawing-svg enter")
      s.file = file
      const node = document.importNode(el, true) as SVGSVGElement
      box.replaceChildren(node)
      s.el = node
      apply()

      // pan and zoom (AutoCAD's mouse)
      const pt = (e: { clientX: number; clientY: number }) => {
        const r = node.getBoundingClientRect(), v = s.view!
        const k = Math.max(v[2] / r.width, v[3] / r.height)
        const ox = (r.width * k - v[2]) / 2, oy = (r.height * k - v[3]) / 2
        return [v[0] - ox + (e.clientX - r.left) * k, v[1] - oy + (e.clientY - r.top) * k, k]
      }
      const wheel = (e: WheelEvent) => {
        e.preventDefault(); cancelAnimationFrame(s.anim)
        const [x, y] = pt(e), f = Math.exp(e.deltaY * 0.0015), v = s.view!
        s.view = [x - (x - v[0]) * f, y - (y - v[1]) * f, v[2] * f, v[3] * f]; apply()
      }
      let drag: number[] | null = null, midDown = 0
      const down = (e: PointerEvent) => {
        if (e.button === 1) {
          e.preventDefault()
          if (performance.now() - midDown < 400) { midDown = 0; fit(); return }
          midDown = performance.now()
        }
        cancelAnimationFrame(s.anim)
        drag = [e.clientX, e.clientY, ...s.view!]; node.setPointerCapture(e.pointerId); node.classList.add("drag")
      }
      const move = (e: PointerEvent) => {
        if (!drag) return
        const k = pt(e)[2]
        s.view = [drag[2] - (e.clientX - drag[0]) * k, drag[3] - (e.clientY - drag[1]) * k, drag[4], drag[5]]; apply()
      }
      const up = () => { drag = null; node.classList.remove("drag") }
      const aux = (e: MouseEvent) => e.preventDefault()
      node.addEventListener("wheel", wheel, { passive: false })
      node.addEventListener("pointerdown", down)
      node.addEventListener("pointermove", move)
      node.addEventListener("pointerup", up)
      node.addEventListener("auxclick", aux)
      node.addEventListener("dblclick", fit)
      return () => { cancelAnimationFrame(s.anim) }
    }, [svg, file])

    return <div ref={host} className={className} />
  },
)
