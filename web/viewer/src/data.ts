// The prototype's data: the files, activity and versions shown in the design mock-up.

export type Kind = "drawing" | "part"
export type Format = "dxf" | "step" | "stl" | "fcstd"

export interface FileItem {
  name: string
  format: Format
  ago?: string
}

export const files: FileItem[] = [
  { name: "5810g_blue_hour.dxf", format: "dxf" },
  { name: "UESTC_Badge_20261103.step", format: "step", ago: "2 分钟前" },
  { name: "UESTC_Badge_20261103.stl", format: "stl", ago: "1 分钟前" },
  { name: "UESTC_Logo_20261103.dxf", format: "dxf", ago: "4 分钟前" },
  { name: "bearing_agent_1.FCStd", format: "fcstd" },
  { name: "bearing_agent_1.step", format: "step", ago: "46 分钟前" },
  { name: "bearing_agent_2.FCStd", format: "fcstd" },
  { name: "bearing_agent_2.step", format: "step", ago: "46 分钟前" },
  { name: "bearing_agent_3.FCStd", format: "fcstd" },
  { name: "bearing_agent_3.step", format: "step", ago: "46 分钟前" },
  { name: "bearing_direct_1.step", format: "step", ago: "46 分钟前" },
  { name: "bearing_direct_2.step", format: "step", ago: "46 分钟前" },
  { name: "bearing_direct_3.step", format: "step", ago: "46 分钟前" },
  { name: "sphinx3d.stl", format: "stl", ago: "46 分钟前" },
]

export const kindOf = (f: FileItem): Kind => (f.format === "dxf" ? "drawing" : "part")
export const kindLabel: Record<Kind, string> = { drawing: "图纸", part: "三维零件" }
export const formatLabel: Record<Format, string> = { dxf: "DXF", step: "STEP", stl: "STL", fcstd: "FCStd" }

export interface Activity {
  title: string
  file: string
  ago: string
  by?: { app: string; task: string }
  verdict?: string
  agent?: boolean
}

export const activity: Activity[] = [
  { title: "保存了新版本的零件", file: "UESTC_Badge_20261103.stl", ago: "1 分钟前" },
  { title: "保存了新版本的零件", file: "UESTC_Badge_20261103.step", ago: "2 分钟前" },
  { title: "保存了新版本的零件", file: "UESTC_Badge_20261103.step", ago: "2 分钟前" },
  { title: "保存了新版本的零件", file: "UESTC_Badge_20261103.step", ago: "2 分钟前" },
  { title: "添加 23 个填充，添加 40 个多段线", file: "UESTC_Logo_20261103.dxf", ago: "4 分钟前",
    by: { app: "Codex", task: "电子科大校徽" }, verdict: "没有发现问题", agent: true },
  { title: "添加 Ø100 圆", file: "UESTC_Logo_20261103.dxf", ago: "5 分钟前",
    by: { app: "Codex", task: "电子科大校徽" }, verdict: "没有发现问题", agent: true },
  { title: "保存了新版本的零件", file: "sphinx3d.stl", ago: "46 分钟前" },
]

export interface Version {
  seq: number | null
  title: string
  time?: string
}

export const versions: Version[] = [
  { seq: null, title: "最新版本" },
  { seq: 3, title: "保存了新版本的零件", time: "00:22" },
  { seq: 2, title: "保存了新版本的零件", time: "00:22" },
  { seq: 1, title: "保存了新版本的零件", time: "00:22" },
]

export const folder = "C:\\Users\\HUAWEI\\AgentCAD"
export const assistants = 2
