# 沙河主楼独立实验 B：原生 FreeCAD

## 输出与重现

`../../models/native/shahe-native-b.FCStd` 是可打开的 FreeCAD 原生文件；`preview-axon.png` 和 `preview-front.png` 为 FreeCAD 截图，`validation.json` 为建模过程的几何检查。模型由八个按材料分组的 Part 特征构成，所有构件保留为复合体；不是 BIM、施工或内部空间模型。文件使用毫米，建模代码的输入以米表示。

在 PowerShell 中从任意目录执行。先创建一个新的空输出目录，设置 `SHAHE_NATIVE_OUT` 为该目录的绝对路径，并按本机实际安装位置修改 Python 和脚本路径：

```powershell
& 'D:\Apps\MiKTeX\FreeCAD\1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe' -c "import FreeCAD, FreeCADGui; FreeCADGui.showMainWindow(); exec(compile(open(r'D:\Projects\AgentCAD-wt\shahe-benchmark\research\shahe-benchmark\scripts\native\build.FCMacro', encoding='utf-8').read(),'build.FCMacro','exec'))"
```

需要交互式桌面和此版本 FreeCAD。脚本末尾关闭它自己的窗口；输出目录由环境变量指定。不要复用已交付成果目录。

三角网格导出和独立重新读取：

```powershell
& 'D:\Apps\MiKTeX\FreeCAD\1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe' 'D:\Projects\AgentCAD-wt\shahe-benchmark\research\shahe-benchmark\scripts\native\export_mesh.py'
```

生成 `shahe-native-b.stl` 和 `mesh-validation.json`，STL 按毫米解释但格式本身不存单位及材质。重新读取结果为 21060 三角面、13564 点，包围盒 223600 × 78510 × 23600 mm。`isSolid()` 为 false：这是由许多独立且有交叠的装饰/墙体组成的视觉网格，未经布尔融合，不适合作为封闭单体或直接打印。首次验证尝试调用不可用的 `isManifold()` 报 AttributeError；删除该检查后导出及重读成功，未声称流形性。

## 证据和假设

- [成电新闻网建筑历史](https://news.uestc.edu.cn/info/1087/29361.htm)：1957 年建成，楼长 223 米、宽 75 米，门廊八个拱门；2001 年启动改造。文中包含 2020 年照片。
- [成电新闻网修建过程](https://news.uestc.edu.cn/info/1087/29398.htm)：正文在选址段落之后、工程修建段落之前写道“主楼本来打算建七层”，并称“最后只建了五层”。这是原建楼层数的记载；2002 年改造描述未明确重新核实现状楼层数。2002 年 2 月至 9 月改造，外墙和门窗等更新。文章附改造后照片。
- [校友会文章及鸟瞰照片](https://alumni.uestc.edu.cn/xyzh/info/1091/2000.htm)：记载中轴对称和八拱门；[鸟瞰照片直链](https://mmbiz.qpic.cn/mmbiz/JYhPemdYMoQHsymC3qZiarOiatibRCbclnE46J8CJWQDDUmnYAa0BwBoDcVUFFlqBG1VBwUcLnqmwZku0nxWbmeWw/0?wx_fmt=jpeg)提供浅色长立面、中央体量、窗列和周围体量的视觉线索。所查看的鸟瞰图 SHA-256 为 `48e839e260d5a0755baa54d1b3315fd0fb5dea67c0cab882a7f2a931a8df415e`；图片版权未确认，不随成果提供。

历史资料未明确 223 m 和 75 m 的测量范围。暂将 223 m 用作主体正面长度、75 m 用作主立面基准至侧翼末端的深度；中央向前突出 2.7 m，因此墙体总包围盒深 77.7 m。不能据此认定真实范围或尺寸。建筑高度、五层层高、中央突出量、窗宽/节距、坡屋顶、侧翼 U 形布局与深度、背面开窗和颜色都是估计；照片不足以确认这些几何。屋顶和后部尤其不可靠。门窗为贴于墙面的色块，拱门也是表面表现，并未在墙体中开孔；不含室内、结构和细部。窗列数量和门廊比例并非实测，不能视为精确复原。

## 运行记录

- 工作起始时间约 2026-11-02 00:19（UTC+08）；成果检查时间 00:22:15，总耗时约 3 分钟，起点由首次环境时间记录近似；此实验未用满 20 分钟预算。最终保留的 `validation.json` 记载脚本耗时 **13.567 秒**，其最后修改时间为 00:22:03，晚于最终 FCStd 的 00:22:00；这是最终交付文件对应的最佳可用计时证据。另一次 Python 运行的控制台输出为 8.925 秒，先前误将它作为最终文件的计时；两次进程可能有重叠，故不能仅凭时间戳证明验证文件与模型来自同一进程。计时包括模型创建、保存、截图及形状检查，不是纯几何建模时间。
- 使用指定的三篇文章，没有搜索其他资料，也未读取 SketchUp、评估结果或 A 组文件；未使用 AgentCAD。
- 使用 web 工具读取三篇页面文字；校友会鸟瞰图通过 curl 获取并查看后删除。两张新闻网图片的直接 TLS 下载失败（`SEC_E_INVALID_TOKEN` / corrupted frame）；因此未能视觉核对这些图片，限制了现状辨识。
- `freecad.exe` 宏启动未在命令行提供可靠日志；随后以 FreeCAD 自带 Python 加载 FreeCADGui 重建，完成并输出 `MODEL_COMPLETE`。两次运行共用输出目录且可能重叠，最终文件被后续写入覆盖，故以保留的验证记录为准并保留上述归属限制。再次用 FreeCAD 自带 Python 独立打开 FCStd，8 个对象可读取，所有对象的 Shape.isValid() 为 true。分别有 4、2、10、4、472、1024、8、11 个实体。验证仅证明文件可读和构件形状有效，不证明尺寸或建筑相似性，也不意味着复合体之间不存在交叠。
- 自检了两张渲染图；正面截图较小且有视角偏转，优先使用轴测图查看。墙体包围盒 223000 × 77700 × 21800 mm；屋顶最高点不包含在该墙体包围盒中。更多机器可读结果见 validation.json。
- 工具调用次数、token 用量不可可靠测量：`null`。未提交或推送。

可移植复现：设置 `SHAHE_NATIVE_OUT` 为新的空输出目录，并将命令中的 FreeCAD Python 路径和宏路径替换为本机路径。环境变量选项在原实验完成后加入，仅改变输出目录，不改变几何。
