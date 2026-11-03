// The setup wizard's page (agentcad setup --gui, agentcad/setup_gui.py): pick the apps, watch them being connected,
// then the last steps. Every /api call carries the token of the URL the installer opened.
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowRight, Check, ChevronDown, Copy, FolderOpen, Languages, Loader2, MessageSquareText, Minus, MousePointerClick,
  Plug, RotateCw, Share2, Stethoscope, Wand2, X, type LucideIcon,
} from "lucide-react"
import { cn } from "cn"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Progress } from "@/components/ui/progress"
import { T } from "./text"

type Lang = "en" | "zh"
type App = { id: string; label: string; found: boolean }
type Info = { workspace: string; dry_run: boolean; platform: string; apps: App[] }
type StepState = "wait" | "run" | "done" | "error" | "opt"
type Step = { id: string; state: StepState; info: Record<string, any> }
type Wizard = { phase: "ready" | "running" | "done" | "error"; steps: Step[]; result: any; error: any }
type Check_ = { name: string; status: string; detail?: string; required?: boolean }
type View = "welcome" | "pick" | "progress" | "check" | "bye"

const TOKEN = new URLSearchParams(location.search).get("t") || ""
const REPO = "https://github.com/lizaixi01/AgentCAD"
const COLORS: Record<string, string> = { "claude-code": "#d97757", codex: "#4b5563", "claude-desktop": "#b8613f", cursor: "#2f6fdf" }
const INITIALS: Record<string, string> = { "claude-code": "CC", codex: "Cx", "claude-desktop": "C", cursor: "Cu" }
const store = { get: (k: string) => { try { return localStorage.getItem(k) } catch { return null } },
                set: (k: string, v: string) => { try { localStorage.setItem(k, v) } catch { /* storage blocked */ } } }

async function api(path: string, body?: unknown) {
  const r = await fetch(path, body === undefined ? { headers: { "X-AgentCAD-Token": TOKEN } }
    : { method: "POST", headers: { "X-AgentCAD-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(body) })
  return r.json()
}

async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); return } catch { /* not allowed: the old way */ }
  const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select()
  try { document.execCommand("copy") } catch { /* nothing more to try */ }
  ta.remove()
}

function useSystemTheme() {
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)")
    const apply = () => document.documentElement.classList.toggle("dark", mq.matches)
    apply()
    mq.addEventListener("change", apply)
    return () => mq.removeEventListener("change", apply)
  }, [])
}

// --- small pieces -------------------------------------------------------------------------------------------------
function Big({ className, ...props }: React.ComponentProps<typeof Button>) {
  return <Button size="lg" className={cn("h-12 gap-2 rounded-xl px-5 text-base [&_svg:not([class*='size-'])]:size-5", className)} {...props} />
}

function Dots({ on, labels }: { on: number; labels: string[] }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-2 text-sm font-medium">
      {labels.map((s, i) => (
        <li key={s} className={cn("flex items-center gap-2", i === on ? "text-primary" : "text-muted-foreground")}>
          {i > 0 && <span className={cn("h-px w-6", i <= on ? "bg-primary/40" : "bg-border")} />}
          <span className={cn("grid size-7 place-items-center rounded-full text-xs font-semibold",
                              i === on ? "bg-primary text-primary-foreground" : i < on ? "bg-success text-white" : "bg-muted")}>
            {i < on ? <Check className="size-4" strokeWidth={3} /> : i + 1}
          </span>
          <span className="max-sm:hidden">{s}</span>
        </li>
      ))}
    </ol>
  )
}

const STEP_ICON: Record<StepState, { icon: LucideIcon; tone: string }> = {
  run: { icon: Loader2, tone: "bg-primary/10 text-primary [&_svg]:animate-spin" },
  done: { icon: Check, tone: "bg-success text-white" },
  error: { icon: X, tone: "bg-destructive text-white" },
  opt: { icon: Minus, tone: "bg-warning/15 text-warning" },
  wait: { icon: Minus, tone: "bg-muted text-muted-foreground" },
}

