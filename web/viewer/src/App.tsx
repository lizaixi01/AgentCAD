import { useEffect, useMemo, useState } from "react"
import {
  Bot, Box, Check, ChevronDown, ChevronRight, Columns2, Copy, Cylinder, FileImage, FileCode2, FolderOpen, Globe,
  Maximize2, Monitor, Moon, MousePointer2, Move, PencilRuler, Rotate3d, RotateCcw, Search, Share2, ShieldCheck, Sun,
  Triangle, ZoomIn, ZoomOut,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Toggle } from "@/components/ui/toggle"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { BadgeModel } from "@/components/badge-model"
import {
  activity, assistants, files, folder, formatLabel, kindLabel, kindOf, versions, type FileItem, type Format, type Kind,
} from "@/data"

const FORMAT_ICON: Record<Format, { icon: LucideIcon; tone: string }> = {
  dxf: { icon: PencilRuler, tone: "bg-sky-500/10 text-sky-600 dark:text-sky-400" },
  step: { icon: Box, tone: "bg-violet-500/10 text-violet-600 dark:text-violet-400" },
  stl: { icon: Triangle, tone: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
  fcstd: { icon: Cylinder, tone: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
}

type Theme = "auto" | "light" | "dark"
const THEME: Record<Theme, { icon: LucideIcon; label: string; next: Theme }> = {
  auto: { icon: Monitor, label: "自动", next: "light" },
  light: { icon: Sun, label: "浅色", next: "dark" },
  dark: { icon: Moon, label: "深色", next: "auto" },
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("agentcad-theme") as Theme) || "auto")
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)")
    const apply = () => document.documentElement.classList.toggle("dark", theme === "dark" || (theme === "auto" && mq.matches))
    apply()
    localStorage.setItem("agentcad-theme", theme)
    mq.addEventListener("change", apply)
    return () => mq.removeEventListener("change", apply)
  }, [theme])
  return [theme, setTheme] as const
}

function Tip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

function CardHead({ title, count, children }: { title: string; count?: number; children?: React.ReactNode }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {count !== undefined && <span className="text-xs text-muted-foreground tabular-nums">{count}</span>}
      <div className="ml-auto flex items-center gap-1">{children}</div>
    </div>
  )
}

