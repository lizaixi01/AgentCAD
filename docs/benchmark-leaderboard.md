# README benchmark 榜单的来源与边界

> 历史快照说明：以下保留最初发布 v8 图表时的测量与 `44aa822` 源码审查结论。
> 后续产品修复、`b4c0466` 的 31/31 复跑，以及对双方采用冻结细则的
> **AgentCAD 98 / Pro 96** 本地源码评估，另见[新评审记录](source-capability-review.md)。
> 新结果不改写以下历史分数，也不表示上游已收录 AgentCAD。

核对日期：2026-10-30。上游最新提交仍为
[`58a05dd`](https://github.com/U-C4N/Autocad-MCP/tree/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks)。
README 展示的是 **v8 固定任务执行榜**。AgentCAD 与 Pro 均为 31/31、100 分，
在这组已复跑的 v8 服务中并列最高；不是给 AgentCAD 的源码能力打了 100 分。

## 执行榜：可以复现的同口径比较

| 同组名次 | 服务 | 产品版本 | 矩阵 | 通过 | 分数 |
|---|---|---|---|---|---|
| 并列 1 | AgentCAD | `39fa4b5` | v8 / 31 项 | 31/31 | 100/100 |
| 并列 1 | AutoCAD MCP Pro | `58a05dd` | v8 / 31 项 | 31/31 | 100/100 |

AgentCAD 数据来自上游标准 runner 的[新复跑](../examples/autocad_benchmark/results/2026-10-30-v8/upstream/README.md)，
参考行来自保留的[同机参考复跑](../examples/autocad_benchmark/results/2026-10-30-v8/reference.json)。
Pro 自己[已发表的 v8 报告](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks/results/published/autocad-mcp-pro.json)
也为 31/31。AgentCAD 的上游 PR 尚未获收录；本文发布自有证据不依赖它先合并。

上游较早的两个竞争产品运行只覆盖 v2：beiming183 5/10、50 分，puran-water
4/10、45 分。没有把它们没运行的 21 项填成失败，也没有把 v2 与 v8 混排。
各报告的版本、路径、校验值及原始来源保存在 [data.json](assets/mcp-benchmark/data.json)。

两个服务发现模式都公布 3 个工具，使用相同 `ratio/v1` 估算时目录为 220 对
503 token，AgentCAD 少 56.3%。这排除服务 instructions，不是模型计费 token，
也不是同等完整工具功能量的比较。两者都低于 2,000，现有评分不会为更小的目录加分。
执行耗时包含不同的进程/磁盘/调用开销，不能用于宣称跨服务速度排名。

## 源码榜：93 分来自不同的评估

上游 [source_review.json](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks/source_review.json)
给 Pro 1.6.0 的源码能力自评为 93。该行评于 2026-09-24，其他行是 2026 年 7 月
快照；上游明确表示没有为 1.7.0 重评。这是截至核对日期的最新**已发表**源码分，
不是十月对所有产品的一次新评审。

| 上游源码榜名次 | 项目 | 已发表分数 |
|---|---|---:|
| 1 | U-C4N/Autocad-MCP | 93 |
| 2 | varavista/autocad-mcp | 84 |
| 3 | beiming183-cloud/AutoCAD-MCP | 83 |
| 4 | LokmenoWer/best-cad-mcp | 74 |
| 5 | AnCode666/multiCAD-mcp | 73 |
| 6 | puran-water/autocad-mcp | 70 |
| 7 | NCO-1986/AutoCAD_mcp | 68 |
| 8 | daobataotie/CAD-MCP | 35 |
| 9 | zh19980811/Easy-MCP-AutoCad | 30 |
| 未评分 | AgentCAD | — |

六类权重为功能覆盖 25、正确性与交付 20、后端与平台 15、工程生产 15、测试维护
15、安全运维 10。上游公开了类别权重、分数和叙述性依据，但没有逐项计分、扣分单位
或等级阈值。不能由这套公开资料唯一复算一个新的 AgentCAD 整数分，更不能把
执行测试的 100 换算为“超过源码 93”。数据文件保留 `agentcad_score: null`。

## 本次独立核对发现的差距

两项独立源码与行为审查固定在 AgentCAD `44aa8225ffbc573b15967cccbb962675e93f7665`。
该提交与被测 `39fa4b5` 的产品 `src/` 没有 Git 差异。本次核对不重评其他九个项目，
不为 AgentCAD 预设分数；当前不足以支持源码能力 94+ 的声明。

- **交付门槛尚未复用全部验收。** 默认 `deliver_drawing` 直接调用通用
  [validate_file](https://github.com/lizaixi01/AgentCAD/blob/44aa8225ffbc573b15967cccbb962675e93f7665/src/agentcad/quality.py#L33)，
  绕过 `validate_drawing` 恢复的已存规格要求，也未合并领域读回 critique。
  独立反例中，四个 Ø8 孔的板有一孔改为 Ø10：普通验证恢复 14 项要求、2 项失败，
  严格交付仍成功并记 97 分、0 项要求。另一反例把房间面积标签改成 999.00 m²，
  领域读回报 `ROOM_LABEL_MISMATCH`，严格交付仍成功并记 100 分。
  这两种闭环错误没有被现有固定 31 题覆盖，不能用 31/31 否认它们。
- **产物复核仍有限。** DXF 交付检查可解析，其他格式检查非空；没有全面的实体、
  属性和跨格式语义一致性检查。见[已公开交付契约](engineering-workflows.md#measure-verify-and-deliver)。
- **平台和维护证据尚不齐。** 有 Windows 上的 AutoCAD 2027、FreeCAD 和无头记录，
  但此提交没有跟踪的跨平台 CI 或依赖锁定文件。平台路径发现代码不等于 Linux/macOS
  已运行验证；跳过的可选测试也不计作通过。
- **默认工作区保护是优势，HTTP 边界仍有限。** 脚本和原始 CAD 命令默认关闭，
  路径默认限制在 root；但可修改图纸的
  [HTTP API](https://github.com/lizaixi01/AgentCAD/blob/44aa8225ffbc573b15967cccbb962675e93f7665/src/agentcad/http_api.py)
  接受外部 host 配置而没有认证门槛，不能把只读 viewer 的 Host/loopback 保护
  当作写入 API 已具有的保护。
- **能力优势不能自行换算成分数。** 参数化 FreeCAD 3D、持久撤销和尺寸重渲染有
  实现与证据；机械出图、建筑几何、ISO 配合与公差覆盖仍有范围限制。公开评分规则
  没有说明这些优势与不足如何逐分抵扣。

这些是后续提升的实际方向，不是要求上游认可一个预设的高分。本次修改只发布
已有执行证据、榜单和评分解释，没有声称已修复上述产品问题。

## 图表复现

发布 README 前正常合入主线 `dd600e1` 的三维预览与测量更新；集成后全套回归为
**439 passed、81 skipped（520 项）**。此前本任务在 `44aa822` 上为 435/74。
这些是仓库回归结果；图表的 v8 成绩仍引用原始 `39fa4b5` 产品测量，不把新的
三维代码说成已经完成另一轮 v8 测量。跳过项不视为通过。

图表只读取固定的两个 v8 报告，验证哈希、31 项任务集合、结果状态、分数和目录
估算器；源码评分数据不进入执行图。哈希仅允许 Git 的 LF/CRLF 换行转换。
没有修改历史图表、既有测量或任何评分规则。

```bash
python docs/assets/mcp-benchmark/make_charts.py
python docs/assets/mcp-benchmark/make_charts.py --check
```

渲染需要 matplotlib；与原有 Results 图表使用相同方式生成明暗 SVG。
