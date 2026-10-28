# 试用沙盒

这个目录用来亲手试用 AgentCAD Runtime。里面的图纸不进 git（只有这份说明进）。

## 方式一：让 Claude 用（推荐）

先在仓库根目录生成 `.mcp.json`，把 AgentCAD 注册成 MCP 服务器，工作区就是这个 `playground/` 目录：

```powershell
.venv\Scripts\agentcad.exe --root playground mcp-config --write
```

macOS/Linux 用 `.venv/bin/agentcad`。`.mcp.json` 里是本机路径，不进 git。

1. 在 Claude 桌面应用里，对仓库目录新开一个 Code 会话（已经打开的会话不会加载新的 MCP 服务器）。
2. 第一次使用时，应用会询问是否启用项目里的 MCP 服务器 `agentcad`，选允许。
3. 直接用中文提要求，例如：
   - "画一块 200×100 的安装板，四角 R8，四个 Ø12 安装孔距边 15，中间一个 Ø40 孔，标好尺寸，保存为 plate.dxf"
   - "把 plate.dxf 的宽度改成 240，孔位跟着走，告诉我改了哪些实体"
   - "撤销上一步"
   - "给 plate.dxf 出一张 A3 图纸，1:2 视口，标题栏写图号 MP-240"
   - "检查 plate.dxf 有没有问题"

Claude 会调用 `read_drawing`、`apply_operations`、`validate_drawing`、`get_diff`、`rollback` 等工具。每次修改前都会自动建检查点，可以随时撤回。

## 方式二：自己敲命令

```powershell
.venv\Scripts\agentcad.exe --root playground create my.dxf --units mm
.venv\Scripts\agentcad.exe --root playground apply my.dxf --ops-file ops.json
.venv\Scripts\agentcad.exe --root playground validate my.dxf
.venv\Scripts\agentcad.exe --root playground export my.dxf my.svg --format svg
```

`ops.json` 是操作列表，全部操作见 `docs/operations.md`，一步一步的教程见 `docs/tutorial.md`。

## 看图

- 导出 SVG 后用浏览器打开（最快）。
- 装了 AutoCAD 的话，DXF 可以直接用 AutoCAD 打开。
