// The live viewer's API (agentcad/viewer.py) and its wording (viewer_static/friendly.js, loaded by index.html).

export type Lang = "zh" | "en"

export interface ProgressEvent {
  run: string
  state: "working" | "checking" | "done" | "error"
  tool?: string
  drawing?: string
  ts: number
  step?: number
  total?: number
  op?: Record<string, unknown>
  passed?: boolean
  error?: { code?: string; message?: string }
  client?: string
  conversation?: string
  [k: string]: unknown
}

export interface Run {
  run: string
  last: ProgressEvent
  step?: ProgressEvent
  drawing?: string
  tool?: string
}

export interface Session { client?: string; label?: string; started?: number; last_seen?: number; drawing?: string }

export interface TimelineRecord {
  seq: number
  tool: string
  steps?: unknown
  ts?: string
  ok: boolean
  version?: string
  available?: boolean
  before?: string
  label?: string
  client?: string
  conversation?: string
  changes?: { added?: number; modified?: number; deleted?: number }
  error?: { code?: string; message?: string }
}

export interface Timeline { records: TimelineRecord[]; current: string; modified_outside_runtime?: boolean }

export interface Layer { name: string; entities: number; color?: string }

export interface ApiError { code?: string; message?: string }

interface Friendly {
  pick(): Lang
  t(key: string, vars?: Record<string, unknown>, lang?: Lang): string
  opText(op: Record<string, unknown>, lang: Lang, mode: "doing" | "done"): string
  toolText(tool: string | undefined, kind: "part" | "drawing", lang: Lang, mode: "doing" | "done"): string
  summary(ev: Record<string, unknown>, lang: Lang): string
  verdict(ev: Record<string, unknown>, lang: Lang): string
  UI: Record<Lang, Record<string, string>>
  PART: RegExp
}

declare global { interface Window { AgentCADFriendly: Friendly } }

export const F = () => window.AgentCADFriendly
export const isPart = (p?: string | null) => !!p && F().PART.test(p)
export const base = (p?: string | null) => String(p || "").split("/").pop() || ""
export const ext = (p?: string | null) => (String(p || "").split(".").pop() || "").toLowerCase()

export async function api<T = unknown>(path: string, q: Record<string, string | number> = {}): Promise<T> {
  const r = await fetch(path + "?" + new URLSearchParams(q as Record<string, string>))
  const ct = r.headers.get("content-type") || ""
  if (!r.ok) throw (ct.includes("json") ? (await r.json()).error : { message: r.statusText }) as ApiError
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>
}

// The page's only writes. The header proves the request comes from this page (viewer.py refuses it otherwise).
export function post(path: string, body: BodyInit, headers: Record<string, string> = {}) {
  return fetch(path, { method: "POST", body, headers: { "X-AgentCAD-Viewer": "1", ...headers } })
    .then((r) => r.json())
    .catch((e: Error) => ({ ok: false, error: { message: e.message } }))
}

export function ago(ts: number | undefined, lang: Lang) {
  if (!ts) return ""
  const s = Date.now() / 1000 - ts
  const t = F().t
  if (s < 60) return t("justNow", {}, lang)
  if (s < 3600) return t("minAgo", { n: Math.floor(s / 60) }, lang)
  if (s < 86400) return t("hAgo", { n: Math.floor(s / 3600) }, lang)
  return new Date(ts * 1000).toLocaleDateString(lang === "zh" ? "zh-CN" : undefined)
}

// a run still "working" after ten minutes crashed
export function stateOf(r?: Run): "idle" | ProgressEvent["state"] {
  if (!r) return "idle"
  const st = r.last.state
  return (st === "working" || st === "checking") && Date.now() / 1000 - r.last.ts > 600 ? "idle" : st
}

// why a file cannot be shown, in a sentence (the server's message names cache paths and parser details)
export function cannotShow(e: ApiError | undefined, lang: Lang) {
  const code = e?.code || ""
  return F().UI[lang]["show_" + code] ? F().t("show_" + code, {}, lang) : F().t("show_other", { c: code || e?.message || "" }, lang)
}
