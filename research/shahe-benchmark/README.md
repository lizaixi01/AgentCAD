# 沙河校区主楼：探索性建模与 benchmark 协议

本目录包含 AgentCAD 与原生 FreeCAD 两个概念模型、复现材料和探索性差异分析。没有独立参考真值，且运行未满足下述完整协议，不能据此判定两种方法的准确性或性能优劣。状态、结果和限制见 results.json 与 comparison.md。

## 可复现的环境检查

在独立工作树安装本仓库（见仓库 AGENTS.md），运行：

```powershell
.venv\Scripts\agentcad.exe --root playground doctor
.venv\Scripts\agentcad.exe --help
.venv\Scripts\python.exe -c "import importlib.util as u; print({x:bool(u.find_spec(x)) for x in ['cadquery','FreeCAD','trimesh','numpy']})"
```

2026-11-02 检查：AgentCAD 0.1.0、Python 3.11.16；doctor 报告 FreeCAD 1.1.4 已配置、AutoCAD 已配置。工作树 Python 未发现 CadQuery、FreeCAD 和 trimesh 模块；FreeCAD 独立运行环境尚未实测。doctor 成功不等于建模或导出成功。

## 后续严格实验的建议协议（本次未满足）

1. 固定目标为改造后现状，以同一份公开证据包（sources.md 中经过核验的照片和文本）提供给两组。记录证据抓取时间、文件散列、版权和缺失视角；冻结后不得向单组补充。历史资料只能标明时期使用。不要包含参考模型的几何、截图或衍生信息。
2. 使用两个独立、全新且无共享记忆的 Agent 会话，固定模型版本、推理配置、任务文字、资源和最大墙钟时间及 token 上限，开始前记录实际值。两组顺序随机，最好多次独立重复；单次结果不能支持总体优势。A 只能经 AgentCAD MCP/CLI 建模，可用官方脚本模式；B 直接用同版本 FreeCAD 或 CadQuery，不调用 AgentCAD。记录所有工具调用、失败、日志、版本、时间、token 用量和人工干预，无法计量则标 null。A 组脚本模式本身可使用原生脚本，应作为解释因果差异的限制。
3. 将参考文件放在建模会话无法访问的独立位置，由独立评估者记录下载来源、许可、散列、格式、单位、坐标系和缺失几何；许可不明时不入库、不重新分发。评估时锁定输出和评价代码，避免通过多轮反馈泄露参考信息。参考模型不等同工程真值。
4. 导出同类可解析三角网格并检查非空、有限坐标、连通性、法向和闭合性，保留原始模型。预先规定建筑范围与排除项。登记单位尺度下的包围盒；另用统一的、仅平移旋转和单一比例的对齐，禁止各轴独立拉伸，报告变换及配准残差。尺度归一化指标不能证明真实尺度准确。
5. 对闭合可信实体，在固定空间分辨率下测占据体素 IoU，报告体素尺寸并做分辨率敏感性检查；非闭合网格不强行计算体积 IoU。使用固定随机种子、面积加权等量采样计算双向表面 Chamfer 距离，声明平方与否及归一化方式。以相同正交相机、视向、画幅和分辨率计算正、背、左右、顶视的 silhouette IoU，记录遮挡及空掩膜处理。保留差异图。
6. 由与建模隔离的评估者按预先定义的结构清单检查主体、侧翼、层数、入口、屋顶及窗列；每项标证据、可见性和不确定性，避免在不可见处判错。报告各项及评估者一致性，不凭空汇总打分。
7. 报告完成状态、有效文件、耗时、token、调用及失败次数，区分测量、估计、未测和参考质量误差；未取得可靠数据时为 null，绝不补零。记录中断及恢复。两组均完成并采用相同规则后才进行比较。

## 后续执行门槛

如将来需要真实建筑精度评估，尚需取得可合法使用的独立真值、核实文件质量、收集侧后俯视证据并建立强隔离环境。不得将参考文件或其几何放入建模上下文。

## 评估脚本

`scripts/evaluation/evaluate.py` 接受两份三角网格，通过各自包围盒中心及最长边作统一比例归一化，不做旋转或配准；仅适用于已统一轴方向的模型。输出双向平均未平方表面 Chamfer、三个正交平面的轮廓 IoU 及差异图（灰色重叠、红色仅第一模型、蓝色仅第二模型）。相反方向的正交轮廓相同，故不虚报五个独立视图。结果仅表示两模型彼此差异，不代表相对于真实建筑的准确度。体积 IoU 尚未实现，值保持 null。网格闭合检测先合并重合顶点，不能替代自交或实体有效性检查。

示例（仅对可合法访问的网格执行）：

```powershell
uv venv .eval-venv
uv pip install --python .eval-venv\Scripts\python.exe numpy==2.2.6 scipy==1.15.3 pillow==11.3.0 trimesh==4.9.0
.eval-venv\Scripts\python.exe research\shahe-benchmark\scripts\evaluation\test_evaluate.py
.eval-venv\Scripts\python.exe research\shahe-benchmark\scripts\evaluation\evaluate.py <mesh1> <mesh2> <output-dir>
```

用户随后选择自行比较，不再要求取得 SketchUp 参考文件。缺少真值的绝对精度指标不能计算；A/B 相互比较只能展示差异。

## 已执行的检查

2026-11-02：在独立工作树执行 `.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=D:\Projects\AgentCAD-wt\shahe-benchmark-pytest-temp -q`，进程退出码 0，含可选依赖跳过项。评估脚本合成盒子测试通过；A 与 B 的建模脚本在新的空输出目录再次运行成功，A 返回有效实体、B 返回八个有效复合对象。复现不等于对实物精度的验证。
