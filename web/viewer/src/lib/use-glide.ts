// One highlight that glides to the row under the pointer, as the old viewer's lists did (Fluid Functionalism's
// fluidHover): the list gets a ref, its rows data-glide, and the returned style goes on an absolute <span>.
import { useEffect, useRef, useState } from "react"

export function useGlide<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [box, setBox] = useState<{ y: number; h: number; on: boolean; jump: boolean }>({ y: 0, h: 0, on: false, jump: true })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const over = (e: PointerEvent) => {
      const row = (e.target as HTMLElement).closest<HTMLElement>("[data-glide]")
      if (!row || !el.contains(row)) return
      setBox((b) => ({ y: row.offsetTop, h: row.offsetHeight, on: true, jump: !b.on }))
    }
    const leave = () => setBox((b) => ({ ...b, on: false }))
    el.addEventListener("pointerover", over)
    el.addEventListener("pointerleave", leave)
    return () => { el.removeEventListener("pointerover", over); el.removeEventListener("pointerleave", leave) }
  }, [])
  const style: React.CSSProperties = {
    transform: `translateY(${box.y}px)`, height: box.h, opacity: box.on ? 1 : 0,
    transition: box.jump ? "opacity 80ms ease-out" : "transform 160ms cubic-bezier(.2,.8,.2,1), height 160ms cubic-bezier(.2,.8,.2,1), opacity 80ms ease-out",
  }
  return { ref, style }
}
