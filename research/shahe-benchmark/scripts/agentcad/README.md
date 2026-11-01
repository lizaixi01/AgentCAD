# 沙河主楼：AgentCAD 独立实验 A

## 依据与不确定性

唯一使用以下指定来源，没有使用任何 SketchUp 模型、其截图或评价结果：

1. [主楼建筑历史（2021）](https://news.uestc.edu.cn/info/1087/29361.htm)：1957 年建成；2001–2002 年改造；历史尺寸 223×75 m。2020 年照片的原图直链经本机 HTTPS 和浏览器尝试失败（TLS / SSL protocol error），因此**没有看到该照片**。
2. [主楼修建过程（2016）](https://news.uestc.edu.cn/info/1087/29398.htm)：历史建筑五层、历史门廊八拱；2002 年完成改造。2002 年照片直链下载失败，因此**没有看到该照片**。
3. [校友会文章](https://alumni.uestc.edu.cn/xyzh/info/1091/2000.htm)：经浏览器看到文章中的 [500×333 鸟瞰照片](https://mmbiz.qpic.cn/mmbiz/JYhPemdYMoQHsymC3qZiarOiatibRCbclnE46J8CJWQDDUmnYAa0BwBoDcVUFFlqBG1VBwUcLnqmwZku0nxWbmeWw/0?wx_fmt=jpeg)。正面中央浅色、略突出，侧翼暖色，屋顶总体平缓。该图分辨率低，建筑边缘和后方不完整。照片仅用于观察，未保存在交付目录。

## 模型假设

所有数值为毫米。以历史 223 m 作为**暂定正面宽度**、75 m 作为**暂定最深范围**，两者的真实测量范围并未确认，不能视为测绘尺寸。主体深 18 m、两端向后各伸至 75 m 的 U 形平面完全是假设，鸟瞰图不能证明；层高 4 m、窗位置和尺寸、入口深度、楼檐也均为估计。正面采用五层重复窗和轻微突出的中央体块；入口暂用八个矩形门洞，历史八拱是否仍保留未经确认。后立面和侧立面缺少窗洞，模型无材质颜色、屋面设施或内部结构。模型适合比较粗略体量，不代表可靠的现状测绘。

## 重现（PowerShell，工作目录为本 worktree）

```powershell
$env:AGENTCAD_FREECAD = 'D:/Apps/MiKTeX/FreeCAD/1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311'
$env:AGENTCAD_SCRIPT_TIMEOUT = '300'
$r = (New-Item -ItemType Directory -Path 'playground/shahe-reproduction' -ErrorAction Stop).FullName
$env:SHAHE_AGENTCAD_OUT = $r
.\.venv\Scripts\agentcad.exe --root $r create shahe.FCStd --overwrite
.\.venv\Scripts\agentcad.exe --root $r --allow-scripts script shahe.FCStd --language freecad --file research/shahe-benchmark/scripts/agentcad/build.py
.\.venv\Scripts\agentcad.exe --root $r inspect shahe.FCStd
.\.venv\Scripts\agentcad.exe --root $r validate shahe.FCStd
.\.venv\Scripts\agentcad.exe --root $r export shahe.FCStd preview.png --format png --overwrite
.\.venv\Scripts\agentcad.exe --root $r export shahe.FCStd shahe.step --format step --overwrite
.\.venv\Scripts\agentcad.exe --root $r export shahe.FCStd shahe.stl --format stl --overwrite
.\.venv\Scripts\python.exe research/shahe-benchmark/scripts/agentcad/render.py
.\.venv\Scripts\python.exe research/shahe-benchmark/scripts/agentcad/check_stl.py
```

环境依赖本机 `.venv` 和 FreeCAD 1.1.4；路径请按安装位置调整。以上使用新的空输出目录以保护已有成果；修改输出位置的环境变量支持是在实验结束后加入的。脚本和本说明置于 `scripts/agentcad`。

## 过程与失败

- 2026-11-02 00:19（UTC+8）开始读取资料及检查工具，时间按首次记录估算，非精确计时。
- 最初 CLI 找不到 FreeCAD；`doctor` 指明其安装路径，设置 `AGENTCAD_FREECAD` 后创建成功。
- 一次将全部窗洞作为复合体执行布尔差集报 FreeCAD access violation，未保存；改成逐个差集。
- 原始窗数量逐个差集超过默认 60 秒超时，未保存；减少到正面窗并将脚本超时设为 300 秒。两次为修正设计主动中断，未保存。
- 尝试直接下载图片失败；经 Chrome 查看校友会鸟瞰图成功。未查看新闻站 2020 或 2002 年照片。
- 工具调用次数和 token 无可靠计数，均为 `null`。生成及验证结果见模型目录内的日志。
- 00:26:58 左右完成验证，距 00:19:22 的首次时间记录约 7 分 36 秒；起点并非任务收到时刻，故不是精确总耗时。成功脚本执行本身耗时 25.613 秒，工具调用含启动约 31.067 秒。

## 结果及检查

`shahe.FCStd` 是 FreeCAD 文件，`shahe.step` 和 `shahe.stl` 是交换格式；`preview.png` 是等轴测预览，`views.png` 是正、顶、右和等轴测四视图。可复现的脚本为 `build.py`。AgentCAD 检验结果为一个有效实体，外包尺寸 224000×78900×20300 mm（包括挑出的檐口和入口），STEP 重读匹配。警告：该实体是脚本生成的基底，不是逐特征可编辑的 PartDesign 特征树。STL 独立结构重读成功，3420 个三角形、无非有限坐标、包围盒一致；未验证网格流形性。上述检查只证明文件和几何有效，不证明与真实建筑吻合。
