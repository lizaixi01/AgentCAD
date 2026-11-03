// The live state of the workspace: its files, who is connected, what the runtime reported (progress.py), and the
// change stream (/api/events). Each run's events fold into one Run, most recent last.
import { useCallback, useEffect, useReducer, useRef, useState } from "react"
import { api, type ProgressEvent, type Run, type Session } from "@/lib/agentcad"

export interface Workspace {
  drawings: string[]
  root: string
  canAdd: boolean
  sessions: Session[] | null
  live: boolean
  runs: Run[]           // most recent last
  stamps: Map<string, number>  // bumps when a file changes, so its thumbnail reloads
}

// history: only a 3D part's version history moved (the viewer recorded a version it found): no jump, no new thumbnail
export type ChangeEvent = { drawing: string; kind: "changed" | "added" | "removed"; history?: boolean }

export function useWorkspace(handlers: { onActivity(ev: ProgressEvent, run: Run): void; onChange(ev: ChangeEvent): void }) {
  const runs = useRef(new Map<string, Run>())
  const [, bump] = useReducer((n: number) => n + 1, 0)
  const [files, setFiles] = useState<{ drawings: string[]; root: string; canAdd: boolean }>({ drawings: [], root: "", canAdd: false })
  const [sessions, setSessions] = useState<Session[] | null>(null)
  const [live, setLive] = useState(false)
  const stamps = useRef(new Map<string, number>())
  const h = useRef(handlers)
  h.current = handlers

  const add = (ev: ProgressEvent) => {
    if (!ev?.run) return null
    const m = runs.current
    const r: Run = m.get(ev.run) || { run: ev.run, last: ev }
    r.last = ev; r.drawing = ev.drawing || r.drawing; r.tool = ev.tool
    if (ev.state === "working" && ev.step) r.step = ev
    m.delete(ev.run); m.set(ev.run, r)
    while (m.size > 200) m.delete(m.keys().next().value as string)
    return r
  }

  const loadList = useCallback(async () => {
    const r = await api<{ drawings: { path: string }[]; root: string; can_add: boolean }>("/api/drawings")
    setFiles({ drawings: r.drawings.map((d) => d.path), root: r.root, canAdd: !!r.can_add })
    return r.drawings.map((d) => d.path)
  }, [])
  const loadSessions = useCallback(async () => {
    try { setSessions((await api<{ sessions: Session[] }>("/api/sessions")).sessions || []) } catch { /* the viewer is restarting */ }
  }, [])

  useEffect(() => {
    let es: EventSource | null = null, stop = false
    ;(async () => {
      try { for (const ev of (await api<{ events: ProgressEvent[] }>("/api/activity")).events) add(ev) } catch { /* older viewer */ }
      bump()
      await loadList()
      if (stop) return
      es = new EventSource("/api/events?progress=1")
      es.onopen = () => setLive(true)
      es.onerror = () => setLive(false)
      es.onmessage = (msg) => {
        const ev = JSON.parse(msg.data)
        if (ev.kind === "activity") {
          const r = add(ev.activity)
          if (r) { bump(); h.current.onActivity(ev.activity, r) }
          if (ev.activity?.state === "done") loadSessions()
          return
        }
        if (ev.history) { h.current.onChange(ev); return }
        stamps.current.set(ev.drawing, (stamps.current.get(ev.drawing) || 0) + 1)
        if (ev.kind !== "changed") loadList()
        bump()
        h.current.onChange(ev)
      }
    })()
    loadSessions()
    const s = setInterval(loadSessions, 5000)  // an assistant may connect or leave any time
    const tick = setInterval(bump, 30000)      // keeps "2 min ago" current
    return () => { stop = true; es?.close(); clearInterval(s); clearInterval(tick) }
  }, [loadList, loadSessions])

  const ws: Workspace = { ...files, sessions, live, runs: [...runs.current.values()], stamps: stamps.current }
  return { ws, loadList }
}