export default function App() {
  const [theme, setTheme] = useTheme()
  const [lang, setLang] = useState<"中文" | "English">("中文")
  const [query, setQuery] = useState("")
  const [kind, setKind] = useState<"all" | Kind>("all")
  const [selected, setSelected] = useState("UESTC_Badge_20261103.step")
  const [version, setVersion] = useState<number | null>(null)
  const [compare, setCompare] = useState(false)
  const [zoom, setZoom] = useState(1)

  const shown = useMemo(
    () => files.filter((f) => (kind === "all" || kindOf(f) === kind) && f.name.toLowerCase().includes(query.trim().toLowerCase())),
    [kind, query],
  )
  const file = files.find((f) => f.name === selected) as FileItem
  const ThemeIcon = THEME[theme].icon

  return (
    <TooltipProvider delayDuration={300}>
      <div className="grid h-svh grid-cols-[280px_minmax(0,1fr)_300px] grid-rows-[auto_minmax(0,1fr)] gap-3 bg-background p-3 pt-0 max-lg:grid-cols-[248px_minmax(0,1fr)_272px] max-md:flex max-md:h-auto max-md:min-h-svh max-md:flex-col">
        {/* header */}
        <header className="col-span-3 flex h-14 items-center gap-2 px-1">
          <div className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
              <PencilRuler className="size-4" />
            </div>
            <span className="text-[15px] font-semibold tracking-tight">AgentCAD</span>
          </div>
          <Badge variant="outline" className="ml-2 h-6 gap-1.5 rounded-full bg-card px-2.5 font-normal text-muted-foreground">
            <span className="size-1.5 rounded-full bg-success shadow-[0_0_0_3px] shadow-success/20" />
            {assistants} 个助手已连接
          </Badge>
          <div className="ml-auto flex items-center gap-1">
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setLang(lang === "中文" ? "English" : "中文")}>
              <Globe /> <span className="max-sm:hidden">{lang}</span>
            </Button>
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => setTheme(THEME[theme].next)}>
              <ThemeIcon /> <span className="max-sm:hidden">{THEME[theme].label}</span>
            </Button>
            <Separator orientation="vertical" className="mx-2 h-5!" />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm"><Share2 /> 保存和分享</Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem className="items-start gap-3 py-2">
                  <FileCode2 className="mt-0.5" />
                  <div><div className="font-medium">网页 (.html)</div><div className="text-xs text-muted-foreground">图和修改记录在一个文件里</div></div>
                </DropdownMenuItem>
                <DropdownMenuItem className="items-start gap-3 py-2">
                  <FileImage className="mt-0.5" />
                  <div><div className="font-medium">图片 (.png)</div><div className="text-xs text-muted-foreground">当前看到的画面</div></div>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* files */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-3">
          <CardHead title="我的图纸" count={files.length} />
          <div className="flex shrink-0 flex-col gap-2.5 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索图纸" className="h-8 pl-8" />
            </div>
            <Tabs value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
              <TabsList className="w-full">
                <TabsTrigger value="all">全部</TabsTrigger>
                <TabsTrigger value="part">三维零件</TabsTrigger>
                <TabsTrigger value="drawing">图纸</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <ScrollArea className="min-h-0 flex-1">
            <ul className="flex flex-col gap-0.5 px-2 pb-2">
              {shown.map((f) => {
                const { icon: Icon, tone } = FORMAT_ICON[f.format]
                const on = f.name === selected
                return (
                  <li key={f.name}>
                    <button onClick={() => { setSelected(f.name); setVersion(null) }}
                            className={cn("flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-accent",
                                          on && "bg-accent")}>
                      <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", tone)}><Icon className="size-4" /></span>
                      <span className="min-w-0">
                        <span className={cn("block truncate text-sm", on && "font-medium")}>{f.name}</span>
                        <span className="block text-xs text-muted-foreground">{kindLabel[kindOf(f)]}{f.ago && ` · ${f.ago}`}</span>
                      </span>
                    </button>
                  </li>
                )
              })}
              {!shown.length && <li className="px-2 py-6 text-center text-sm text-muted-foreground">没有匹配的图纸</li>}
            </ul>
          </ScrollArea>
          <div className="flex shrink-0 items-center gap-1 border-t px-4 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="text-xs text-muted-foreground">保存位置</div>
              <div className="truncate font-mono text-xs">{folder}</div>
            </div>
            <Tip label="打开文件夹"><Button variant="ghost" size="icon-sm"><FolderOpen /></Button></Tip>
            <Tip label="复制路径"><Button variant="ghost" size="icon-sm"><Copy /></Button></Tip>
          </div>
        </Card>

        {/* the open file */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-1">
          <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            <Breadcrumb className="min-w-0">
              <BreadcrumbList className="flex-nowrap">
                <BreadcrumbItem className="shrink-0 whitespace-nowrap max-sm:hidden"><BreadcrumbLink href="#">我的图纸</BreadcrumbLink></BreadcrumbItem>
                <BreadcrumbSeparator className="max-sm:hidden"><ChevronRight /></BreadcrumbSeparator>
                <BreadcrumbItem className="min-w-0"><BreadcrumbPage className="truncate font-semibold">{file.name}</BreadcrumbPage></BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
            <Badge variant="secondary" className="shrink-0 rounded-md font-normal">{kindLabel[kindOf(file)]} · {formatLabel[file.format]}</Badge>
            <Toggle variant="outline" size="sm" pressed={compare} onPressedChange={setCompare} className="ml-auto shrink-0">
              <Columns2 /> 前后对比
            </Toggle>
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-3 p-4 max-md:p-3">
            {/* what is happening now */}
            <div className="flex shrink-0 items-center gap-3 rounded-lg border border-success/30 bg-success/8 px-3.5 py-2.5">
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-success/15 text-success"><Check className="size-4" strokeWidth={2.5} /></span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-sm">
                  <span className="shrink-0 font-semibold">全部完成！</span>
                  <span className="truncate text-muted-foreground">保存了新版本的零件 <span className="font-mono text-xs">UESTC_Badge_20261103.stl</span></span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">1 分钟前</span>
                </div>
                <Progress value={100} className="mt-2 h-1 bg-success/15 *:data-[slot=progress-indicator]:bg-success" />
              </div>
            </div>

            {/* the canvas */}
            <div className="relative min-h-[320px] flex-1 overflow-hidden rounded-lg border bg-canvas max-md:h-[56vh] max-md:flex-none"
                 style={{ backgroundImage: "radial-gradient(var(--canvas-dot) 1px, transparent 1.2px)", backgroundSize: "16px 16px" }}>
              <div className={cn("absolute inset-0 grid place-items-center p-10", compare && "grid-cols-2 gap-0 p-6")}>
                {compare ? (
                  <>
                    <div className="relative h-full w-full border-r opacity-70"><span className="absolute top-0 left-0 rounded-md bg-card px-2 py-0.5 text-xs shadow-sm ring-1 ring-foreground/10">修改前</span><BadgeModel zoom={zoom * 0.9} /></div>
                    <div className="relative h-full w-full"><span className="absolute top-0 right-0 rounded-md bg-primary px-2 py-0.5 text-xs text-primary-foreground">修改后</span><BadgeModel zoom={zoom * 0.9} /></div>
                  </>
                ) : <div className="h-full w-full max-w-[560px]"><BadgeModel zoom={zoom} /></div>}
              </div>
              <div className="absolute bottom-4 left-4 flex gap-4 text-xs text-muted-foreground max-lg:hidden">
                <span className="flex items-center gap-1.5"><Rotate3d className="size-3.5" />拖动旋转</span>
                <span className="flex items-center gap-1.5"><Move className="size-3.5" />右键拖动平移</span>
                <span className="flex items-center gap-1.5"><MousePointer2 className="size-3.5" />滚轮缩放</span>
              </div>
              <div className="absolute right-3 bottom-3 flex items-center gap-0.5 rounded-lg bg-popover/95 p-1 shadow-md ring-1 ring-foreground/10 backdrop-blur">
                <Tip label="放大"><Button variant="ghost" size="icon-sm" onClick={() => setZoom((z) => Math.min(z * 1.2, 3))}><ZoomIn /></Button></Tip>
                <Tip label="缩小"><Button variant="ghost" size="icon-sm" onClick={() => setZoom((z) => Math.max(z / 1.2, 0.4))}><ZoomOut /></Button></Tip>
                <Tip label="重置视角"><Button variant="ghost" size="icon-sm" onClick={() => setZoom(1)}><RotateCcw /></Button></Tip>
                <Tip label="全屏"><Button variant="ghost" size="icon-sm"><Maximize2 /></Button></Tip>
                <Separator orientation="vertical" className="mx-1 h-4!" />
                <span className="w-11 text-center font-mono text-xs text-muted-foreground tabular-nums">{Math.round(zoom * 100)}%</span>
              </div>
            </div>
          </div>
        </Card>

        {/* what happened */}
        <Card className="min-h-0 gap-0 py-0 max-md:order-2">
          <CardHead title="动态" count={activity.length} />
          <ScrollArea className="min-h-0 flex-1">
            <ol className="px-2 py-1.5">
              {activity.map((a, i) => (
                <li key={i} className="relative flex gap-2.5 rounded-lg px-2 py-1.5 hover:bg-accent/60">
                  {i < activity.length - 1 && <span className="absolute top-7 bottom-[-6px] left-[17.5px] w-px bg-border" />}
                  <span className={cn("relative mt-0.5 grid size-5 shrink-0 place-items-center rounded-full",
                                      a.agent ? "bg-primary/12 text-primary" : "bg-success/15 text-success")}>
                    {a.agent ? <Bot className="size-3" /> : <Check className="size-3" strokeWidth={3} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <span className="flex-1 text-[13px] leading-5">{a.title}</span>
                      <span className="shrink-0 text-[11px] leading-5 text-muted-foreground">{a.ago}</span>
                    </div>
                    <div className="truncate font-mono text-[11px] leading-4 text-muted-foreground">{a.file}</div>
                    {a.by && (
                      <div className="mt-1 flex items-center gap-1 text-[11px] leading-4 text-muted-foreground">
                        <span className="font-medium text-primary">{a.by.app}</span>·<span className="truncate">{a.by.task}</span>
                        <span className="ml-auto flex shrink-0 items-center gap-1 text-success"><ShieldCheck className="size-3" />{a.verdict}</span>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </ScrollArea>

          <div className="shrink-0 border-t px-2 pt-2.5 pb-2">
            <div className="flex items-center gap-2 px-2 pb-1.5 text-xs text-muted-foreground">版本 <span className="tabular-nums">{versions.length}</span></div>
            <ul className="flex flex-col gap-0.5">
              {versions.map((v) => {
                const on = v.seq === version
                return (
                  <li key={v.seq ?? "now"}>
                    <button onClick={() => setVersion(v.seq)}
                            className={cn("flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-left text-[13px] transition-colors hover:bg-accent", on && "bg-accent")}>
                      <span className={cn("grid size-3.5 shrink-0 place-items-center rounded-full border-[1.5px]", on ? "border-primary" : "border-muted-foreground/40")}>
                        {on && <span className="size-1.5 rounded-full bg-primary" />}
                      </span>
                      <span className="w-8 shrink-0 font-semibold">{v.seq === null ? "现在" : `#${v.seq}`}</span>
                      <span className="min-w-0 flex-1 truncate text-muted-foreground">{v.title}</span>
                      {v.time && <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{v.time}</span>}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>

          <Collapsible defaultOpen className="shrink-0 border-t">
            <CollapsibleTrigger className="group flex h-10 w-full items-center px-4 text-xs text-muted-foreground hover:text-foreground">
              技术细节
              <ChevronDown className="ml-auto size-3.5 transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 px-4 pb-3 text-[11px]">
                <dt className="text-muted-foreground">文件</dt><dd className="truncate font-mono">{file.name}</dd>
                <dt className="text-muted-foreground">类型</dt><dd className="font-mono">{kindLabel[kindOf(file)]} · {formatLabel[file.format]}</dd>
                <dt className="text-muted-foreground">位置</dt><dd className="truncate font-mono">{folder}</dd>
                <dt className="text-muted-foreground">历史版本</dt><dd className="font-mono">{versions.length - 1} 个</dd>
              </dl>
            </CollapsibleContent>
          </Collapsible>
        </Card>
      </div>
    </TooltipProvider>
  )
}