function StepRow({ state, title, sub }: { state: StepState; title: string; sub: string }) {
  const { icon: Icon, tone } = STEP_ICON[state]
  return (
    <li className={cn("flex items-center gap-3 rounded-xl border bg-card px-4 py-3 transition-opacity",
                      state === "wait" && "opacity-55", state === "error" && "border-destructive/30 bg-destructive/5")}>
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-full", tone, (state === "done" || state === "error") && "animate-in zoom-in-50")}>
        <Icon className="size-5" strokeWidth={state === "done" || state === "error" ? 3 : 2} />
      </span>
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div className="text-sm break-words text-muted-foreground">{sub}</div>
      </div>
    </li>
  )
}

function Verdict({ ok, title, lead }: { ok: boolean; title: string; lead?: string }) {
  return (
    <div className="mb-6 grid place-items-center text-center">
      <div className={cn("mb-4 grid size-20 place-items-center rounded-full animate-in zoom-in-50 duration-300",
                         ok ? "bg-success/12 text-success" : "bg-destructive/12 text-destructive")}>
        {ok ? <Check className="size-10" strokeWidth={3} /> : <X className="size-10" strokeWidth={3} />}
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      {lead && <p className="mt-2 text-lg text-muted-foreground">{lead}</p>}
    </div>
  )
}

function CopyButton({ text, t }: { text: string; t: (k: string) => string }) {
  const [done, setDone] = useState(false)
  return (
    <Button variant="outline" className="h-10 shrink-0 gap-1.5 rounded-lg px-3.5 text-sm"
            onClick={async () => { await copyText(text); setDone(true); setTimeout(() => setDone(false), 1800) }}>
      {done ? <Check className="text-success" /> : <Copy />}{t(done ? "copied" : "copy")}
    </Button>
  )
}

