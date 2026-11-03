// The canvas: the open drawing (2D) or part (3D), before/after, the zoom bar, hints and notes. Both views stay mounted
// and cross-fade, and the previous file stays on screen (dimmed) until the next one is ready, so switching never flashes.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react"
import { ChevronsLeftRight, Loader2, Maximize2, MousePointer2, Move, Rotate3d, RotateCcw, ScanSearch, ZoomIn, ZoomOut } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { DrawingView } from "@/components/drawing-view"
import { PartView, type Mesh, type ViewHandle } from "@/components/part-view"
import { api, base, cannotShow, F, isPart, type ApiError, type Lang, type Timeline } from "@/lib/agentcad"
import { cn } from "@/lib/utils"

export interface StageHandle { picture(): Promise<HTMLCanvasElement> }

interface Props {
  path: string | null
  version: string | null
  tl: Timeline | null
  highlight: boolean
  hidden: string[]
  compare: boolean
  lang: Lang
  reload: number            // bumps when the open file changed on disk
  onBackToNow(): void
  children?: React.ReactNode  // overlays (the celebration)
}

const HINTS: Record<"zoomHint" | "orbitHint", LucideIcon[]> = { zoomHint: [MousePointer2, Move, ScanSearch], orbitHint: [Rotate3d, Move, MousePointer2] }

