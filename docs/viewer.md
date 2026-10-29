# 实时查看器（viewer）

Agent 改图纸或零件时，人可以在浏览器里实时看到它在变。查看器只读工作区，不依赖是哪个 Agent 在改（Claude Code、
Codex、CLI、HTTP API 都一样），也不需要 Agent 配合。

## 启动

```bash
agentcad --root playground viewer            # http://127.0.0.1:8770/
agentcad --root playground viewer --port 9000
```

Windows 上是 `.venv\Scripts\agentcad.exe`。启动后打印一行 JSON（`{"ok": true, "viewer": "http://127.0.0.1:8770/", ...}`），
Ctrl+C 退出。只监听 `127.0.0.1`，并且只回应 Host 头是 `127.0.0.1`、`localhost` 或 `[::1]` 的请求（其他返回 403 `HOST_NOT_ALLOWED`），挡住 DNS 重绑定：别的网站把自己的域名解析到 127.0.0.1 后，读不到图纸。页面不鉴权，所以 `--host` 设成非回环地址要同时加 `--allow-remote`（否则 `REMOTE_NOT_ALLOWED`，退出码 4），加了之后也不再检查 Host。`--host ::1` 用 IPv6 监听。三维零件要用 FreeCAD 出网格，
启动查看器的环境里同样要设 `AGENTCAD_FREECAD`（见 [part-3d.md](part-3d.md)）。端口被占用时返回 `PORT_IN_USE`，退出码 2。

### 在 Claude 桌面应用里打开

仓库带了 `.claude/launch.json`，里面的 `agentcad-viewer` 配置在应用内置浏览器里启动查看器（根目录 `playground`，
端口 8770）。它用的是 Windows venv 路径 `.venv/Scripts/python.exe`，macOS/Linux 改成 `.venv/bin/python`。
也可以自己在终端启动，再在内置浏览器里打开 `http://127.0.0.1:8770/`。

### Agent 怎么告诉用户去哪看

查看器运行时会写 `<root>/.agentcad/viewer.json`（地址和进程号），退出时删掉。这期间 `create_drawing` 的结果里多一个
`viewer_url`（如 `http://127.0.0.1:8770/#parts/plate.dxf`），Agent 可以把它转给用户。判断依据是向文件里的地址发一个 `GET /api/ping`，回答的查看器服务的正是这个根目录，
查看器崩溃留下的旧文件不会产生链接；文件里的地址不是回环地址（`127.0.0.1`、`localhost`、`::1`）时也不用，Runtime 不会去连别的主机。`create_drawing` 不加载 HTTP 服务器的代码。

## 页面

- **左栏**：根目录下所有 `.dxf` 和 `.FCStd`（跳过 `.agentcad`、`.git`、`.venv` 等目录，最多 2000 个）。别的图有改动时
  标一个点。
- **中间**：
  - 二维图纸：ezdxf 渲染的 SVG（和 `export_drawing(..., "svg")` 同一个渲染器），滚轮缩放、拖动平移、双击复位。
    顶部是图层开关（只列有实体的图层），隐藏图层不会改变取景。
  - 三维零件：three.js 显示 FreeCAD 三角化的实体和 B-rep 边，左键旋转、右键平移、滚轮缩放、双击复位。零件更新时
    保持视角，尺寸变化超过 20% 才重新取景。three.js 0.160.0 从 jsDelivr CDN 加载，import map 带 SRI 哈希（浏览器校验内容）；离线时退回到四视图 PNG 预览
    （同 `export_drawing(..., "png")` 的渲染器）。
  - **highlight changes**（默认开）：二维图把这一版改动的实体着色，新增绿色、修改橙色、其余灰色。
- **右栏**：
  - **时间线**：journal 的每条记录，最新的在上：工具、label、操作名（`add_line x3`）、增改删数量，失败的调用带错误码。
    点一条提交，就切到它产生的那一版（只读，顶部显示 "viewing an earlier version"）；点 **LIVE** 回到当前文件。
    文件在 AgentCAD 之外被改过时，LIVE 下面会提示。
  - **这一版的改动**：和 `get_diff` 相同的结果，对比的是这次提交开始时的版本。二维列出实体（id、类型、图层、tag、
    改了哪些字段）和图层增删；三维列出特征、参数（`width: 80 → 120`）和形状（体积、尺寸、孔）的变化。三维对比要
    起两次 FreeCAD，约几秒。