function Confetti() {
  const bits = useMemo(() => Array.from({ length: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 60 }, (_, i) => ({
    left: Math.random() * 100, c: ["#1f6feb", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"][i % 6],
    dx: Math.random() * 160 - 80, r: Math.random() * 720 - 360, delay: Math.random() * 0.4, dur: 1.8 + Math.random() * 1.2,
  })), [])
  return (
    <div className="pointer-events-none fixed inset-0 z-30 overflow-hidden">
      {bits.map((b, i) => (
        <i key={i} className="absolute -top-3.5 h-3.5 w-2 rounded-[2px]" style={{ left: `${b.left}%`, background: b.c, "--dx": `${b.dx}px`, "--r": `${b.r}deg`,
           animation: `confetti-fall ${b.dur}s ease-in ${b.delay}s forwards` } as React.CSSProperties} />
      ))}
    </div>
  )
}

// --- the page -----------------------------------------------------------------------------------------------------
export default function Setup() {
  useSystemTheme()
  const [lang, setLangState] = useState<Lang>(() => {
    const s = store.get("agentcad-lang")
    return s === "en" || s === "zh" ? s : /^zh\b/i.test(navigator.language || "") ? "zh" : "en"
  })
  const setLang = (l: Lang) => { setLangState(l); store.set("agentcad-lang", l) }
  const t = useCallback((k: string, v?: Record<string, unknown>) =>
    (T[lang][k] || T.en[k] || k).replace(/\{(\w+)\}/g, (_, n) => v && v[n] != null ? String(v[n]) : ""), [lang])
  useEffect(() => { document.documentElement.lang = lang === "zh" ? "zh-CN" : "en"; document.title = t("title") }, [lang, t])

  const [info, setInfo] = useState<Info | null>(null)
  const [lost, setLost] = useState(false)
  const [view, setView] = useState<View>("welcome")
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [toast, setToast] = useState("")
  const toastTimer = useRef<number>(0)
  const say = (msg: string) => { setToast(msg); clearTimeout(toastTimer.current); toastTimer.current = window.setTimeout(() => setToast(""), 2600) }

  const loadInfo = useCallback(async () => {
    const r: Info = await api("/api/info")
    setInfo(r)
    setPicked(p => p.size ? p : new Set(r.apps.filter(a => a.found).map(a => a.id)))
  }, [])
  const markLost = useCallback(() => setLost(true), [])
  useEffect(() => { loadInfo().catch(markLost) }, [loadInfo, markLost])

  const label = (id: string) => info?.apps.find(a => a.id === id)?.label || id
  const friendlyError = (code?: string, app?: string, path?: string) => {
    const k = "err_" + code
    if (!T[lang][k]) return t("err_other")
    const text = t(k, { app: app || "", path: path || "" })
    return path ? text : text.replace(/(文件位置：| File: )$/, "")
  }

  let body: React.ReactNode
  if (lost) body = <p className="text-lg text-muted-foreground">{t("lost")}</p>
  else if (view === "bye") body = <Verdict ok title={t("bye")} lead={t("byeLead")} />
  else if (!info) body = <div className="grid place-items-center py-16"><Loader2 className="size-8 animate-spin text-muted-foreground" /></div>
  else if (view === "welcome") body = <Welcome t={t} onStart={() => setView("pick")} onCheck={() => setView("check")} />
  else if (view === "pick") body = <Pick t={t} info={info} picked={picked} setPicked={setPicked} onBack={() => setView("welcome")}
                                         onAgain={() => loadInfo().catch(markLost)}
                                         onInstall={async () => {
                                           const r = await api("/api/start", { clients: [...picked] })
                                           if (!r.ok) return say(r.error.message)
                                           setView("progress")
                                         }} />
  else if (view === "check") body = <Health t={t} info={info} onBack={() => setView("welcome")}
                                            onFix={(apps) => { setPicked(p => new Set([...p, ...apps])); setView("pick") }} />
  else body = <Progressing t={t} label={label} friendlyError={friendlyError} lost={markLost} say={say}
                           onRetry={() => setView("pick")} onFinish={async () => { try { await api("/api/quit", {}) } catch { /* already gone */ } setView("bye") }} />

  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="mx-auto flex h-16 max-w-3xl items-center gap-3 px-4">
        <img src="/logo.svg" alt="" className="size-9 rounded-xl shadow-sm" />
        <span className="text-lg font-semibold tracking-tight">AgentCAD</span>
        <div className="flex-1" />
        <Button variant="ghost" className="h-10 gap-2 rounded-lg px-3 text-base text-muted-foreground" onClick={() => setLang(lang === "zh" ? "en" : "zh")}>
          <Languages className="size-5" />{t("other")}
        </Button>
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-12">
        <div className="rounded-2xl bg-card p-6 text-card-foreground shadow-sm ring-1 ring-foreground/10 sm:p-9" aria-live="polite">
          {info?.dry_run && !lost && view !== "bye" &&
            <div className="mb-5 rounded-xl bg-warning/12 px-4 py-2.5 text-sm font-medium text-warning">{t("demo")}</div>}
          {body}
        </div>
      </main>
      {toast && <div role="status" className="fixed bottom-7 left-1/2 z-40 -translate-x-1/2 rounded-full bg-foreground px-5 py-2.5 font-medium text-background shadow-lg animate-in fade-in slide-in-from-bottom-2">{toast}</div>}
    </div>
  )
}

type Tr = (k: string, v?: Record<string, unknown>) => string

function Welcome({ t, onStart, onCheck }: { t: Tr; onStart: () => void; onCheck: () => void }) {
  const tiles: [LucideIcon, string, string][] = [[MousePointerClick, "w1", "w1s"], [Wand2, "w2", "w2s"], [MessageSquareText, "w3", "w3s"]]
  return (
    <>
      <div className="grid place-items-center pt-2 text-center">
        <img src="/logo.svg" alt="" className="mb-5 size-24 rounded-3xl shadow-lg ring-1 ring-foreground/5" />
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{t("welcome")}</h1>
        <p className="mt-3 max-w-xl text-lg text-muted-foreground">{t("welcomeLead")}</p>
      </div>
      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        {tiles.map(([Icon, k, s], i) => (
          <div key={k} className="rounded-xl border bg-muted/40 p-4">
            <span className="mb-3 grid size-10 place-items-center rounded-lg bg-primary/10 text-primary"><Icon className="size-5" /></span>
            <div className="font-semibold">{i + 1}. {t(k)}</div>
            <div className="text-sm text-muted-foreground">{t(s)}</div>
          </div>
        ))}
      </div>
      <div className="mt-8 flex flex-wrap gap-3">
        <Big autoFocus className="flex-1 basis-60" onClick={onStart}>{t("start")}<ArrowRight /></Big>
        <Big variant="outline" onClick={onCheck}><Stethoscope />{t("checkBtn")}</Big>
      </div>
    </>
  )
}