function Tool({ label, icon: Icon, onClick }: { label: string; icon: LucideIcon; onClick(): void }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={label} onClick={onClick}><Icon /></Button></TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

export const Stage = forwardRef<StageHandle, Props>(function Stage(
  { path, version, tl, highlight, hidden, compare, lang, reload, onBackToNow, children }, ref,
) {
  const t = (k: string, v?: Record<string, unknown>) => F().t(k, v, lang)
  const [svg, setSvg] = useState<string | null>(null)
  const [mesh, setMesh] = useState<Mesh | null>(null)
  const [shown, setShown] = useState<{ kind: "2d" | "3d"; file: string } | null>(null)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")
  const [zoom, setZoom] = useState(100)
  const [cut, setCut] = useState(50)
  const [wantPart, setWantPart] = useState(false)  // the 3D view (WebGL) starts the first time a part is opened
  const seq = useRef(0)
  const view2d = useRef<ViewHandle>(null), view3d = useRef<ViewHandle>(null)
  const box = useRef<HTMLDivElement>(null)
  const part = isPart(path)
  const hideKey = hidden.join(",")

  useEffect(() => {
    if (!path || compare) return
    const n = ++seq.current, v = version || "current"
    setError("")
    if (part) {
      setWantPart(true)
      if (shown?.file !== path) setBusy(t("meshing"))
      api<Mesh>("/api/mesh", { path, v })
        .then((m) => { if (n === seq.current) { setMesh(m); setShown({ kind: "3d", file: path }); setBusy("") } })
        .catch((e: ApiError) => { if (n === seq.current) { setBusy(""); setError(cannotShow(e, lang)) } })
    } else {
      if (shown?.file !== path) setBusy(t("loading"))
      api<string>("/api/svg", { path, v, diff: highlight ? 1 : 0, hide: hideKey })
        .then((s) => { if (n === seq.current) { setSvg(s); setShown({ kind: "2d", file: path }); setBusy("") } })
        .catch((e: ApiError) => { if (n === seq.current) { setBusy(""); setError(cannotShow(e, lang)) } })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version, highlight, hideKey, compare, reload])

  useImperativeHandle(ref, () => ({
    async picture() {  // what is on screen, on white, with a footer: the file's name, the date, "Made with AgentCAD"
      let src: CanvasImageSource, w: number, h: number
      if (part) {
        const c = view3d.current?.canvas()
        if (!c) throw new Error("render")
        src = c; w = c.width; h = c.height
      } else {
        const text = await api<string>("/api/svg", { path: path!, v: version || "current", diff: highlight ? 1 : 0, hide: hideKey })
        const [, , vw, vh] = ((/viewBox="([^"]+)"/.exec(text) || [])[1] || "0 0 1600 1000").split(/\s+/).map(Number)
        w = 2000; h = Math.round(2000 * vh / vw)
        if (h > 2400) { h = 2400; w = Math.round(2400 * vw / vh) }
        const img = new Image(w, h), url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }))
        await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("render")); img.src = url })
        URL.revokeObjectURL(url)
        src = img
      }
      const pad = 32, foot = 72, c = document.createElement("canvas")
      c.width = w + pad * 2; c.height = h + pad * 2 + foot
      const g = c.getContext("2d")!
      g.fillStyle = "#ffffff"; g.fillRect(0, 0, c.width, c.height)
      g.drawImage(src, pad, pad, w, h)
      g.fillStyle = "#f1f4f8"; g.fillRect(0, c.height - foot, c.width, foot)
      const font = "system-ui, 'Segoe UI', 'Microsoft YaHei UI', sans-serif"
      g.fillStyle = "#111827"; g.font = `600 26px ${font}`; g.textBaseline = "middle"
      g.fillText(base(path), pad, c.height - foot / 2)
      g.fillStyle = "#5b6474"; g.font = `22px ${font}`; g.textAlign = "right"
      g.fillText(`${new Date().toLocaleDateString(lang === "zh" ? "zh-CN" : undefined)} · ${t("madeWith")}`, c.width - pad, c.height - foot / 2)
      return c
    },
  }))

  const active = shown?.kind === "3d" ? view3d : view2d
  const switching = !!path && shown?.file !== path
  const hint = part ? "orbitHint" : "zoomHint"

  return (
    <div ref={box} className="@container relative min-h-[320px] flex-1 overflow-hidden rounded-lg border bg-canvas select-none max-md:h-[56vh] max-md:flex-none"
         style={{ backgroundImage: "radial-gradient(var(--canvas-dot) 1px, transparent 1.2px)", backgroundSize: "16px 16px" }}>
      {/* the two views, cross-fading */}
      <div className={cn("absolute inset-0 transition-opacity duration-200", shown?.kind === "2d" && !compare ? (switching ? "opacity-40" : "opacity-100") : "pointer-events-none opacity-0")}>
        <DrawingView ref={view2d} svg={svg} file={shown?.kind === "2d" ? shown.file : ""} onZoom={(p) => shown?.kind === "2d" && setZoom(p)} className="size-full" />
      </div>
      {wantPart && (
        <div className={cn("absolute inset-0 transition-opacity duration-200", shown?.kind === "3d" && !compare ? (switching ? "opacity-40" : "opacity-100") : "pointer-events-none opacity-0")}>
          <PartView ref={view3d} mesh={mesh} picture={path && part ? "/api/png?" + new URLSearchParams({ path, v: version || "current" }) : ""} onZoom={(p) => shown?.kind === "3d" && setZoom(p)} className="size-full" />
        </div>
      )}

      {compare && path && tl && <Compare path={path} version={version} tl={tl} highlight={highlight} cut={cut} setCut={setCut} lang={lang} />}

      {/* notes on top */}
      {version && !compare && (
        <div className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-2 rounded-full bg-warning/15 py-1 pr-1 pl-3.5 text-sm font-medium text-warning shadow-sm ring-1 ring-warning/30 backdrop-blur">
          {t("earlier")}
          <Button size="xs" className="rounded-full bg-warning text-white hover:bg-warning/90" onClick={onBackToNow}>{t("backToNow")}</Button>
        </div>
      )}
      {highlight && !part && !compare && shown?.kind === "2d" && (
        <div className="absolute top-3 left-3 z-10 flex gap-3 rounded-md bg-popover/90 px-2.5 py-1 text-xs shadow-sm ring-1 ring-foreground/10 backdrop-blur">
          {[["#16a34a", "legendAdded"], ["#ea580c", "legendModified"], ["#b8bcc4", "legendOther"]].map(([c, k]) => (
            <span key={k} className="flex items-center gap-1.5"><i className="h-[3px] w-3 rounded-full" style={{ background: c }} />{t(k)}</span>
          ))}
        </div>
      )}
      {(busy || error) && (
        <div className="absolute top-1/2 left-1/2 z-10 flex max-w-[min(460px,calc(100%-32px))] -translate-x-1/2 -translate-y-1/2 items-center gap-2.5 rounded-lg bg-popover px-4 py-2.5 text-sm shadow-md ring-1 ring-foreground/10">
          {busy && <Loader2 className="size-4 shrink-0 animate-spin text-primary" />}
          <span className={cn(error && "text-muted-foreground")}>{busy || error}</span>
        </div>
      )}

      {/* hints and the zoom bar */}
      {path && !compare && (
        <>
          <div className="pointer-events-none absolute bottom-4 left-4 flex gap-4 text-xs text-muted-foreground @max-[600px]:hidden">
            {t(hint).split(" · ").map((x, i) => {
              const Icon = HINTS[hint][i] || MousePointer2
              return <span key={x} className="flex items-center gap-1.5"><Icon className="size-3.5" />{x}</span>
            })}
          </div>
          <div className="absolute right-3 bottom-3 z-10 flex items-center gap-0.5 rounded-lg bg-popover/95 p-1 shadow-md ring-1 ring-foreground/10 backdrop-blur">
            <Tool label={t("zoomIn")} icon={ZoomIn} onClick={() => active.current?.zoomIn()} />
            <Tool label={t("zoomOut")} icon={ZoomOut} onClick={() => active.current?.zoomOut()} />
            <Tool label={t("zoomAll")} icon={RotateCcw} onClick={() => active.current?.fit()} />
            <Tool label={t("fullscreen")} icon={Maximize2} onClick={() => (document.fullscreenElement ? document.exitFullscreen() : box.current?.requestFullscreen())} />
            <Separator orientation="vertical" className="mx-1 h-4!" />
            <span className="w-12 text-center font-mono text-xs text-muted-foreground tabular-nums">{zoom}%</span>
          </div>
        </>
      )}
      {children}
    </div>
  )
})

