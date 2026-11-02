import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle, Bot, Box, Check, ChevronDown, ChevronRight, Clock, Columns2, Copy, Cylinder, FileCode2, FileImage, FolderOpen,
  Globe, Highlighter, Loader2, Monitor, Moon, PencilRuler, Plus, Search, Share2, ShieldCheck, Sun, Triangle, Upload,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Breadcrumb, BreadcrumbItem, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Toggle } from "@/components/ui/toggle"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { Stage, type StageHandle } from "@/components/stage"
import {
  ago, api, base, ext, F, isPart, post, stateOf, type Lang, type Layer, type ProgressEvent, type Run, type Timeline,
} from "@/lib/agentcad"
import { useGlide } from "@/lib/use-glide"
import { useWorkspace, type ChangeEvent } from "@/lib/use-viewer"
import { cn } from "@/lib/utils"

const FORMAT: Record<string, { icon: LucideIcon; tone: string }> = {
  dxf: { icon: PencilRuler, tone: "bg-sky-500/10 text-sky-600 dark:text-sky-400" },
  step: { icon: Box, tone: "bg-violet-500/10 text-violet-600 dark:text-violet-400" },
  stl: { icon: Triangle, tone: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
  fcstd: { icon: Cylinder, tone: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
}
const formatOf = (p: string) => FORMAT[{ dxf: "dxf", dwg: "dxf", stl: "stl", fcstd: "fcstd" }[ext(p)] || "step"]
const EXT_LABEL: Record<string, string> = { fcstd: "FCStd", stp: "STEP" }
const extLabel = (p: string) => EXT_LABEL[ext(p)] || ext(p).toUpperCase()

type Theme = "auto" | "light" | "dark"
const THEME_ICON: Record<Theme, LucideIcon> = { auto: Monitor, light: Sun, dark: Moon }
const NEXT_THEME: Record<Theme, Theme> = { auto: "light", light: "dark", dark: "auto" }
const APP_COLORS: Record<string, string> = { "Claude Code": "#d97757", Codex: "#4b5563", "Claude Desktop": "#b8613f", Cursor: "#2f6fdf" }
const params = new URLSearchParams(location.search)  // ?lang=zh|en&theme=light|dark override the saved choice
const store = { get: (k: string) => { try { return localStorage.getItem(k) } catch { return null } },
                set: (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* storage blocked */ } } }

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (["light", "dark"].includes(params.get("theme") || "") ? params.get("theme") : store.get("agentcad-theme") || "auto") as Theme)
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)")
    const apply = () => document.documentElement.classList.toggle("dark", theme === "dark" || (theme === "auto" && mq.matches))
    apply()
    mq.addEventListener("change", apply)
    return () => mq.removeEventListener("change", apply)
  }, [theme])
  return [theme, (v: Theme) => { setTheme(v); store.set("agentcad-theme", v) }] as const
}

function Tip({ label, children, side }: { label: string; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return <Tooltip><TooltipTrigger asChild>{children}</TooltipTrigger><TooltipContent side={side}>{label}</TooltipContent></Tooltip>
}

function CardHead({ title, count, children }: { title: string; count?: number | string; children?: React.ReactNode }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      <h2 className="shrink-0 text-sm font-semibold whitespace-nowrap">{title}</h2>
      {!!count && <span className="text-xs text-muted-foreground tabular-nums">{count}</span>}
      <div className="ml-auto flex min-w-0 items-center gap-1">{children}</div>
    </div>
  )
}

