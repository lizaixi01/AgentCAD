# iPhone 18 Pro Max：两种 CAD 建模方式

两份模型基于**同一个人制定的同一外观参数**，仅用来展示 AgentCAD 脚本接口和直接 FreeCAD 脚本两种生成路径，不是独立 agent、效率或准确率 benchmark。没有访问或转换任何参考三维模型。

## 模型与已知限制

- AgentCAD：[原始文件](models/agentcad/iphone18.FCStd)、[彩色展示副本](models/agentcad/agentcad-display.FCStd)、[STEP](models/agentcad/iphone18.step)、[STL](models/agentcad/iphone18.stl)。脚本通过 AgentCAD CLI 提交并验证；原始文件是单实体脚本基底，不是可编辑的逐特征设计树。
- 原生 FreeCAD：[原始文件](models/native/iphone18-native.FCStd)、[彩色展示副本](models/native/native-display.FCStd)、[STEP](models/native/iphone18-native.step)、[STL](models/native/iphone18-native.stl)。生成脚本直接调用 FreeCAD，不调用 AgentCAD。
- 两组使用共同展示脚本在副本上着色，未改变几何；正背和轴测预览在各组目录。酒红是近似配色。背面 PNG 旋转 180° 以将顶部朝上。
- [Apple 官方规格](https://support.apple.com/en-lamr/148591)公布机身宽 78.0、高 163.4、厚 8.75 mm。模型基本机身按此建模；包括示意按键与摄像头后的包围尺寸是 78.5 × 163.4 × 11.75 mm，不是苹果公布的整机包围尺寸。
- 外形参考 [Apple 官方产品图片](https://www.apple.com/newsroom/2026/09/apple-debuts-iphone-18-pro-and-iphone-18-pro-max/) 和 [外观说明](https://support.apple.com/en-my/guide/iphone/iphbr22k8rnysnm/27/ios/27)。摄像头、按钮、圆角、屏幕边界、开孔、配色均为目测近似；缺少内部结构、复杂镜头光学和微小细节，不适用于配件生产。

## 几何验证

两份 FCStd 和 STEP 用原生 FreeCAD 1.1.4 重新打开，均为一个有效实体，STEP 与原文件体积差小于 1e-4 mm³。两模型相互做双向实体差集，体积均为 0 mm³（具体值见 [comparison.json](comparison.json)）。由于设计参数共同制定，这是两份产物之间的一致性检查，不是相对于真实手机的精度测量。

## 重现

在独立工作树安装开发依赖，使用 **全新的空目录**，从仓库根目录运行；FreeCAD 路径按实际安装修改。两组都不应覆盖已交付模型。

```powershell
$fc = 'D:\Apps\MiKTeX\FreeCAD\1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311'
$env:AGENTCAD_FREECAD = $fc
$env:AGENTCAD_SCRIPT_TIMEOUT = '300'
$a = (New-Item -ItemType Directory -Path playground/iphone18-repro-a).FullName
$b = (New-Item -ItemType Directory -Path playground/iphone18-repro-b).FullName
.\.venv\Scripts\agentcad.exe --root $a create iphone18.FCStd
.\.venv\Scripts\agentcad.exe --root $a --allow-scripts script iphone18.FCStd --language freecad --file research/iphone18-comparison/scripts/agentcad.py
.\.venv\Scripts\agentcad.exe --root $a validate iphone18.FCStd
.\.venv\Scripts\agentcad.exe --root $a export iphone18.FCStd iphone18.step --format step
.\.venv\Scripts\agentcad.exe --root $a export iphone18.FCStd iphone18.stl --format stl
$env:IPHONE_NATIVE_OUT = $b
& "$fc\bin\python.exe" research/iphone18-comparison/scripts/native.py
& "$fc\bin\python.exe" research/iphone18-comparison/scripts/compare.py "$a\iphone18.FCStd" "$b\iphone18-native.FCStd" "$b\comparison.json"
& "$fc\bin\python.exe" research/iphone18-comparison/scripts/presentation.py "$a\iphone18.FCStd" $a ScriptSolid
& "$fc\bin\python.exe" research/iphone18-comparison/scripts/presentation.py "$b\iphone18-native.FCStd" $b Phone
```

展示脚本需要 GUI 和 Pillow；示例的 FreeCAD 发行版已包含 Pillow。`verify.py` 可在子目录名为 `agentcad`、`native` 的模型根目录上执行完整读回检查。AgentCAD 操作日志见 `logs/agentcad-journal.jsonl`。本次未记录可比较的总耗时、token 或工具调用数，不填估计值。