// before / after: for a drawing a slider over the two renders (the "after" one coloured by what changed), for a
// part the two pictures side by side
function Compare({ path, version, tl, highlight, cut, setCut, lang }:
  { path: string; version: string | null; tl: Timeline; highlight: boolean; cut: number; setCut(n: number): void; lang: Lang }) {
  const t = (k: string) => F().t(k, {}, lang)
  const after = version || tl.current
  const rec = [...tl.records].reverse().find((r) => r.version === after)
  const before = rec?.before
  const stored = new Set(tl.records.filter((r) => r.available).map((r) => r.version))
  if (!before || !stored.has(before)) {
    return <div className="absolute inset-0 grid place-items-center p-6 text-center text-muted-foreground">{t("noBefore")}</div>
  }
  const src = (sha: string, other: string) => isPart(path) ? "/api/thumb?" + new URLSearchParams({ path, v: sha })
    : "/api/svg?" + new URLSearchParams({ path, v: sha, frame: other, diff: highlight && sha === after ? "1" : "0" })
  const label = "absolute top-3 z-10 rounded-full px-2.5 py-0.5 text-xs font-medium"
  if (isPart(path)) {
    return (
      <div className="absolute inset-0 grid grid-cols-2">
        <div className="relative border-r"><img alt="" src={src(before, after)} className="absolute inset-0 size-full object-contain p-6" />
          <span className={cn(label, "left-3 bg-popover shadow-sm ring-1 ring-foreground/10")}>{t("before")}</span></div>
        <div className="relative"><img alt="" src={src(after, before)} className="absolute inset-0 size-full object-contain p-6" />
          <span className={cn(label, "right-3 bg-primary text-primary-foreground")}>{t("after")}</span></div>
      </div>
    )
  }
  return (
    <div className="absolute inset-0" style={{ "--cut": `${cut}%` } as React.CSSProperties}>
      <img alt="" src={src(before, after)} className="compare-img absolute inset-0 size-full object-contain" />
      <div className="absolute inset-0 bg-canvas [clip-path:inset(0_0_0_var(--cut))]">
        <img alt="" src={src(after, before)} className="compare-img absolute inset-0 size-full object-contain" />
      </div>
      <span className={cn(label, "left-3 bg-popover shadow-sm ring-1 ring-foreground/10")}>{t("before")}</span>
      <span className={cn(label, "right-3 bg-primary text-primary-foreground")}>{t("after")}</span>
      <div className="pointer-events-none absolute inset-y-0 left-(--cut) z-10 w-0.5 -translate-x-1/2 bg-primary" />
      <div className="pointer-events-none absolute top-1/2 left-(--cut) z-10 grid size-9 -translate-1/2 place-items-center rounded-full bg-primary text-primary-foreground shadow-md">
        <ChevronsLeftRight className="size-4" />
      </div>
      <input type="range" min={0} max={100} value={cut} aria-label={t("compare")} onChange={(e) => setCut(+e.target.value)}
             className="absolute inset-0 z-20 size-full cursor-ew-resize opacity-0" />
    </div>
  )
}
