# AgentCAD 在 U-C4N AutoCAD MCP benchmark 上的结果

日期：2026-10-30。**目前不能达到这套 benchmark 的第一名。** 在共同的旧版
v2 十项上，AgentCAD 完整通过 7 项；新版 v8 的 31 项中完整通过 9 项。
AutoCAD MCP Pro 的未修改参考实现已在本机复现 31/31。

## 比较的是哪张榜

[上游 benchmarks](https://github.com/U-C4N/Autocad-MCP/tree/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks)
有两种不同证据：

1. **源码审阅榜**：按功能、正确性、后端、工程出图、测试和安全六类人工评定，
   Pro 的记录为 93/100。这不是执行脚本能自动更新的排名；本次没有给自己编一个源码分。
2. **固定任务执行榜**：v2 有 10 项，v8 有 31 项。上游另外两家的公开结果来自
   v2；不能把这些分数直接排进 v8 的同一列。

本次使用上游提交 `58a05ddf`、evaluator `v8.1`，AgentCAD 产品代码为 `945e6c6`。
AgentCAD 适配器独立编写，调用真实 MCP stdio 服务；上游任务清单、权重、结果枚举和
评分函数直接复用。结果是本地评测，尚未经上游认证或收录。

## 结果

| 产品 | 共同 v2 十项 | v8 三十一项 | 证据 |
|---|---:|---:|---|
| AutoCAD MCP Pro 1.7.0 | 10/10，100 分 | 31/31，100 分 | 本机重跑未修改的参考实现 |
| AgentCAD | 7/10，70 分 | 9 项完整通过，30 分 | 本机真实 MCP 接口适配 |
| beiming183-cloud/AutoCAD-MCP | 5/10，50 分 | 未做同矩阵对比 | 上游已发表的旧版结果，本次未重跑 |
| puran-water/autocad-mcp | 4/10，45 分 | 未做同矩阵对比 | 上游已发表的旧版结果，本次未重跑 |

AgentCAD v8 详细状态：**9 pass、7 partial、10 unsupported、4 fail、1 not_run**。
`partial` 本次一律记零；已明确缺失的能力 `unsupported` 也留在分母。
`cancel_safety` 缺少同等可控的 worker 阻塞/事件轨迹适配，记 `not_run`，不算失败，
按上游规则排除在评分分母外，所以分数是 **9/30 = 30.0**。
若只看完整固定矩阵，完整通过比例是 **9/31 = 29.03%**。
这里既有实际几何执行，也有基于完整公开工具目录的能力缺口评估；没有把未执行的
领域工作流说成运行成功。取消安全仍属未验证能力。

| 任务 | AgentCAD | 观察到的行为或尚缺的验收条件 |
|---|---|---|
| core_geometry | pass | 3-4-5 直线和半径 2 的圆；接口和落盘文件共同核验 |
| modify_query | pass | 平移后起点 (5,2)，重新读文件确认 |
| layers_linetypes | pass | GEOMETRY 图层和 CENTER 线型落盘 |
| dimensions | pass | 真实 DIMENSION，有渲染块，尺寸为 50 |
| table_mleader | pass | 表格网格/文字与 LEADER/MTEXT 复合表示；上游参考也接受复合表示，不声称原生 TABLE/MLEADER |
| transactions | pass | 添加圆后原生 rollback，文件读回实体数为零 |
| preflight | unsupported | 缺少 ready/spec_hash 需求预检契约 |
| quality_refiner | partial | 能发现重复；缺少质量评分和自动修复循环 |
| dxf_roundtrip | pass | 导出 DXF，新的服务进程与独立 ezdxf 均读回一个实体 |
| auditable_delivery | partial | 提交哈希和文件复核已有；缺少原生交付 manifest |
| tool_discovery | unsupported | 有操作索引，缺少六个 AutoCAD 命令名的 top-3 搜索 |
| token_budget | fail | 24 个工具的目录约 6,292 token，高于 2,000 上限 |
| hatch_islands | partial | 外边界和岛均落盘；缺少面积测量及 ignore 样式编辑的 300/400 验收 |
| selection_filter | partial | crossing=2、图层过滤=1；缺少包含式 window 和多边形选择 |
| measure_from_handle | partial | 能 join 出含 bulge 的闭合曲线；缺少按 handle 返回精确面积 139.2699 的测量接口 |
| pid_roundtrip | unsupported | 有符号/管线；缺少图读取、悬空/置信度检查、线表与仪表索引 |
| page_setup_truth | partial | ANSI B PDF 为 432×279 mm；现有布局不能原生改成 A3 并报告 CTB 等变化 |
| mech_assembly | unsupported | 有标准件与标题栏；缺少零件视图、BOM/气泡关联审查及出图评分 |
| arch_roundtrip | unsupported | 缺少墙/洞口/房间面积识别与门窗房间表工作流 |
| takeoff_roundtrip | unsupported | 缺少管线/电缆提量和布置图长度推断 |
| understand_foreign | unsupported | 缺少单位推断、远处分簇和工艺服务分类 |
| requirements_roundtrip | pass | 原生 plate spec 建图；三个约束加一个孔数要求。孔移动 3 mm 后，仅 R3 在原进程和新进程中失败 |
| cancel_safety | not_run | 尚无与上游内部 held-worker 轨迹等价的公开接口测试 |
| qa_large_drawing | fail | 能找出 10,000 条线之后的反向重复；模型/纸空间三个施工线问题没有报出 |
| export_safety | unsupported | CSV 和 XLSX 导出均被 UNSUPPORTED_FORMAT 拒绝 |
| stale_preview | fail | dry_run 没有可携带回 apply 的版本/指纹；外部改色后，无条件 apply 仍平移直线 |
| revision_guarded_edit | unsupported | apply_operations 没有 expected_revision/指纹前置条件 |
| pid_file_roundtrip | unsupported | 缺少可跨进程复读的 P&ID 图、线号和仪表索引 |
| foreign_edit_verified | partial | 找到唯一错孔 H3，原生修改后直径/数量/孔距通过，独立对比只有一个实体改变；缺少修复时的指纹保护 |
| damaged_dxf_refusal | pass | 截断/非 DXF 都被明确拒绝；原文件字节和实体保持不变 |
| dimension_binding | fail | 能发现 D2 的文字覆盖 42/几何 40 冲突；D3 的 DIMLFAC=2 没有对物理几何报冲突，缺少需求到标注实体的绑定 |

## 能从结果得出什么

共同基础题已经优于另外两家的旧版公开记录，但落后于 Pro。AgentCAD 的持久化撤销、
跨会话 journal、CLI/HTTP 和 3D 等优势在本题集里基本不计分；这解释了它与
[既有同模型任务对比](comparison-autocad-mcp-pro.md)衡量的目标不同。

若目标是追平这张 v8 榜，建议按依赖关系推进，而不是增加工具数量：

1. **先补已接近的完整契约**：预览/修改前置指纹与版本保护，复用到外来图纸修复；
   交付时重新读取并产出哈希 manifest；给需求验收接上标注和实际几何，检出 DIMLFAC 失真。
   外部文件被改动可在摘要里检测到，但目前这不等于 apply 的乐观并发保护。
2. **补通用绘图闭环**：曲线/填充的解析面积、window/polygon 选择、已有页面设置修改、
   施工线规则、评分与自动修复循环、按需工具搜索、CSV/XLSX 安全导出。
   token 数是沿用上游 ratio/v1 的估计（字符数/4.19），不是实际模型计费 token。
3. **最后补领域引擎**：P&ID 语义图与读回、机械装配出图、建筑房间与明细表、工厂提量
   和外来图理解。这些需要真实的领域模型及独立验收，画出相似图形不能代替。

这是基线测量，本次未修改产品实现来追分。Pro 的大部分参考任务进程内调用后端，
AgentCAD 经 stdio、磁盘事务和进程启动，因此不从本次耗时推导谁更快。
也不能将一份本地适配报告宣称为九个项目均已同条件重测后的全球排名。

## 证据与复跑

- [适配器、方法及命令](../examples/autocad_benchmark/README.md)
- [AgentCAD 原始报告](../examples/autocad_benchmark/results/2026-10-30/agentcad.json)
- [Pro 本机参考报告](../examples/autocad_benchmark/results/2026-10-30/reference.json)
- [证据归档](../examples/autocad_benchmark/results/2026-10-30/evidence.zip)及
  [SHA256 清单](../examples/autocad_benchmark/results/2026-10-30/evidence-manifest.json)

归档保留实际 MCP 调用/返回、目录、绘图文件、参考产物和当时使用的适配器。
上游部分任务会覆盖先前返回的同名文件，参考组通过留存包装逐项立即复制产物，
再交原 runner 计算哈希；原参考任务的输入、验收、结果及计分不变。
上游 checkout 固定 SHA，产品所有 Python 源文件记录哈希；脚本拒绝覆盖已有结果。
补充的评分器测试用“接口声称已平移、文件未改变”、漏测要求、错误数量和读回旧数据
等反例，验证评分器会拒绝这些结果。