// shadcn's tabs with an indicator that glides to the chosen tab
function SlidingTabs({ value, onChange, items }: { value: string; onChange(v: string): void; items: [string, string][] }) {
  const list = useRef<HTMLDivElement>(null)
  const [ind, setInd] = useState<{ x: number; w: number } | null>(null)
  useLayoutEffect(() => {
    const measure = () => {
      const on = list.current?.querySelector<HTMLElement>('[data-state="active"]')
      if (on) setInd({ x: on.offsetLeft, w: on.offsetWidth })
    }
    measure()
    const ro = new ResizeObserver(measure)
    if (list.current) ro.observe(list.current)
    return () => ro.disconnect()
  }, [value, items])
  return (
    <Tabs value={value} onValueChange={onChange}>
      <TabsList ref={list} className="relative w-full">
        {ind && <span className="absolute top-[3px] bottom-[3px] left-0 rounded-md bg-background shadow-sm ring-1 ring-foreground/5 transition-[transform,width] duration-200 ease-out dark:bg-input/50"
                      style={{ transform: `translateX(${ind.x}px)`, width: ind.w }} />}
        {items.map(([v, label]) => (
          <TabsTrigger key={v} value={v} className="relative z-10 data-active:bg-transparent! data-active:shadow-none! dark:data-active:border-transparent! dark:data-active:bg-transparent!">{label}</TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  )
}

function download(blob: Blob, name: string) {
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob); a.download = name
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 4000)
}

function Confetti({ run, ok, text }: { run: string; ok: boolean; text: string }) {
  const bits = useMemo(() => Array.from({ length: ok && !matchMedia("(prefers-reduced-motion: reduce)").matches ? 46 : 0 }, (_, i) => ({
    left: Math.random() * 100, c: ["#1f6feb", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"][i % 6],
    dx: Math.random() * 160 - 80, r: Math.random() * 720 - 360, delay: Math.random() * 0.4, dur: 1.8 + Math.random() * 1.2,
  })), [run, ok])
  return (
    <div className="pointer-events-none absolute inset-0 z-30 overflow-hidden">
      <div className={cn("absolute top-[42%] left-1/2 flex items-center gap-3 rounded-2xl bg-popover px-7 py-4 text-2xl font-bold whitespace-nowrap shadow-xl ring-1 ring-foreground/10",
                         ok ? "text-success" : "text-destructive")} style={{ animation: "done-pop 3s ease forwards" }}>
        {ok ? <Check className="size-8" strokeWidth={3} /> : <AlertTriangle className="size-8" />}{text}
      </div>
      {bits.map((b, i) => (
        <i key={i} className="absolute -top-3.5 h-3.5 w-2 rounded-[2px]" style={{ left: `${b.left}%`, background: b.c, "--dx": `${b.dx}px`, "--r": `${b.r}deg`,
           animation: `confetti-fall ${b.dur}s ease-in ${b.delay}s forwards` } as React.CSSProperties} />
      ))}
    </div>
  )
}

export default function App() {
  const [lang, setLangState] = useState<Lang>(() => (["zh", "en"].includes(params.get("lang") || "") ? params.get("lang") : F().pick()) as Lang)
  const setLang = (l: Lang) => { setLangState(l); store.set("agentcad-lang", l) }
  const t = useCallback((k: string, v?: Record<string, unknown>) => F().t(k, v, lang), [lang])
  const [theme, setTheme] = useTheme()
  const [path, setPath] = useState<string | null>(() => decodeURIComponent(location.hash.slice(1)) || null)
  const [version, setVersion] = useState<string | null>(null)
  const [tl, setTl] = useState<Timeline | null>(null)
  const [removed, setRemoved] = useState(false)
  const [diff, setDiff] = useState<{ cls: string; text: string }[] | null>(null)
  const [layers, setLayers] = useState<Layer[]>([])
  const [hidden, setHidden] = useState<string[]>([])
  const [highlight, setHighlight] = useState(true)
  const [compare, setCompare] = useState(false)
  const [follow, setFollow] = useState(true)
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState("all")
  const [ping, setPing] = useState<Set<string>>(new Set())
  const [reload, setReload] = useState(0)
  const [toastMsg, setToastMsg] = useState<{ text: string; n: number } | null>(null)
  const [party, setParty] = useState<{ run: string; ok: boolean; text: string } | null>(null)
  const [dropping, setDropping] = useState(false)
  const stage = useRef<StageHandle>(null)
  const pick = useRef<HTMLInputElement>(null)
  const celebrated = useRef<string | null>(null)
  const pathRef = useRef(path)
  pathRef.current = path

  const toast = useCallback((text: string) => setToastMsg((m) => ({ text, n: (m?.n || 0) + 1 })), [])
  useEffect(() => { if (!toastMsg) return; const h = setTimeout(() => setToastMsg(null), 2600); return () => clearTimeout(h) }, [toastMsg])
  const open = useCallback((p: string) => { location.hash = encodeURIComponent(p) }, [])

  const followRef = useRef(follow)
  followRef.current = follow
  const { ws, loadList } = useWorkspace({
    onActivity(ev: ProgressEvent, run: Run) {
      if (ev.drawing && ev.drawing !== pathRef.current && ev.state === "working" && followRef.current) open(ev.drawing)
      if (ev.state === "done" && ev.tool !== "validate_drawing" && Date.now() / 1000 - ev.ts < 15 && celebrated.current !== run.run) {
        celebrated.current = run.run
        const ok = ev.passed !== false
        setParty({ run: run.run, ok, text: ok ? F().t("doneAll", {}, lang) : F().verdict(ev, lang) })
        setTimeout(() => setParty(null), 3400)
      }
    },
    onChange(ev: ChangeEvent) {
      if (ev.drawing === pathRef.current) setReload((n) => n + 1)
      else if (ev.kind !== "removed" && followRef.current) open(ev.drawing)
      else if (ev.kind !== "removed") setPing((s) => new Set(s).add(ev.drawing))
    },
  })

  // the open file follows the address (#path), so a link opens it and Back works
  useEffect(() => {
    const on = () => setPath(decodeURIComponent(location.hash.slice(1)) || null)
    addEventListener("hashchange", on)
    return () => removeEventListener("hashchange", on)
  }, [])
  useEffect(() => { if (!path && ws.drawings.length && !location.hash) open(ws.drawings[0]) }, [ws.drawings, path, open])
  useEffect(() => {
    setVersion(null); setHidden([]); setLayers([]); setRemoved(false); setCompare(false); setTl(null)
    if (path) setPing((s) => { if (!s.has(path)) return s; const n = new Set(s); n.delete(path); return n })
  }, [path])
  useEffect(() => { document.documentElement.lang = lang === "zh" ? "zh-CN" : "en"; document.title = t("title") }, [lang, t])

  // the open file's versions, layers and what its last change did
  useEffect(() => {
    if (!path) return
    let live = true
    api<Timeline>("/api/timeline", { path })
      .then((r) => { if (live) { setTl(r); setRemoved(false) } })
      .catch((e) => { if (live && e?.code === "FILE_NOT_FOUND") setRemoved(true) })
    return () => { live = false }
  }, [path, reload])
  useEffect(() => {
    if (!path || isPart(path)) { setLayers([]); return }
    let live = true
    api<{ layers: Layer[] }>("/api/layers", { path, v: version || "current" }).then((r) => { if (live) setLayers(r.layers.filter((l) => l.entities > 0)) }).catch(() => {})
    return () => { live = false }
  }, [path, version, reload])
  useEffect(() => {
    if (!path) return
    let live = true
    setDiff(null)
    api<{ summary?: { added: number; modified: number; deleted: number }; note?: string; added?: Rec[]; modified?: Rec[]; deleted?: Rec[];
          shape?: Record<string, { old: unknown; new: unknown }>; layers?: { added?: string[]; deleted?: string[] } }>("/api/diff", { path, v: version || "current" })
      .then((d) => {
        if (!live) return
        const ent = (e: Rec) => `${e.id} ${e.type}${e.layer ? " @" + e.layer : ""}${e.tag ? " tag:" + e.tag : ""}`
        const rows: { cls: string; text: string }[] = []
        if (d.summary) rows.push({ cls: "", text: t("changesSummary", { a: d.summary.added, m: d.summary.modified, d: d.summary.deleted }) })
        if (d.note) rows.push({ cls: "text-muted-foreground", text: d.note })
        for (const e of (d.added || []).slice(0, 60)) rows.push({ cls: "text-success", text: "+ " + ent(e) })
        for (const e of (d.modified || []).slice(0, 60)) {
          const f = Object.keys(e.changes || e.changed || {}).join(", ")
          rows.push({ cls: "text-warning", text: `~ ${e.id} ${e.type}${f ? ` (${f})` : ""}` })
        }
        for (const e of (d.deleted || []).slice(0, 60)) rows.push({ cls: "text-destructive", text: "− " + ent(e) })
        for (const [k, c] of Object.entries(d.shape || {})) rows.push({ cls: "text-warning", text: `${k}: ${JSON.stringify(c.old)} → ${JSON.stringify(c.new)}` })
        for (const l of d.layers?.added || []) rows.push({ cls: "text-success", text: "+ layer " + l })
        for (const l of d.layers?.deleted || []) rows.push({ cls: "text-destructive", text: "− layer " + l })
        setDiff(rows)
      })
      .catch((e) => live && setDiff([{ cls: "text-muted-foreground", text: e?.message || "" }]))
    return () => { live = false }
  }, [path, version, reload, t])

  // adding files: the button, dragging them onto the page, or Ctrl+V of files copied in Explorer / Finder
  const importFiles = useCallback(async (list: FileList | File[] | null) => {
    const files = [...(list || [])]
    if (!files.length) return
    if (!ws.canAdd) { toast(t("readOnlyAdd")); return }
    let last: { path: string; shown?: boolean; kind?: string; renamed?: boolean } | null = null, added = 0
    for (const f of files) {
      toast(t("adding", { f: f.name }))
      const r = await post("/api/import", f, { "X-AgentCAD-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" })
      if (!r.ok) {
        const why = r.error && F().UI[lang]["why_" + r.error.code] ? t("why_" + r.error.code) : r.error?.message || ""
        toast(t("addFailed", { f: f.name, m: why })); await new Promise((ok) => setTimeout(ok, 2400)); continue
      }
      added++; last = r
    }
    if (!last) return
    const msg = added > 1 ? t("addedMany", { n: added }) : last.shown ? t("addedShown", { f: base(last.path) })
      : last.kind === "dwg" ? t("addedDwg", { f: base(last.path) }) : t("addedKept", { f: base(last.path) })
    toast(msg + (last.renamed ? " " + t("renamed") : ""))
    if (last.shown) { await loadList(); open(last.path) }
  }, [ws.canAdd, lang, t, toast, loadList, open])
  useEffect(() => {
    let depth = 0
    const has = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files")
    const enter = (e: DragEvent) => { if (!has(e) || !ws.canAdd) return; e.preventDefault(); depth++; setDropping(true) }
    const over = (e: DragEvent) => { if (has(e)) { e.preventDefault(); e.dataTransfer!.dropEffect = "copy" } }
    const leave = (e: DragEvent) => { if (has(e) && --depth <= 0) { depth = 0; setDropping(false) } }
    const drop = (e: DragEvent) => { if (!has(e)) return; e.preventDefault(); depth = 0; setDropping(false); importFiles(e.dataTransfer!.files) }
    const paste = (e: ClipboardEvent) => {
      if ((e.target as HTMLElement).closest?.("input, textarea, [contenteditable]")) return
      if (e.clipboardData?.files.length) { e.preventDefault(); importFiles(e.clipboardData.files) }
    }
    addEventListener("dragenter", enter); addEventListener("dragover", over); addEventListener("dragleave", leave)
    addEventListener("drop", drop); addEventListener("paste", paste)
    return () => {
      removeEventListener("dragenter", enter); removeEventListener("dragover", over); removeEventListener("dragleave", leave)
      removeEventListener("drop", drop); removeEventListener("paste", paste)
    }
  }, [ws.canAdd, importFiles])

  const reveal = async (p: string) => {
    const r = await post("/api/reveal", JSON.stringify({ path: p }), { "Content-Type": "application/json" })
    if (!r.ok) toast(t("cannotOpen", { m: r.error?.message || "" }))
  }
  const copyPath = async () => {
    try { await navigator.clipboard.writeText(ws.root); toast(t("pathCopied")) } catch { toast(ws.root) }
  }
  const stem = () => base(path).replace(/\.[^.]+$/, "") || "drawing"
  const saveHtml = async () => {
    toast(t("saving"))
    try {
      const r = await fetch("/api/export?" + new URLSearchParams({ path: path!, v: version || "current" }))
      if (!r.ok) throw (await r.json()).error
      const cd = r.headers.get("content-disposition") || "", star = /filename\*=UTF-8''([^;]+)/.exec(cd)
      download(await r.blob(), star ? decodeURIComponent(star[1]) : (/filename="([^"]+)"/.exec(cd) || [])[1] || stem() + ".html")
      toast(t("saved"))
    } catch (e) { toast(t("saveFailed", { m: (e as Error).message || String(e) })) }
  }
  const savePng = async () => {
    toast(t("saving"))
    try {
      const c = await stage.current!.picture()
      download(await new Promise<Blob>((ok) => c.toBlob((b) => ok(b!), "image/png")), `${stem()}.png`)
      toast(t("saved"))
    } catch (e) { toast(t("saveFailed", { m: (e as Error).message || String(e) })) }
  }

  // ---- derived -------------------------------------------------------------------------------------------
  const runs = ws.runs
  const latest = runs[runs.length - 1]
  const st = stateOf(latest)
  const kindOf = (p?: string) => (isPart(p) ? "part" : "drawing") as "part" | "drawing"
  const lastChange = (p: string) => runs.reduce((ts, r) => (r.drawing === p ? Math.max(ts, r.last.ts) : ts), 0)
  const shown = ws.drawings.filter((p) => (kind === "all" || kindOf(p) === kind) && base(p).toLowerCase().includes(query.trim().toLowerCase()))
  const feed = [...runs].reverse().slice(0, 60)
  const sessions = ws.sessions || []
  const appName = (s?: { client?: string }) => s?.client || t("someApp")
  const hm = (ts?: number | string) => ts ? new Date(typeof ts === "number" ? ts * 1000 : ts).toLocaleTimeString(lang === "zh" ? "zh-CN" : undefined, { hour: "2-digit", minute: "2-digit" }) : ""

  let stTitle = t("idle"), stText = t("idleHint"), pct = 0, indet = false
  if (latest && st !== "idle") {
    const ev = latest.last
    if (st === "working") {
      stTitle = t("working")
      const s = latest.step
      if (s?.total) { stText = `${t("stepOf", { i: s.step, n: s.total })}: ${F().opText(s.op || {}, lang, "doing")}`; pct = Math.max(4, ((s.step || 1) - 0.5) / s.total * 100) }
      else { stText = F().toolText(latest.tool, kindOf(latest.drawing), lang, "doing") + "…"; indet = true }
    } else if (st === "checking") { stTitle = t("checking"); stText = t("checkingNow"); pct = 100; indet = true }
    else if (st === "done") {
      stTitle = t("doneAll")
      stText = [F().summary({ ...ev, drawing: latest.drawing }, lang), (ev.total || 0) > 1 ? t("doneSteps", { n: ev.total }) : "", F().verdict(ev, lang)].filter(Boolean).join(" · ")
      pct = 100
    } else if (st === "error") { stTitle = t("error"); stText = `${ev.error?.message ? ev.error.message + " " : ""}${t("errorUnchanged")}`; pct = 100 }
  }
  const tone = { idle: "", working: "border-primary/30 bg-primary/6", checking: "border-warning/35 bg-warning/8", done: "border-success/30 bg-success/8", error: "border-destructive/35 bg-destructive/8" }[st]
  const toneIco = { idle: "bg-muted text-muted-foreground", working: "bg-primary/12 text-primary", checking: "bg-warning/15 text-warning", done: "bg-success/15 text-success", error: "bg-destructive/12 text-destructive" }[st]
  const toneBar = { idle: "", working: "bg-primary/15 *:data-[slot=progress-indicator]:bg-primary", checking: "bg-warning/15 *:data-[slot=progress-indicator]:bg-warning",
                    done: "bg-success/15 *:data-[slot=progress-indicator]:bg-success", error: "bg-destructive/15 *:data-[slot=progress-indicator]:bg-destructive" }[st]
  const StIcon = { idle: Clock, working: Loader2, checking: Search, done: Check, error: AlertTriangle }[st]
  const ThemeIcon = THEME_ICON[theme]
  const filesGlide = useGlide<HTMLUListElement>(), feedGlide = useGlide<HTMLOListElement>(), tlGlide = useGlide<HTMLUListElement>()
  const empty = !ws.drawings.length

  return (
    <TooltipProvider delayDuration={300}>
      <div className="grid h-svh grid-cols-[280px_minmax(0,1fr)_300px] grid-rows-[auto_minmax(0,1fr)] gap-3 bg-background p-3 pt-0 max-lg:grid-cols-[248px_minmax(0,1fr)_272px] max-md:flex max-md:h-auto max-md:min-h-svh max-md:flex-col">
        {/* header */}
        <header className="col-span-3 flex h-14 items-center gap-2 px-1">
          <div className="flex items-center gap-2.5">
            <img src="/logo.svg" alt="" className="size-8 rounded-lg shadow-sm" />
            <span className="text-[15px] font-semibold tracking-tight">AgentCAD</span>
          </div>
          <Popover>
            <PopoverTrigger asChild>
              <button className="ml-2 flex h-6 items-center gap-1.5 rounded-full border bg-card px-2.5 text-xs text-muted-foreground transition-colors hover:bg-accent">
                <span className={cn("size-1.5 rounded-full", !ws.live ? "bg-destructive" : sessions.length ? "bg-success shadow-[0_0_0_3px] shadow-success/20" : "bg-muted-foreground/50")} />
                {!ws.live ? t("disconnected") : !sessions.length ? t("noAssistant") : sessions.length === 1 ? t("oneConnected", { app: appName(sessions[0]) }) : t("manyConnected", { n: sessions.length })}
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-96 p-2">
              <div className="px-2 pt-1 pb-2 text-xs font-medium text-muted-foreground">{t("connTitle")}</div>
              {sessions.length ? sessions.map((s, i) => {
                const name = appName(s), initials = name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase()
                const bits = [t("connStarted", { t: hm(s.started) }), s.drawing ? t("connWorking", { f: base(s.drawing) }) + " · " + t("connLast", { t: ago(s.last_seen, lang) }) : t("connWaiting")]
                return (
                  <div key={i} className="flex items-center gap-3 rounded-md p-2">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg text-xs font-bold text-white" style={{ background: APP_COLORS[name] || "#1f6feb" }}>{initials}</span>
                    <div className="min-w-0"><div className="text-sm font-medium">{name}{s.label ? " · " + s.label : ""}</div>
                      <div className="text-xs text-muted-foreground">{bits.join(" · ")}</div></div>
                  </div>
                )
              }) : <div className="px-2 pb-2 text-sm leading-relaxed text-muted-foreground"><div className="mb-1 font-medium text-foreground">{t("noAssistantTitle")}</div>{t("noAssistantBody")}</div>}
            </PopoverContent>
          </Popover>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setLang(lang === "zh" ? "en" : "zh")} title="Language / 语言">
              <Globe /> <span className="max-sm:hidden">{t("language")}</span>
            </Button>
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setTheme(NEXT_THEME[theme])} title={t("theme")}>
              <ThemeIcon /> <span className="max-sm:hidden">{t({ auto: "themeAuto", light: "themeLight", dark: "themeDark" }[theme])}</span>
            </Button>
            <Separator orientation="vertical" className="mx-2 h-5!" />
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button size="sm" disabled={!path}><Share2 /> {t("share")}</Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuItem className="items-start gap-3 py-2" onSelect={saveHtml}>
                  <FileCode2 className="mt-0.5" /><div><div className="font-medium">{t("saveHtml")}</div><div className="text-xs text-muted-foreground">{t("saveHtmlHint")}</div></div>
                </DropdownMenuItem>
                <DropdownMenuItem className="items-start gap-3 py-2" onSelect={savePng}>
                  <FileImage className="mt-0.5" /><div><div className="font-medium">{t("savePng")}</div><div className="text-xs text-muted-foreground">{t("savePngHint")}</div></div>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* files */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-3">
          <CardHead title={t("files")} count={ws.drawings.length}>
            {ws.canAdd && <Tip label={`${t("addFiles")} ${t("addHint")}`}><Button variant="ghost" size="icon-sm" aria-label={t("addFiles")} onClick={() => pick.current?.click()}><Plus /></Button></Tip>}
          </CardHead>
          <input ref={pick} type="file" multiple hidden accept=".dxf,.dwg,.fcstd,.FCStd,.step,.stp,.stl,.brep,.pdf,.png,.jpg,.jpeg,.webp"
                 onChange={(e) => { importFiles(e.target.files); e.target.value = "" }} />
          <div className="flex shrink-0 flex-col gap-2.5 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchFiles")} className="h-8 pl-8" />
            </div>
            <SlidingTabs value={kind} onChange={setKind} items={[["all", t("all")], ["part", t("part")], ["drawing", t("drawing")]]} />
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <ul ref={filesGlide.ref} className="relative flex flex-col gap-0.5 px-2 pb-2">
              <span className="pointer-events-none absolute inset-x-2 top-0 rounded-lg bg-accent/70" style={filesGlide.style} />
              {shown.map((p) => {
                const { icon: Icon, tone: tile } = formatOf(p), on = p === path, ts = lastChange(p), stamp = String(ws.stamps.get(p) || 0)
                return (
                  <li key={p} data-glide className="group relative">
                    <HoverCard openDelay={500} closeDelay={80}>
                      <HoverCardTrigger asChild>
                        <button onClick={() => open(p)} title={p}
                                className={cn("relative flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors", on && "bg-accent")}>
                          <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", tile)}><Icon className="size-4" /></span>
                          <span className="min-w-0 flex-1 pr-6">
                            <span className={cn("block truncate text-sm", on && "font-medium")}>{base(p)}</span>
                            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                              {t(kindOf(p))}{ts ? ` · ${ago(ts, lang)}` : ""}
                              {ping.has(p) && <span className="size-1.5 animate-pulse rounded-full bg-primary" />}
                            </span>
                          </span>
                        </button>
                      </HoverCardTrigger>
                      <HoverCardContent side="right" align="start" className="w-64 p-2">
                        <img alt="" src={"/api/thumb?" + new URLSearchParams({ path: p, s: stamp })} className={cn("aspect-[4/3] w-full rounded-md bg-white object-contain", !isPart(p) && "dark:invert-[.88] dark:hue-rotate-180")} />
                        <div className="mt-2 truncate px-1 text-xs text-muted-foreground">{p}</div>
                      </HoverCardContent>
                    </HoverCard>
                    <Tip label={t("showInFolder")}>
                      <Button variant="ghost" size="icon-xs" aria-label={t("showInFolder")} onClick={() => reveal(p)}
                              className="absolute top-1/2 right-2 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"><FolderOpen /></Button>
                    </Tip>
                  </li>
                )
              })}
              {!shown.length && <li className="px-2 py-6 text-center text-sm text-muted-foreground">{ws.drawings.length ? t("filesNoMatch") : t("filesEmpty")}</li>}
              {ws.canAdd && !empty && (
                <li className="px-2 pt-1 text-center text-[11px] leading-4 text-muted-foreground/80">{t("addHint")}</li>
              )}
            </ul>
          </ScrollArea>
          {ws.root && (
            <div className="flex shrink-0 items-center gap-1 border-t px-4 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-xs text-muted-foreground">{t("savedIn")}</div>
                <div className="truncate font-mono text-xs [direction:rtl] text-left" title={ws.root}>{ws.root}</div>
              </div>
              <Tip label={t("openFolder")}><Button variant="ghost" size="icon-sm" aria-label={t("openFolder")} onClick={() => reveal("")}><FolderOpen /></Button></Tip>
              <Tip label={t("copyPath")}><Button variant="ghost" size="icon-sm" aria-label={t("copyPath")} onClick={copyPath}><Copy /></Button></Tip>
            </div>
          )}
        </Card>

        {/* the open file */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-1">
          <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            {path && (
              <>
                <Breadcrumb className="min-w-0">
                  <BreadcrumbList className="flex-nowrap">
                    <BreadcrumbItem className="shrink-0 whitespace-nowrap text-muted-foreground max-sm:hidden">{t("files")}</BreadcrumbItem>
                    <BreadcrumbSeparator className="max-sm:hidden"><ChevronRight /></BreadcrumbSeparator>
                    <BreadcrumbItem className="min-w-0"><BreadcrumbPage className="truncate font-semibold" title={path}>{base(path)}</BreadcrumbPage></BreadcrumbItem>
                  </BreadcrumbList>
                </Breadcrumb>
                <Badge variant="secondary" className="shrink-0 rounded-md font-normal">{t(kindOf(path))} · {extLabel(path)}</Badge>
                <div className="ml-auto flex shrink-0 items-center gap-1.5">
                  {!isPart(path) && (
                    <Toggle variant="outline" size="sm" pressed={highlight} onPressedChange={setHighlight}><Highlighter /> <span className="max-sm:hidden">{t("highlight")}</span></Toggle>
                  )}
                  <Toggle variant="outline" size="sm" pressed={compare} onPressedChange={setCompare}><Columns2 /> <span className="max-sm:hidden">{t("compare")}</span></Toggle>
                </div>
              </>
            )}
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 max-md:p-3">
            {/* what is happening now */}
            <button onClick={() => latest?.drawing && st !== "idle" && open(latest.drawing)}
                    className={cn("flex shrink-0 items-center gap-3 rounded-lg border bg-card px-3.5 py-2.5 text-left transition-colors duration-300", tone, st !== "idle" && "cursor-pointer")}>
              <span className={cn("grid size-7 shrink-0 place-items-center rounded-full transition-colors duration-300", toneIco)}>
                <StIcon className={cn("size-4", st === "working" && "animate-spin")} strokeWidth={st === "done" ? 2.5 : 2} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-sm">
                  <span className="shrink-0 font-semibold">{stTitle}</span>
                  <span className="truncate text-muted-foreground" title={stText}>{stText}
                    {latest?.drawing && st !== "idle" && <span className="ml-1.5 font-mono text-xs">{base(latest.drawing)}</span>}</span>
                  {latest && st !== "idle" && <span className="ml-auto shrink-0 text-xs text-muted-foreground">{ago(latest.last.ts, lang)}</span>}
                </div>
                {st !== "idle" && (
                  <Progress value={indet ? 30 : pct} className={cn("mt-2 h-1", toneBar, indet && "*:data-[slot=progress-indicator]:w-[30%] *:data-[slot=progress-indicator]:flex-none *:data-[slot=progress-indicator]:animate-[indet_1.3s_cubic-bezier(.45,0,.55,1)_infinite]")} />
                )}
              </div>
            </button>

            {layers.length > 1 && !compare && (
              <div className="flex shrink-0 flex-wrap gap-1.5">
                {layers.map((l) => {
                  const off = hidden.includes(l.name)
                  return (
                    <Toggle key={l.name} variant="outline" size="sm" pressed={!off} title={t("layers")}
                            onPressedChange={() => setHidden((h) => off ? h.filter((x) => x !== l.name) : [...h, l.name])}
                            className={cn("h-7 rounded-full px-2.5 text-xs data-[state=on]:bg-card", off && "opacity-50")}>
                      <span className={cn("size-2 rounded-[3px]", off && "bg-transparent! ring-1 ring-muted-foreground")} style={{ background: l.color || "currentColor" }} />
                      {l.name} · {l.entities}
                    </Toggle>
                  )
                })}
              </div>
            )}

            {empty || removed ? (
              <div className="grid min-h-[320px] flex-1 place-items-center overflow-auto rounded-lg border bg-card p-8 text-center">
                <div className="max-w-lg">
                  <img src="/logo.svg" alt="" className="mx-auto size-14 rounded-2xl shadow-md" />
                  <h3 className="mt-4 text-xl font-semibold">{removed ? t("removed") : sessions.length ? t("readyTitle", { app: appName(sessions[0]) }) : ws.sessions ? t("noAssistantTitle") : t("waitingTitle")}</h3>
                  {!removed && <p className="mt-1.5 text-sm text-muted-foreground">{sessions.length ? t("readyBody") : ws.sessions ? t("noAssistantBody") : t("waitingBody")}</p>}
                  {!removed && <TryList t={t} />}
                </div>
              </div>
            ) : (
              <Stage ref={stage} path={path} version={version} tl={tl} highlight={highlight} hidden={hidden} compare={compare} lang={lang}
                     reload={reload} onBackToNow={() => setVersion(null)}>
                {party && <Confetti {...party} />}
              </Stage>
            )}
          </div>
        </Card>

        {/* what happened */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-2">
          <CardHead title={t("activity")} count={feed.length}>
            <Tip label={t("followHint")} side="left">
              <label className="flex min-w-0 cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                <span className="truncate">{t("follow")}</span><Switch size="sm" checked={follow} onCheckedChange={setFollow} />
              </label>
            </Tip>
          </CardHead>
          <ScrollArea className="min-h-0 flex-1">
            <ol ref={feedGlide.ref} className="relative px-2 py-1.5">
              <span className="pointer-events-none absolute inset-x-2 top-0 rounded-lg bg-accent/70" style={feedGlide.style} />
              {feed.map((r, i) => {
                const s = stateOf(r), ev = r.last, k = kindOf(r.drawing)
                let main = s === "done" ? F().summary({ ...ev, drawing: r.drawing }, lang)
                  : s === "error" ? `${F().toolText(r.tool, k, lang, "done")} – ${t("failed")}`
                  : s === "working" ? (r.step ? F().opText(r.step.op || {}, lang, "doing") : F().toolText(r.tool, k, lang, "doing")) + "…"
                  : s === "checking" ? t("checkingNow") : F().toolText(r.tool, k, lang, "done")
                main = main.charAt(0).toUpperCase() + main.slice(1)
                const v = s === "done" ? F().verdict(ev, lang) : ""
                const Ico = s === "error" ? AlertTriangle : s === "working" ? Loader2 : ev.client ? Bot : Check
                return (
                  <li key={r.run} data-glide onClick={() => r.drawing && open(r.drawing)}
                      className="relative flex cursor-pointer gap-2.5 rounded-lg px-2 py-1.5">
                    {i < feed.length - 1 && <span className="absolute top-7 bottom-[-6px] left-[17.5px] w-px bg-border" />}
                    <span className={cn("relative mt-0.5 grid size-5 shrink-0 place-items-center rounded-full",
                                        s === "error" ? "bg-destructive/12 text-destructive" : s === "working" || s === "checking" || ev.client ? "bg-primary/12 text-primary" : "bg-success/15 text-success")}>
                      <Ico className={cn("size-3", s === "working" && "animate-spin")} strokeWidth={s === "done" && !ev.client ? 3 : 2.2} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start gap-2">
                        <span className="flex-1 text-[13px] leading-5">{main}</span>
                        <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">{ago(ev.ts, lang)}</span>
                      </div>
                      <div className="truncate font-mono text-[11px] leading-4 text-muted-foreground">{base(r.drawing)}</div>
                      {(ev.client || v || (s === "error" && ev.error)) && (
                        <div className="mt-1 flex items-center gap-1 text-[11px] leading-4 text-muted-foreground">
                          {ev.client && <><span className="font-medium text-primary">{ev.client}</span>{ev.conversation && <>·<span className="truncate">{ev.conversation}</span></>}</>}
                          {v && <span className={cn("ml-auto flex shrink-0 items-center gap-1", ev.passed === false ? "text-destructive" : "text-success")}>{ev.passed !== false && <ShieldCheck className="size-3" />}{v}</span>}
                          {s === "error" && ev.error && <span className="truncate text-destructive">{ev.error.message || ev.error.code}</span>}
                        </div>
                      )}
                    </div>
                  </li>
                )
              })}
              {!feed.length && <li className="px-2 py-6 text-center text-sm text-muted-foreground">{t("activityEmpty")}</li>}
            </ol>
          </ScrollArea>

          {path && tl && (
            <div className="flex max-h-[38%] shrink-0 flex-col border-t px-2 pt-2.5 pb-2">
              <div className="flex items-center gap-2 px-2 pb-1.5 text-xs text-muted-foreground">{t("history")} <span className="tabular-nums">{tl.records.length + 1}</span></div>
              <ScrollArea className="min-h-0">
                <ul ref={tlGlide.ref} className="relative flex flex-col gap-0.5">
                  <span className="pointer-events-none absolute inset-x-0 top-0 rounded-md bg-accent/70" style={tlGlide.style} />
                  <VersionRow on={!version} seq={t("now")} text={t("latest")} note={tl.modified_outside_runtime ? t("changedOutside") : ""} onClick={() => setVersion(null)} />
                  {[...tl.records].reverse().map((r) => {
                    const pickable = !!(r.version && r.available), ch = r.changes || {}
                    const title = [r.client && (r.conversation ? `${r.client} · ${r.conversation}` : r.client), r.label,
                      r.ok ? t("changesSummary", { a: ch.added || 0, m: ch.modified || 0, d: ch.deleted || 0 }) : `${t("failed")}${r.error ? ": " + (r.error.message || r.error.code) : ""}`,
                      r.version && !r.available ? t("notStored") : ""].filter(Boolean).join(" · ")
                    return (
                      <VersionRow key={r.seq} on={!!version && r.version === version} seq={`#${r.seq}`} bad={!r.ok} disabled={!pickable} title={title}
                                  text={F().summary({ tool: r.tool, steps: r.steps, drawing: path }, lang)} time={hm(r.ts)}
                                  onClick={() => pickable && setVersion(r.version === tl.current ? null : r.version!)} />
                    )
                  })}
                </ul>
              </ScrollArea>
            </div>
          )}

          {path && (
            <Collapsible defaultOpen className="shrink-0 border-t">
              <CollapsibleTrigger className="group flex h-10 w-full items-center px-4 text-xs text-muted-foreground hover:text-foreground">
                {t("details")}<ChevronDown className="ml-auto size-3.5 transition-transform duration-200 group-data-[state=open]:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 px-4 pb-2 text-[11px]">
                  <dt className="text-muted-foreground">{t("factFile")}</dt><dd className="truncate font-mono" title={path}>{base(path)}</dd>
                  <dt className="text-muted-foreground">{t("factKind")}</dt><dd className="font-mono">{t(kindOf(path))} · {extLabel(path)}</dd>
                  <dt className="text-muted-foreground">{t("factWhere")}</dt><dd className="truncate font-mono" title={ws.root}>{ws.root}</dd>
                  <dt className="text-muted-foreground">{t("factVersions")}</dt><dd className="font-mono">{t("factVersionsN", { n: tl?.records.length ?? 0 })}</dd>
                </dl>
                {diff && !!diff.length && (
                  <div className="max-h-36 overflow-auto px-4 pb-3 font-mono text-[11px] leading-4">
                    {diff.map((d, i) => <div key={i} className={cn("break-words", d.cls)}>{d.text}</div>)}
                  </div>
                )}
              </CollapsibleContent>
            </Collapsible>
          )}
        </Card>
      </div>

      {/* dropping files onto the page */}
      {dropping && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-primary/10 p-6 backdrop-blur-[3px]">
          <div className="pointer-events-none grid w-[min(560px,100%)] justify-items-center gap-2 rounded-2xl bg-popover px-10 py-9 text-center shadow-2xl outline-2 -outline-offset-[12px] outline-primary outline-dashed">
            <Upload className="size-10 text-primary" />
            <b className="text-xl">{t("dropTitle")}</b>
            <span className="text-sm text-muted-foreground">{t("dropBody")}</span>
          </div>
        </div>
      )}
      {/* toast */}
      <div role="status" aria-live="polite"
           className={cn("pointer-events-none fixed bottom-6 left-1/2 z-50 max-w-[calc(100vw-32px)] -translate-x-1/2 rounded-full bg-foreground px-5 py-2.5 text-sm text-background shadow-xl transition-all duration-200",
                         toastMsg ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0")}>
        {toastMsg?.text}
      </div>
    </TooltipProvider>
  )
}

interface Rec { id: string; type: string; layer?: string; tag?: string; changes?: Record<string, unknown>; changed?: Record<string, unknown> }

function VersionRow({ on, seq, text, time, note, bad, disabled, title, onClick }:
  { on: boolean; seq: string; text: string; time?: string; note?: string; bad?: boolean; disabled?: boolean; title?: string; onClick(): void }) {
  return (
    <li data-glide className="relative">
      <button onClick={onClick} disabled={disabled} title={title}
              className={cn("relative flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-left text-[13px] transition-colors disabled:cursor-default disabled:opacity-50", on && "bg-accent")}>
        <span className={cn("grid size-3.5 shrink-0 place-items-center rounded-full border-[1.5px] transition-colors", bad ? "border-destructive" : on ? "border-primary" : "border-muted-foreground/40")}>
          <span className={cn("size-1.5 rounded-full bg-primary transition-transform duration-200", on ? "scale-100" : "scale-0")} />
        </span>
        <span className="w-9 shrink-0 font-semibold">{seq}</span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground">{text}</span>
        {note && <span className="shrink-0 text-[11px] text-destructive">{note}</span>}
        {time && <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{time}</span>}
      </button>
    </li>
  )
}

function TryList({ t }: { t: (k: string) => string }) {
  const [copied, setCopied] = useState("")
  const copy = async (k: string) => {
    try { await navigator.clipboard.writeText(t(k)) } catch {
      const ta = document.createElement("textarea"); ta.value = t(k); document.body.appendChild(ta); ta.select()
      try { document.execCommand("copy") } catch { /* nothing more to try */ } ta.remove()
    }
    setCopied(k); setTimeout(() => setCopied(""), 1800)
  }
  return (
    <div className="mt-5 grid gap-2 text-left">
      <div className="text-xs font-medium text-muted-foreground">{t("tryThis")}</div>
      {["try1", "try2", "try3"].map((k) => (
        <div key={k} className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2 text-sm">
          <span className="flex-1">“{t(k)}”</span>
          <Button size="sm" variant={copied === k ? "default" : "outline"} className={cn(copied === k && "bg-success hover:bg-success")} onClick={() => copy(k)}>
            {copied === k ? t("copied") : t("copy")}
          </Button>
        </div>
      ))}
    </div>
  )
}
