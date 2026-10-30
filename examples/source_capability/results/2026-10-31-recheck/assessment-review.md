本轮固定源码复评：**AgentCAD 100/100，AutoCAD MCP Pro 93/100**。采用此前冻结的同一六类权重、20 项累计锚点；这不是官方榜单、外部认证或所有 CAD 功能的完成百分比。31/31 v8 是单独的执行结果，没有换算为源码能力分。

评审身份：**independent AI reviewer, requested/published by AgentCAD**。本评审与产品实现代理分开，未编写产品代码，未启动 AutoCAD、FreeCAD 或 Claude；独立阅读固定源码、运行所列非原生反例、核对已完成原生输出，并逐张检查最终 PDF。大部分原生运行由项目实现方执行，此处明确区分运行者与评审者。

评估版本为 [AgentCAD 290ced3033f85e1fc97611cf1c920d922524bc3a](https://github.com/lizaixi01/AgentCAD/tree/290ced3033f85e1fc97611cf1c920d922524bc3a) 与 [Pro 58a05ddfc34a9832c626e82cd88ecdce8e16a62a](https://github.com/U-C4N/Autocad-MCP/tree/58a05ddfc34a9832c626e82cd88ecdce8e16a62a)。后续合并、集成测试或文档提交不得被重标为这次受测版本。[冻结评分标准](https://github.com/lizaixi01/AgentCAD/blob/25abc96b9e39abe4e52464d3f8f00eba589759e5/docs/source-capability-rubric.md) 的 Git/LF 内容 SHA256 仍为 `be562004ba7f25c0d131cdf690c9dc4844cd0df9dc3ede467ae2308420d1d52e`，不是 Windows CRLF 文件的原始哈希。

| 类别 | 权重 | AgentCAD | Pro |
| --- | ---: | ---: | ---: |
| F：CAD 功能覆盖 | 25 | 25 | 24 |
| C：正确性与交付 | 20 | 20 | 17 |
| B：后端与平台 | 15 | 15 | 15 |
| E：工程出图 | 15 | 15 | 15 |
| T：测试与维护 | 15 | 15 | 14 |
| S：安全与运行 | 10 | 10 | 8 |
| 合计 | 100 | **100** | **93** |

每项 0..5 的依据、扣分、固定源码链接、当前证据及带 archive 标识的继承证据均在 `assessment.json`。AgentCAD 的 20 项均达到本标准的累计 5 分证据门槛：可用实现、正常与失败边界、独立保存/重开或接口验证，以及适用的真实后端和不同于 benchmark 的结构化场景。没有因测试数量、功能数量或用户目标加分；已知范围限制也没有被自动当作满分理由。

**先前 6699109 的 100 已失效，原件不改写。** 后续发现全透明尺寸文字被认证为可见，以及科学计数法错误文本被放行；f1 的首次修复还遗漏实际渲染的父属性继承和零物理量科学格式。四种保存原件及其正常对照均在 290 上用相同字节独立复放：完全透明文字和科学假值明确拒绝，正确继承的文字既被接受，也实际出现在 SVG、PDF 和 viewer 输出中。此前的严重假通过归入 C2 并应用上限 2，修复且同输入复验后才解除；同一缺陷没有重复扣在 C3/E2。新的 100 是针对修复后固定版本及新证据的判断，不是恢复旧结论。

本轮重新执行 11 组此前独立反例，覆盖与 Pro 相同字节的初始 6.4/可见 6、显式尺寸要求、分数/后缀、公差文本、默认 DIMRND、角度精度、所属空间、所需角色、细微几何、坐标误差、重复直径、所有视图与 XRECORD 丢失。控制组接受、损坏组拒绝，源字节绑定和实际行为都有明确断言，未只使用进程 exit 0。669→290 的 17 个新增/改变文件和 63 个相同文件逐项追踪，全部 80 个源码/静态文件匹配固定 Git；改变的共享显示与渲染路径使用当前证据，未盲目继承旧图纸。

独立检查原生输出进一步确认：无 graphics/measurement 缓存的科学计数法尺寸由 AutoCAD 生成 `6.50E-03`；半透明 ByBlock 尺寸经过实际 DWG 保存/导入后仍可验证，随后对导入 DXF 做全透明篡改会拒绝。这里没有声称另行完成了全透明 DWG 往返。四个无缓存角度由原生生成 36.87/143.13 度，与独立几何计算一致。非零 alpha 的边界是可见输出，不是所有格式中间透明强度完全相等。

当前完整 Windows 回归为 **885 通过、8 跳过、0 失败，893 项**；8 项全部因为缺少 CadQuery，AutoCAD 与 FreeCAD 实际启用。四个已完成 CI lane 与本机测试 ID 完全相同：Windows 792/101、Linux 3.10 720/173、Linux 3.12 与 macOS 741/152（通过/跳过）。CI 实际 checkout 是合并提交 `884ac930e438570d69c3e4fa33cacfbbe64bf346`，整个 Git tree 与 290 相同。独立经 GitHub 插件读取的四份 ZIP 摘要匹配原件，103 个解压文件逐字节一致。当前本机和 CI 原版 v8 均为 **31/31**，失败门禁通过。[CI run 41114528669](https://github.com/lizaixi01/AgentCAD/actions/runs/41114528669)

另一次独立 169 项定向检查首次是 168 通过、1 失败：`test_demo_icon` 检查整个 desktop 文件中没有 `viewer`，临时路径 `reviewer-rubric-recheck` 的子串造成误报。产品和测试源码均未改，仅把该单例移到中性临时根再跑，1 通过。两份 JUnit/日志及解释均保留，不能写成首次全绿。f1 中断记录和旧失败也保留，未升级为完成的回归。

正式新出图有 **40 次公开 Runtime 调用、7 项检查、7 份逐张独立渲染和目视的 PDF**。两种机械规格包含提供的分段/总长度、内外径、孔数/孔径/PCD/间距/起始方向、视图/剖面、图框、BOM 和气泡；正常与原生见证图的关键文字清晰且未裁切。变体的 M14 简化名义符号明确标出混合 ISO/GOST 来源，Ø15.5、Ø24、深 15 可见。E1 沿用经源码/数据边界核实的来源证据；E2 使用新的实际渲染、原生往返、正常规格和反例证据。小型透明度探针中已有的打印字高警告如实记录，没有把它作为正式制造图的替代证据。

同机同依赖版本对照为基线 `69c1425a2dd7465f6f8c092033447b608554a8a3` 对 290。两种线数、每版每规模排除 1 次预热并计时 5 次，共 24 次观测全部正确性通过。总用时中位数为 2,000 线 **2.6341107→2.6250365 秒**，10,000 线 **46.0567481→45.7476885 秒**，比值约 0.9966 和 0.9933，近似不变。它不是与 Pro、原生 CAD、MCP 或模型时延的性能比较，不支持全面提速声明。

Pro 的本地扣分维持相同固定源码和同尺依据：

- **F3：4/5，扣 1。** headless `dimstyle_modify` 留下旧 DIMENSION 图形并明确返回 `rerender_required`，后续显示工作流尚未完成。
- **C2：2/5，扣 3。** 6.4 mm 圆第一次、仅一次按 DIMDEC=0 渲染后，实际 MTEXT 为 6，但普通及保存文件要求验证仍报告显示 6.4 并接受。DIMDEC=1/实际 6.4 对照通过。该初始渲染假通过与 F3 修改样式后的重绘缺口不同；相同字节也曾暴露 AgentCAD 的问题，双方适用相同上限。
- **T3：4/5，扣 1。** 已公开同机性能 head 为 efd33d0，距受测 58a05dd 还有 17 个改变源码的提交；未找到跨最后产品边界的同机性能重跑，不据此断言速度更慢。
- **S1：3/5，扣 2。** 默认空 `allowed_paths` 与原始命令/LISP 的 denylist 留有默认操作范围缺口；找到的 HTTP 测试没有达到真实请求拒绝及保存无写入结果的证据层级。没有声称已证明可利用漏洞。

这个 Pro 93 恰好与上游 v1.6.0 历史自评 93 相同，但版本、评审者、锚点和扣分理由不同；两者单独记录。更早 98/96 历史材料也不改写。

所有分数只覆盖说明的有用能力范围。模板由调用者安排位置，不推断未提供的孔深、公差、表面处理和工艺，不等于可直接投产的图纸认证。未解析单位的非十进制角度仍明确不可验证；一般两线角度的意图绑定不作支持声明。native witness PDF 是 AgentCAD 对真实 AutoCAD 保存/重开/激活 DXF 的渲染，不是 Autodesk PDF 驱动输出。可信脚本按操作者权限运行，旧锁 marker 需关闭旧写者后离线处理，不是敌对代码隔离。

证据根目录为 `output/source-capability-100/`。本次 `evidence_index` 只列新文件；`inherited_evidence`/`inherited_evidence_index` 通过 archive 字段分别解析两份不变的旧 ZIP。三个 ZIP 并列解压，保留 `output/source-capability/` 与 `output/source-capability-100/` 原目录；新包不覆盖旧 `reviewer-rubric/`。关键独立记录位于 `reviewer-rubric-recheck/` 的 `independent-validation-290ced3.json`、`final-run-validation-290ced3.json`、`native-display-validation-290ced3.json`、`ci-provenance-290ced3.json`、`showcase-performance-validation-290ced3.json` 和 `visual-review-290ced3.json`。