- **follow agent**（默认开）：别的图纸或零件一有改动，自动切过去，人不用跟着点。

## 工作方式

- **变更推送**：后台线程每 0.4 s 对每个图纸的文件、`journal.jsonl` 和 `head.json` 做一次 `stat`（不打开文件），
  有变化就发一个事件；每秒重新扫一次目录发现新文件。页面通过 Server-Sent Events（`/api/events`）收到事件后重新
  拉时间线和当前版本。断线后浏览器自动重连（`Last-Event-ID` 续上）。
- **版本按内容寻址**：每条成功提交的 journal 记录都有它写出的文件 sha256，每个检查点也记着自己内容的 sha256，
  所以磁盘上还存着的任何版本都能显示。要显示的版本先整体读进工作区外的缓存（系统临时目录下
  `agentcad-viewer/<root 的哈希>/<sha256>.dxf`），校验 sha256 后再解析或交给 FreeCAD；渲染结果按 sha 缓存，
  旧版本的响应可以被浏览器长期缓存。
- **只读**：查看器用 `read_only` 策略，不加写锁、不写 journal、不调用会写文件的工具（三维网格用 runner 新增的
  `mesh` 动作，在 FreeCAD 作业目录里完成，不经过 `export_drawing`）。唯一写到根目录下的是 `.agentcad/viewer.json`。
  测试 `test_viewer_never_writes_the_workspace` 检查请求所有版本前后工作区文件的哈希不变。
- **不会让 Agent 的提交失败**：Windows 上一个文件被任何进程打开着（查看器、杀毒软件、搜索索引、资源管理器预览），
  就不能被 `os.replace` 替换，加 `FILE_SHARE_DELETE` 共享也不行（实测）。所以存储层的原子替换（图纸、`committed.*`、
  `head.json`）遇到这种 `PermissionError` 会退避重试，最多 2 s（`store.replace_file`）；查看器读文件只要几毫秒。
  2 s 后还被占着：图纸还没替换就返回 `FILE_BUSY`（`retryable=true`，文件不变）；图纸已经替换、只是 `head.json` 写不进去，返回 `FILE_BUSY`（`partial_changes=true`、`details.state="applied_not_recorded"`），提示不要重做、调 `recover`，它会把这次提交补记进 journal（见 [architecture.md](architecture.md)）。
  反过来，查看器读到正在被替换的文件时也重试，不报错。测试 `test_commits_succeed_while_the_viewer_reads` 用三个线程
  不停读，同时提交 60 次，每次提交都必须成功。

## HTTP 接口

都是 `GET`，`path` 是相对根目录的路径，`v` 是版本的 sha256（省略或 `current` = 当前文件）。

| 路径 | 返回 |
|---|---|
| `/` | 页面 |
| `/api/drawings` | `{"drawings": [{"path", "kind": "drawing" \| "part"}], "last_event"}` |
| `/api/timeline?path=` | `{"current", "modified_outside_runtime", "records": [{"seq", "tool", "ok", "label", "ops", "changes", "error", "version", "available", "before"}]}` |
| `/api/svg?path=&v=&diff=1&hide=L1,L2` | 二维 SVG |
| `/api/layers?path=&v=` | 图层和实体数 |
| `/api/diff?path=&v=` | 这一版的改动（`before` = 起始版本） |
| `/api/mesh?path=&v=` | 三维：`{"positions", "indices", "edges"}` |
| `/api/png?path=&v=` | 三维：四视图 PNG |
| `/api/events` | SSE，`data: {"id", "drawing", "kind": "changed" \| "added" \| "removed"}` |

出错时返回和其他接口相同的错误信封：版本或文件不存在 404，路径在根目录外 403，缺 FreeCAD 503。
