# AgentCAD 与 AutoCAD MCP Pro：同题对比

本实验用同一版本的 Codex 分别调用两套 CAD MCP 服务。H1、H4、H5 的题目、底图生成器和评分器复用仓库里的既有难题实验；两边拿到逐字节相同的 DXF 底图。实验不使用或提交 Autodesk 样例图纸。

- H1：对已有安装板连续做五轮修改，第四轮撤回第二轮，其他修改和原有内容应保留。每轮启动全新的 Codex 与 MCP 进程。
- H4：整理图层，去掉重复和零长度对象，保留已有几何和文字。
- H5：为已有零件补充尺寸标注，保持图形不变。
- 两组使用相同任务文字、模型和推理强度，只在工具入门提示上分别说明两套服务的发现方式。禁止会话运行命令或调用其他插件。
- 每组每题计划重复三次；一对运行同时启动，不同对依次运行。计时因此包含同机并发竞争，只能描述本次条件。模型服务容量或网络中断造成的未完成运行单独记录，并可重跑整对。
- AgentCAD 使用独立工作区且关闭脚本。Pro 使用 ezdxf 后端、工作区白名单、按需工具搜索及五步无头 undo。主实验安装 Pro 默认依赖，未安装 Pillow / matplotlib，因此无头截图不可用；需要截图的补充对照须安装 `[pdf]` extra。H1 的每轮重启会清空 Pro 进程内状态。
- 每轮保存快照，调用已有的 ezdxf 评分器检查实际文件。H4 另将中心线的端点与底图比较；H1 只有五轮均通过才计整题通过。评分器与被测生成逻辑分离，但仍依赖同一个 DXF 库；它不是 AutoCAD 实机审阅。
- 运行状态区分完成、模型服务中断、其他未分类失败和违反工具限制。只有日志明确出现模型容量不足或等待网络，才归为模型服务中断。符合条件的中断配对两侧都排除并整体重跑，以免完成的一侧被重复计数；配对中有未分类失败时不自动重跑，该失败仍计入通过率分母且不计通过。违反工具限制的样本单独报告并排除，不完整配对也单独标记。`eligible_for_rate` 与 `counted_success` 分别标记分母和分子。任何配对未完整执行时，运行器返回非零状态并保留每一侧的错误。
- 记录整题耗时、CAD MCP 调用次数及模型输入/缓存/输出 token。事件中的非 ok 返回也被计数，但可能只是校验正常发现问题，不能直接当作工具故障率；不要把未缓存与已缓存的输入 token 直接当成相同费用。

## 运行

在独立 worktree 中安装 AgentCAD 的开发依赖，然后安装固定版本的 Pro 到忽略目录。要复测报告中的 AgentCAD 提交 `51333f9`，应新建该提交的隔离 worktree，把本实验目录从当前版本复制进去，并在该 worktree 安装 AgentCAD；直接在较新的主线上运行会测到新版本：

```powershell
git clone https://github.com/U-C4N/AutoCad-MCP.git playground/pro-engine
git -C playground/pro-engine checkout 58a05ddfc34a9832c626e82cd88ecdce8e16a62a
Push-Location playground/pro-engine
uv sync --locked
Pop-Location
```

选一个不存在或为空的输出目录。原始模型事件、底图、快照、进度和评分都保存在那里，脚本不会覆盖已有结果。每个任务对在两条运行都结束后写出评分；中断后仍可读取已完成的结果，未完成任务保留原状，需要使用新的输出目录重跑。

```powershell
.venv/Scripts/python.exe examples/trials/pro_comparison/run.py `
  --out D:/Projects/AgentCAD-wt/example-pro-comparison `
  --pro playground/pro-engine --reps 3

.venv/Scripts/python.exe examples/trials/pro_comparison/run.py `
  --out D:/Projects/AgentCAD-wt/example-pro-comparison `
  --pro playground/pro-engine --grade-only
```

补充测试独立调用 MCP：同一图纸上让批量操作的第二步失败；分别检查 Pro 的默认停止与显式回滚模式；重启服务后检查原生回滚；尝试读取工作区以外的文件。

```powershell
.venv/Scripts/python.exe examples/trials/pro_comparison/probes.py `
  --out D:/Projects/AgentCAD-wt/example-pro-probes `
  --pro playground/pro-engine
```

对 Pro 的工具目录做单次补充对照：先在 Pro 目录运行 `uv sync --locked --extra pdf` 启用截图，再分别用主运行器的搜索模式和下面的完整目录模式运行相同任务。每种模式只重复一次，结果只能作为配置敏感性的线索；主实验未安装此 extra。

```powershell
$env:AGENTCAD_COMPARE_FIXTURES = "D:/Projects/AgentCAD-wt/example-pro-comparison/fixtures"
.venv/Scripts/python.exe examples/trials/pro_comparison/full_control.py `
  --out D:/Projects/AgentCAD-wt/example-pro-full-catalogue `
  --pro playground/pro-engine --tasks H4 H5 --reps 1
Remove-Item Env:AGENTCAD_COMPARE_FIXTURES
```

当某一侧被模型服务容量等环境问题中断时，可保留原结果，用原始底图哈希和相同产品版本重跑整对。中断次数与有效结果分开报告：

```powershell
.venv/Scripts/python.exe examples/trials/pro_comparison/retry_pair.py `
  --source D:/Projects/AgentCAD-wt/example-pro-comparison `
  --out D:/Projects/AgentCAD-wt/example-pro-retry `
  --pro playground/pro-engine --task H1 --rep 3
```