function Pick({ t, info, picked, setPicked, onBack, onAgain, onInstall }: {
  t: Tr; info: Info; picked: Set<string>; setPicked: (p: Set<string>) => void; onBack: () => void; onAgain: () => void
  onInstall: () => void
}) {
  const none = !info.apps.some(a => a.found)
  const toggle = (id: string) => { const p = new Set(picked); if (p.has(id)) p.delete(id); else p.add(id); setPicked(p) }
  return (
    <>
      <Dots on={0} labels={[t("s1"), t("s2"), t("s3")]} />
      <h1 className="text-3xl font-semibold tracking-tight">{t("pickTitle")}</h1>
      <p className="mt-2 mb-6 text-lg text-muted-foreground">{t("pickLead")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {info.apps.map(a => {
          const on = picked.has(a.id)
          return (
            <button key={a.id} type="button" role="checkbox" aria-checked={on} onClick={() => toggle(a.id)}
                    className={cn("flex min-h-20 items-center gap-4 rounded-xl border-2 bg-card p-4 text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                                  on ? "border-primary bg-primary/5" : "hover:bg-muted/60")}>
              <span className="grid size-12 shrink-0 place-items-center rounded-xl text-lg font-bold text-white shadow-sm" style={{ background: COLORS[a.id] }}>{INITIALS[a.id]}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-lg font-semibold leading-tight">{a.label}</span>
                <span className={cn("mt-0.5 flex items-center gap-1.5 text-sm", a.found ? "font-medium text-success" : "text-muted-foreground")}>
                  <span className={cn("size-2 rounded-full", a.found ? "bg-success" : "bg-muted-foreground/40")} />{t(a.found ? "found" : "notFound")}
                </span>
              </span>
              <span className={cn("grid size-7 shrink-0 place-items-center rounded-full border-2 transition-colors", on ? "border-primary bg-primary text-primary-foreground" : "border-border")}>
                {on && <Check className="size-4" strokeWidth={3} />}
              </span>
            </button>
          )
        })}
      </div>
      {none && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl bg-warning/12 px-4 py-3">
          <span className="flex-1 basis-72">{t("noneFound")}</span>
          <Button variant="outline" className="h-10 gap-1.5 rounded-lg px-3.5" onClick={onAgain}><RotateCw />{t("lookAgain")}</Button>
        </div>
      )}
      <div className="mt-5 flex items-center gap-3 rounded-xl bg-muted/50 px-4 py-3">
        <FolderOpen className="size-6 shrink-0 text-primary" />
        <div className="min-w-0">
          <div className="text-sm text-muted-foreground">{t("folderTitle")}</div>
          <code className="font-mono text-sm font-medium break-all">{info.workspace}</code>
        </div>
      </div>
      <OtherApp t={t} />
      <div className="mt-8 flex flex-wrap gap-3">
        <Big variant="outline" onClick={onBack}>{t("back")}</Big>
        <Big className="flex-1 basis-60" disabled={!picked.size} onClick={onInstall}>{t(picked.size ? "install" : "pickOne")}<ArrowRight /></Big>
      </div>
    </>
  )
}

// Any other MCP app: the config to paste into its settings, fetched once when the section opens.
function OtherApp({ t }: { t: Tr }) {
  const [open, setOpen] = useState(false)
  const [cfg, setCfg] = useState<{ config?: unknown } | "failed" | null>(null)
  const text = cfg && cfg !== "failed" ? JSON.stringify(cfg.config, null, 2) : ""
  const onOpen = async (o: boolean) => {
    setOpen(o)
    if (!o) { if (cfg === "failed") setCfg(null); return }  // closing after a failure lets the next open try again
    if (cfg) return
    try { const r = await api("/api/generic"); setCfg(r && r.config ? r : "failed") } catch { setCfg("failed") }
  }
  return (
    <Collapsible open={open} onOpenChange={onOpen} className="mt-3 rounded-xl border">
      <CollapsibleTrigger className="flex min-h-12 w-full items-center gap-3 rounded-xl px-4 py-2 text-left outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50">
        <Plug className="size-5 shrink-0 text-muted-foreground" />
        <span className="flex-1 font-medium">{t("otherTitle")}</span>
        <ChevronDown className={cn("size-5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </CollapsibleTrigger>
      <CollapsibleContent className="px-4 pb-4">
        <p className="mb-3 text-muted-foreground">{t("otherLead")}</p>
        {cfg === "failed" ? <p className="text-destructive">{t("otherFailed")}</p>
          : !cfg ? <Loader2 className="size-5 animate-spin text-muted-foreground" />
          : (
            <div className="relative">
              <pre className="max-h-72 overflow-auto rounded-lg bg-muted p-4 pr-28 font-mono text-xs leading-relaxed">{text}</pre>
              <div className="absolute top-2 right-2"><CopyButton text={text} t={t} /></div>
            </div>
          )}
      </CollapsibleContent>
    </Collapsible>
  )
}

// The real steps take a second or two in all; reveal them one by one so the progress can be followed.
function Progressing({ t, label, friendlyError, lost, say, onRetry, onFinish }: {
  t: Tr; label: (id: string) => string; friendlyError: (code?: string, app?: string, path?: string) => string
  lost: () => void; say: (m: string) => void; onRetry: () => void; onFinish: () => void
}) {
  const [st, setSt] = useState<Wizard>({ phase: "running", steps: [], result: null, error: null })
  const [shown, setShown] = useState(0)
  const shownAt = useRef(Date.now())
  useEffect(() => {
    // one request at a time, so a late "running" reply never replaces "done"; stop once it has ended: the finished
    // page stays even if the wizard then exits, and the wizard may reach its idle exit
    let alive = true, id = 0
    const poll = async () => {
      let r: Wizard
      try { r = await api("/api/state") } catch { if (alive) lost(); return }
      if (!alive) return
      setSt(r)
      if (r.phase !== "done" && r.phase !== "error") id = window.setTimeout(poll, 250)
    }
    id = window.setTimeout(poll, 250)
    return () => { alive = false; clearTimeout(id) }
  }, [lost])
  const over = st.phase === "done" || st.phase === "error"
  const finished = over ? st.steps.length : st.steps.filter(s => s.state === "done" || s.state === "error").length
  useEffect(() => {
    if (shown >= finished) return
    const id = setTimeout(() => { setShown(n => n + 1); shownAt.current = Date.now() }, Math.max(0, 550 - (Date.now() - shownAt.current)))
    return () => clearTimeout(id)
  }, [shown, finished])
  const steps: Step[] = st.steps.map((s, i) => i < shown ? s : { ...s, state: i === shown && st.phase !== "ready" ? "run" : "wait" })
  const ended = over && shown >= st.steps.length

  const text = (s: Step): [StepState, string, string] => {
    const app = label(s.id)
    const name = s.id === "workspace" ? t("stWorkspace") : s.id === "autocad" ? t("stAutocad") : s.id === "shortcut" ? t("stShortcut") : t("stApp", { app })
    let sub = t("waiting"), state = s.state
    if (state === "run") sub = t("running")
    else if (state === "done" || state === "error") {
      const p = s.info?.path
      if (s.id === "workspace") sub = t("folderReady", { p })
      else if (s.id === "shortcut") { sub = state === "error" ? t("scFail") : (s.info.status || "").startsWith("would") ? t("scDemo") : t("scOk"); if (state === "error") state = "opt" }
      else if (s.id === "autocad") { sub = p ? t("acYes") : t("acNo"); if (!p) state = "opt" }
      else {
        const k = s.info.status || ""
        sub = state === "error" ? friendlyError(s.info.code, app, s.info.target) : k === "unchanged" ? t("already") : k.startsWith("would") ? t("wouldConnect") : t("connected")
      }
    }
    return [state, name, sub]
  }
  const list = <ul className="mt-6 grid gap-2">{steps.map(s => { const [state, name, sub] = text(s); return <StepRow key={s.id} state={state} title={name} sub={sub} /> })}</ul>

  if (!ended) {
    const n = steps.length || 1, pct = Math.round(100 * Math.min(shown, n) / n)
    return (
      <>
        <Dots on={1} labels={[t("s1"), t("s2"), t("s3")]} />
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">{t("working")}</h1>
          <span className="text-4xl font-bold text-primary tabular-nums">{pct}%</span>
        </div>
        <Progress value={pct} className="mt-4 h-3" aria-label={t("working")} />
        <p className="mt-3 min-h-7 text-lg text-muted-foreground">{steps[shown] ? text(steps[shown])[1] : t("almost")}</p>
        {list}
      </>
    )
  }
  const ok = st.phase === "done"
  const res = st.result || {}
  const good: { client: string }[] = (res.clients || []).filter((c: any) => c.status !== "error")
  const todo = good.map(c => t("restart_" + c.client.replace("-", "_")))
  if (good.some(c => c.client === "claude-code" || c.client === "codex")) todo.push(t("checkConn"))
  const share = async () => {
    const msg = t("shareText") + " " + REPO
    if (navigator.share) { try { await navigator.share({ title: "AgentCAD", text: msg, url: REPO }); return } catch (e) { if ((e as Error).name === "AbortError") return } }
    await copyText(msg); say(t("shared"))
  }
  return (
    <>
      {ok && <Confetti />}
      <Dots on={ok ? 3 : 1} labels={[t("s1"), t("s2"), t("s3")]} />
      <Verdict ok={ok} title={t(ok ? "doneTitle" : "errTitle")} lead={t(ok ? "doneLead" : "errLead")} />
      {!ok && list}
      {!ok && st.error && <p className="mt-4 rounded-xl bg-warning/12 px-4 py-3">{friendlyError(st.error.code)}</p>}
      {ok && res.shortcut && !/^(error|would)/.test(res.shortcut.status) && (
        <div className="flex items-center gap-4 rounded-xl bg-muted/50 px-4 py-3">
          <img src="/logo.svg" alt="" className="size-11 shrink-0 rounded-xl shadow-sm" /><div>{t("iconTip")}</div>
        </div>
      )}
      {todo.length > 0 && (
        <>
          <h2 className="mt-8 mb-3 text-xl font-semibold">{t("lastStep")}</h2>
          <ol className="grid gap-2">
            {[...todo, t("sayThis")].map((s, i) => (
              <li key={i} className="flex items-center gap-3 rounded-xl bg-muted/50 px-4 py-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-sm font-bold text-primary-foreground">{i + 1}</span>{s}
              </li>
            ))}
          </ol>
          <div className="mt-3 grid gap-2">
            {["p1", "p2", "p3"].map(k => (
              <div key={k} className="flex items-center gap-3 rounded-xl border border-dashed px-4 py-3 max-sm:flex-col max-sm:items-stretch">
                <q className="flex-1 text-base">{t(k)}</q><CopyButton text={t(k)} t={t} />
              </div>
            ))}
          </div>
        </>
      )}
      <div className="mt-8 flex flex-wrap gap-3">
        {!ok && <Big className="flex-1 basis-48" onClick={onRetry}><RotateCw />{t("retry")}</Big>}
        <Big variant="outline" onClick={async () => { const r = await api("/api/open-folder", {}); if (!r.ok) say(t("noFolder", { m: r.error.message })) }}><FolderOpen />{t("openFolder")}</Big>
        <Big variant="outline" onClick={share}><Share2 />{t("share")}</Big>
        <Big variant={ok ? "default" : "outline"} className={cn(ok && "flex-1 basis-40")} onClick={onFinish}>{t("finish")}</Big>
      </div>
      <Collapsible className="mt-6 text-sm text-muted-foreground">
        <CollapsibleTrigger className="group flex min-h-10 items-center gap-1.5 hover:text-foreground">
          <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />{t("details")}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs break-all whitespace-pre-wrap">{JSON.stringify(res && res.clients ? res : st, null, 1)}</pre>
        </CollapsibleContent>
      </Collapsible>
    </>
  )
}

// The health check: doctor's checks folded into a few rows a person can act on.
function Health({ t, info, onBack, onFix }: { t: Tr; info: Info; onBack: () => void; onFix: (apps: string[]) => void }) {
  const [r, setR] = useState<{ checks?: Check_[] } | "failed" | null>(null)
  const run = useCallback(async () => {
    setR(null)
    try { const x = await api("/api/doctor"); setR(Array.isArray(x?.checks) ? x : "failed") } catch { setR("failed") }
  }, [])
  useEffect(() => { run() }, [run])
  const again = <Big variant="outline" onClick={run}><RotateCw />{t("checkAgain")}</Big>
  const back = <Big variant="outline" onClick={onBack}>{t("back")}</Big>
  if (r === "failed") return <><Verdict ok={false} title={t("checkTitle")} lead={t("err_other")} /><div className="flex flex-wrap gap-3">{again}{back}</div></>
  if (!r) return (
    <>
      <h1 className="text-3xl font-semibold tracking-tight">{t("checkTitle")}</h1>
      <p className="mt-3 flex items-center gap-2 text-lg text-muted-foreground"><Loader2 className="size-5 animate-spin" />{t("checking")}</p>
    </>
  )
  const by = Object.fromEntries(r.checks!.map(c => [c.name, c]))
  const core = r.checks!.filter(c => c.required && c.name !== "Workspace")
  const ver = (by.AgentCAD?.detail || "").split(" ")[1] || ""
  const coreOk = core.every(c => c.status === "ok")
  type Row = { name: string; s: "ok" | "bad" | "opt" | "skip"; sub: string; app?: string }
  const rows: Row[] = [{ name: t("ckCore"), s: coreOk ? "ok" : "bad", sub: coreOk ? t("ckCoreOk", { v: ver }) : t("ckCoreBad") }]
  const ws = by.Workspace || {} as Check_
  rows.push({ name: t("ckFolder"), s: ws.status === "ok" ? "ok" : "bad", sub: ws.status === "ok" ? ws.detail || "" : t("ckFolderBad") })
  for (const a of info.apps) {
    const c = by[a.label + " config"] || { status: "skip" }
    rows.push({ name: t("ckApp", { app: a.label }), s: c.status === "ok" ? "ok" : c.status === "skip" ? "skip" : "bad",
                sub: c.status === "ok" ? t("ckAppOk") : c.status === "skip" ? t("ckAppSkip") : t("ckAppBad"), app: a.id })
  }
  const ac = by.AutoCAD || {} as Check_
  rows.push({ name: t("ckAc"), s: ac.status === "ok" ? "ok" : ac.status === "skip" ? "skip" : "opt",
              sub: ac.status === "ok" ? ac.detail || "" : ac.status === "skip" ? t("ckAcSkip") : t("ckAcBad") })
  const bad = rows.filter(x => x.s === "bad")
  const state: Record<Row["s"], StepState> = { ok: "done", bad: "error", opt: "opt", skip: "wait" }
  return (
    <>
      <Verdict ok={!bad.length} title={bad.length ? (bad.length === 1 ? t("oneBad") : t("someBad", { n: bad.length })) : t("allGood")} />
      <ul className="grid gap-2">{rows.map(x => <StepRow key={x.name} state={state[x.s]} title={x.name} sub={x.sub} />)}</ul>
      <div className="mt-8 flex flex-wrap gap-3">
        {bad.length > 0 && <Big className="flex-1 basis-48" onClick={() => onFix(bad.filter(x => x.app).map(x => x.app!))}>{t("fixIt")}<ArrowRight /></Big>}
        {again}{back}
      </div>
    </>
  )
}
