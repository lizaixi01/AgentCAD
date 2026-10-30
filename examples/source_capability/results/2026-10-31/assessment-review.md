本地独立源码能力复评已定稿：**AgentCAD 100/100，AutoCAD MCP Pro 93/100**。评审身份为 **independent AI reviewer, requested/published by AgentCAD**，与产品实施代理分离；这是 AgentCAD 委托并发布的 AI 评审，不是外部第三方认证。

被评产品固定为 [AgentCAD 66991092973496b148da45b1f847ddb1a8b4999d](https://github.com/lizaixi01/AgentCAD/tree/66991092973496b148da45b1f847ddb1a8b4999d) 与 [Pro 58a05ddfc34a9832c626e82cd88ecdce8e16a62a](https://github.com/U-C4N/Autocad-MCP/tree/58a05ddfc34a9832c626e82cd88ecdce8e16a62a)。日期为 2026-10-31（Asia/Shanghai）。后续主线合并和集成验证不替换本次固定测量。

双方沿用评分前冻结的[同一 20 项累计标准](https://github.com/lizaixi01/AgentCAD/blob/25abc96b9e39abe4e52464d3f8f00eba589759e5/docs/source-capability-rubric.md)，保留上游六类权重。100 表示这套有限范围的量表中 20 项都达到 5 分证据锚点，不表示具备所有 CAD 能力、任意输入永远正确或可以直接制造放行。没有把 v8 的 31/31、工具数量或测试数量换算为源码分数。

| 类别 | 权重 | AgentCAD | Pro 本轮复评 |
|---|---:|---:|---:|
| 功能覆盖 | 25 | 25 | 24 |
| 正确性与交付 | 20 | 20 | 17 |
| 后端与平台 | 15 | 15 | 15 |
| 工程生产 | 15 | 15 | 15 |
| 测试与维护 | 15 | 15 | 14 |
| 安全与运行 | 10 | 10 | 8 |
| 合计 | 100 | **100** | **93** |

| 逐项评分（每项 0–5） | AgentCAD | Pro |
|---|---:|---:|
| F1 几何与测量 | 5 | 5 |
| F2 编辑与身份 | 5 | 5 |
| F3 尺寸、样式与实际显示 | 5 | 4 |
| F4 组织与格式交换 | 5 | 5 |
| F5 领域工作流 | 5 | 5 |
| C1 事务与恢复 | 5 | 5 |
| C2 意图、实际几何与假值 | 5 | 2 |
| C3 交付与保存后读回 | 5 | 5 |
| C4 异常与不完整输入 | 5 | 5 |
| B1 后端契约 | 5 | 5 |
| B2 原生互操作 | 5 | 5 |
| B3 实际平台运行 | 5 | 5 |
| E1 标准数据来源 | 5 | 5 |
| E2 视图、标注与图纸 | 5 | 5 |
| E3 领域反馈闭环 | 5 | 5 |
| T1 行为回归 | 5 | 5 |
| T2 可复现性 | 5 | 5 |
| T3 持续验证与版本性能 | 5 | 4 |
| S1 默认权限与 HTTP | 5 | 3 |
| S2 锁、取消与恢复 | 5 | 5 |

Pro 本轮扣分均有固定源码和复现依据：

- **F3：4/5，扣 1。** Headless `dimstyle_modify` 修改样式后仍保留旧 DIMENSION 渲染块，明确返回 `rerender_required`；提示准确，但实际显示工作流尚未完成。[源码](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/backends/ezdxf_backend.py#L8821)
- **C2：2/5，扣 3。** 直径 6.4 的图在首次渲染前设置 DIMDEC=0，只渲染一次后可见文字是 6；内存和保存文件验证却都接受，并报告显示值 6.4、没有不匹配。DIMDEC=1、实际显示 6.4 的对照正常通过。源码以 measurement×DIMLFAC 推算显示值，未读实际文字，触发冻结标准的严重假通过上限 2。[源码](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/engineering/verification/binding.py#L370) 原件、返回与脚本见 `reviewer-rubric/pro-initial-precision-58a05dd.json`、`pro-initial-check-*`。这是首次渲染后的验证问题，与 F3 修改样式后的旧缓存问题分开，不重复扣分。相同 DXF 字节也曾使 AgentCAD 760a2c2 假通过；对 AgentCAD 同样实行上限，直到通用接口修复并独立重放通过。
- **T3：4/5，扣 1。** 已有完成的正确性 CI 和同机版本性能资料，但公开性能候选 efd33d0 比被评 58a05dd 早 17 个提交，其间 ezdxf、QA、交付和验证路径发生变化，未找到覆盖最终源码边界的重新测量。没有据此声称 Pro 更慢。[性能记录](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/benchmarks/results/published/perf-v1.6.0-vs-v1.7.0.json)
- **S1：3/5，扣 2。** 配置后的路径、认证和绑定保护有证据，但默认 `allowed_paths` 为空，原始命令/LISP 依赖拒绝列表；已定位 HTTP 测试没有实际请求拒绝及无写入后置条件的完整证明。未断言存在已利用漏洞。[默认配置](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/config.py#L55)、[安全边界](https://github.com/U-C4N/Autocad-MCP/blob/58a05ddfc34a9832c626e82cd88ecdce8e16a62a/security.py#L64)

AgentCAD 原 E1 缺口通过独立核查 GOST 12876-67 图 4/表 4 补齐，并将 M14 沉孔深度 14.6 改为 15；直径 24 和 ISO 273 中等间隙通孔 15.5 分别标明来源。E2 现在覆盖输入模型已给出的段长、总长、外径、通孔、孔数/孔径/PCD/间隔/起始角及视图、剖面、图框、BOM、气泡。两组不同模型的保存、原生读回和可见标注均已核对。此前归属空间、遗漏角色、细小几何、所有视图、显示解析、XRECORD 丢失和旧锁竞态等失败链保留；修复后的控制组与异常组复验是解除上限的依据，完整当前证据才支持最终 5 分。

本轮实际完成并核验的证据为：

- 本机启用真实 AutoCAD 和 FreeCAD：**815 passed、8 skipped、823 total，0 failed/errors，702.46 秒**；8 项仅因未安装 CadQuery 跳过。Windows / Linux 3.10 / Linux 3.12 / macOS CI 分别为 724/99、652/171、673/150、673/150（通过/跳过），五组测试 ID 均为相同 823 项。[CI](https://github.com/lizaixi01/AgentCAD/actions/runs/41101708770)
- CI 实际 checkout 是 `e26b82c13eae7eacfd3b0464abe3dfd05849acd0`；其完整 tree 与 6699109 一致。四份原始 artifact ZIP 的 SHA256 与 GitHub digest 一致，103 个解压文件逐字节核对。原始本机和 CI v8 均 **31/31**，失败门禁通过。
- 正式展示有 **40 次公开 Runtime 调用、7 项检查**；本评审独立渲染并逐张目视 7 份 PDF，确认两套机械样例、建筑、P&ID 和公差文字可读且未被页边裁切。移除缓存和 actual_measurement 后的两线角度，经实际 AutoCAD 独立再生为 36.87/143.13 度，与 atan2 几何一致。
- 同机、同解释器、同依赖的 69c1425→6699109 版本比较共 **24 次观测**，每个版本/规模各排除 1 次预热、计时 5 次，全部正确性通过。2000 条线总时间中位数 **2.823525→2.869212 秒**；10000 条线 **53.718280→48.622136 秒**。这些结果不支持全面提速或优于 Pro 的性能结论。

边界仍明确：非十进制度角度显示没有专门解析器时拒绝验证；通用两线角度锚点绑定尚未声明支持。图纸使用调用方布局与已给公称尺寸，不推断未给的公差、深度、表面或工艺。原生见证 PDF 是实际 AutoCAD 保存/重开/激活后的 DXF 经 AgentCAD 渲染，不是 Autodesk PDF 驱动输出；原生非激活视口需要记录中的激活步骤。机械/变体/公差交付质量分是 94，附两条 VIEWPORT 警告，建筑/P&ID 是 100；这些质量分不与本源码评分混为一谈。旧锁 marker 需要关闭旧程序后人工离线处理，信任执行脚本不是恶意代码隔离箱。

历史 [AgentCAD 98 / Pro 96 本地评审](https://github.com/lizaixi01/AgentCAD/blob/69c1425a2dd7465f6f8c092033447b608554a8a3/examples/source_capability/results/2026-10-30/assessment.json) 与其证据 ZIP 均未覆盖、哈希保持一致。上游原始 **93/100（v1.6.0，2026-09-24，自评）**另列保存；它与本轮 Pro 93 仅数值巧合，版本、评价者、逐分标准和扣分原因不同。本轮高分仅支持这两个固定版本在本地同尺评审中的比较，不能宣称官方或全球榜单第一。

完整逐项依据、扣分、固定源码链接和哈希索引在 `assessment.json`；算术、路径、旧档案与证据校验在 `assessment-validation.json`。文件路径以 ZIP 中的 `output/source-capability-100/` 为根；继承证据另从未改写的旧 ZIP 的 `output/source-capability/` 解析。失败记录、pending 草稿和复现原件均保留。
