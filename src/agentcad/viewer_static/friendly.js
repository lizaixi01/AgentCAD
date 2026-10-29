// Plain-language wording for the live viewer and its HTML snapshots (English and Chinese).
// The runtime writes data (op names and a few parameters, progress.py); this file turns it into sentences.
(function (global) {
  "use strict";
  const pick = () => {
    let saved = null;
    try { saved = localStorage.getItem("agentcad-lang"); } catch (e) { /* storage blocked */ }
    if (saved === "en" || saved === "zh") return saved;
    return /^zh\b/i.test(navigator.language || "") ? "zh" : "en";
  };

  const UI = {
    en: {
      title: "AgentCAD Live", files: "Your drawings", filesEmpty: "Nothing here yet.",
      waitingTitle: "Waiting for your drawing",
      waitingBody: "Ask your AI assistant to draw something. It will appear here and update as the work goes on.",
      idle: "Ready", idleHint: "Waiting for the next change",
      working: "Working", checking: "Checking", done: "Done", error: "Problem",
      stepOf: "Step {i} of {n}", checkingNow: "Checking the result…",
      doneAll: "All done!", doneSteps: "{n} steps finished", doneOne: "1 step finished",
      noProblems: "no problems found", problems: "{n} problems found", oneProblem: "1 problem found",
      notes: "{n} notes", errorUnchanged: "Nothing was changed. The assistant can try again.",
      activity: "What happened", activityEmpty: "Changes will show up here as they happen.",
      history: "Versions", now: "Now", latest: "Latest version", earlier: "You are looking at an earlier version",
      backToNow: "Back to now", notStored: "not stored any more", changedOutside: "Changed outside AgentCAD",
      highlight: "Highlight changes", compare: "Before / after", before: "Before", after: "After",
      noBefore: "There is no earlier version to compare with.",
      legendAdded: "new", legendModified: "changed", legendOther: "unchanged",
      share: "Save & share", saveHtml: "Web page (.html)", saveHtmlHint: "Picture and history in one file. Opens in any browser.",
      savePng: "Picture (.png)", savePngHint: "An image of what you see now.",
      saving: "Preparing…", saved: "Saved to your Downloads", saveFailed: "Could not save: {m}",
      follow: "Follow the assistant", followHint: "Switch to whichever drawing the assistant is changing",
      theme: "Theme", themeAuto: "Automatic", themeLight: "Light", themeDark: "Dark", language: "中文",
      layers: "Layers", details: "Technical details", connected: "Live", disconnected: "Reconnecting…",
      justNow: "just now", minAgo: "{n} min ago", hAgo: "{n} h ago",
      part: "3D part", drawing: "Drawing", loading: "Loading…", meshing: "Building the 3D view…",
      removed: "This file was removed.", zoomHint: "Scroll to zoom · drag to move · double-click to reset",
      orbitHint: "Drag to turn · right-drag to move · scroll to zoom",
      exportedFrom: "Saved from AgentCAD on {d}", shownVersion: "this picture",
      changesSummary: "{a} new · {m} changed · {d} removed", whatChanged: "What changed",
      historyTitle: "Change history", failed: "did not work", madeWith: "Made with AgentCAD",
      inFile: "in {f}",
    },
    zh: {
      title: "AgentCAD 实时查看", files: "我的图纸", filesEmpty: "这里还没有文件。",
      waitingTitle: "等待你的图纸",
      waitingBody: "让 AI 助手画点什么。图纸会出现在这里，并随着工作进行实时更新。",
      idle: "就绪", idleHint: "等待下一次修改",
      working: "进行中", checking: "检查中", done: "完成", error: "出了问题",
      stepOf: "第 {i} 步，共 {n} 步", checkingNow: "正在检查结果…",
      doneAll: "全部完成！", doneSteps: "完成了 {n} 步", doneOne: "完成了 1 步",
      noProblems: "没有发现问题", problems: "发现 {n} 个问题", oneProblem: "发现 1 个问题",
      notes: "{n} 条提示", errorUnchanged: "文件没有被修改，助手可以再试一次。",
      activity: "动态", activityEmpty: "修改会实时显示在这里。",
      history: "版本", now: "现在", latest: "最新版本", earlier: "你正在看一个较早的版本",
      backToNow: "回到最新", notStored: "已不再保存", changedOutside: "在 AgentCAD 之外被修改过",
      highlight: "标出修改", compare: "前后对比", before: "修改前", after: "修改后",
      noBefore: "没有更早的版本可以对比。",
      legendAdded: "新增", legendModified: "修改", legendOther: "未变",
      share: "保存和分享", saveHtml: "网页 (.html)", saveHtmlHint: "图和修改记录在一个文件里，任何浏览器都能打开。",
      savePng: "图片 (.png)", savePngHint: "当前看到的画面。",
      saving: "正在准备…", saved: "已保存到“下载”文件夹", saveFailed: "保存失败：{m}",
      follow: "跟随助手", followHint: "助手改哪张图就切到哪张",
      theme: "外观", themeAuto: "自动", themeLight: "浅色", themeDark: "深色", language: "English",
      layers: "图层", details: "技术细节", connected: "实时", disconnected: "正在重新连接…",
      justNow: "刚刚", minAgo: "{n} 分钟前", hAgo: "{n} 小时前",
      part: "三维零件", drawing: "图纸", loading: "加载中…", meshing: "正在生成三维视图…",
      removed: "这个文件已被删除。", zoomHint: "滚轮缩放 · 拖动平移 · 双击复位",
      orbitHint: "拖动旋转 · 右键拖动平移 · 滚轮缩放",
      exportedFrom: "由 AgentCAD 保存于 {d}", shownVersion: "本图",
      changesSummary: "新增 {a} · 修改 {m} · 删除 {d}", whatChanged: "改了什么",
      historyTitle: "修改记录", failed: "未成功", madeWith: "由 AgentCAD 生成",
      inFile: "（{f}）",
    },
  };

  // op -> [kind, english noun singular, plural, chinese noun] for "add"-like ops, or
  // op -> ["phrase", english past, english -ing, chinese] for the rest
  const NOUN = {
    add_line: ["add", "line", "lines", "直线"], add_circle: ["add", "circle", "circles", "圆"],
    add_arc: ["add", "arc", "arcs", "圆弧"], add_rectangle: ["add", "rectangle", "rectangles", "矩形"],
    add_polyline: ["add", "outline", "outlines", "多段线"], add_polygon: ["add", "polygon", "polygons", "多边形"],
    add_ellipse: ["add", "ellipse", "ellipses", "椭圆"], add_spline: ["add", "curve", "curves", "曲线"],
    add_point: ["add", "point", "points", "点"], add_hatch: ["add", "fill pattern", "fill patterns", "填充"],
    add_donut: ["add", "ring", "rings", "圆环"], add_ray: ["add", "guide line", "guide lines", "构造线"],
    add_xline: ["add", "guide line", "guide lines", "构造线"],
    add_text: ["add", "text", "texts", "文字"], add_mtext: ["add", "text", "texts", "文字"],
    add_linear_dim: ["add", "dimension", "dimensions", "尺寸标注"],
    add_angular_dim: ["add", "angle dimension", "angle dimensions", "角度标注"],
    add_diameter_dim: ["add", "diameter dimension", "diameter dimensions", "直径标注"],
    add_radius_dim: ["add", "radius dimension", "radius dimensions", "半径标注"],
    add_ordinate_dim: ["add", "dimension", "dimensions", "坐标标注"],
    add_leader: ["add", "note with arrow", "notes with arrows", "引线标注"],
    add_center_mark: ["add", "centre mark", "centre marks", "中心标记"], add_table: ["add", "table", "tables", "表格"],
    add_title_block: ["add", "title block", "title blocks", "标题栏"], add_viewport: ["add", "view", "views", "视口"],
    add_standard_hole: ["add", "hole", "holes", "孔"], add_standard_part: ["add", "standard part", "standard parts", "标准件"],
    add_pid_symbol: ["add", "P&ID symbol", "P&ID symbols", "工艺符号"],
    add_process_line: ["add", "process line", "process lines", "工艺管线"],
    add_feature_control_frame: ["add", "tolerance frame", "tolerance frames", "形位公差框"],
    add_datum_feature: ["add", "datum mark", "datum marks", "基准符号"],
    add_surface_finish: ["add", "surface finish mark", "surface finish marks", "粗糙度符号"],
    create_layer: ["add", "layer", "layers", "图层"], create_layout: ["add", "sheet", "sheets", "图纸布局"],
    create_text_style: ["add", "text style", "text styles", "文字样式"], define_block: ["add", "block", "blocks", "图块"],
    insert_block: ["add", "block", "blocks", "图块"], add_sketch: ["add", "sketch", "sketches", "草图"],
    hole: ["add", "hole", "holes", "孔"],
  };
  const PHRASE = {
    delete: ["Removed items", "removing items", "删除对象"], delete_layer: ["Removed a layer", "removing a layer", "删除图层"],
    modify_layer: ["Changed a layer", "changing a layer", "修改图层"], move: ["Moved items", "moving items", "移动对象"],
    copy: ["Copied items", "copying items", "复制对象"], rotate: ["Rotated items", "rotating items", "旋转对象"],
    scale: ["Resized items", "resizing items", "缩放对象"], mirror: ["Mirrored", "mirroring", "镜像"],
    offset: ["Made a parallel copy", "making a parallel copy", "偏移复制"], trim: ["Trimmed lines", "trimming lines", "修剪"],
    extend: ["Extended lines", "extending lines", "延伸"], break: ["Split a line", "splitting a line", "打断"],
    join: ["Joined lines", "joining lines", "合并"], explode: ["Broke up a group", "breaking up a group", "分解"],
    stretch: ["Stretched", "stretching", "拉伸图形"], modify: ["Changed items", "changing items", "修改对象"],
    set_properties: ["Changed colours or layers", "changing colours or layers", "修改属性"],
    draw_order: ["Changed what is on top", "changing what is on top", "调整显示顺序"],
    fillet: ["Rounded corners", "rounding corners", "倒圆角"], chamfer: ["Bevelled edges", "bevelling edges", "倒角"],
    array_rect: ["Copied into rows and columns", "copying into rows and columns", "矩形阵列"],
    array_polar: ["Copied around a circle", "copying around a circle", "环形阵列"],
    set_attributes: ["Filled in block fields", "filling in block fields", "填写属性"],
    set_annotation_scale: ["Set the annotation scale", "setting the annotation scale", "设置注释比例"],
    purge: ["Cleaned up unused items", "cleaning up unused items", "清理未使用项"],
    pad: ["Built up a solid", "building up a solid", "拉伸成实体"],
    pocket: ["Cut a pocket", "cutting a pocket", "挖槽"], revolve: ["Turned a profile into a solid", "turning a profile into a solid", "旋转成形"],
    groove: ["Cut a groove", "cutting a groove", "旋转切槽"], thickness: ["Hollowed it out", "hollowing it out", "抽壳"],
    linear_pattern: ["Repeated features in a row", "repeating features in a row", "线性阵列"],
    polar_pattern: ["Repeated features around a circle", "repeating features around a circle", "环形阵列"],
    loft: ["Blended between shapes", "blending between shapes", "放样"], sweep: ["Swept a profile along a path", "sweeping a profile along a path", "扫掠"],
    helix: ["Made a spiral", "making a spiral", "螺旋扫掠"], modify_feature: ["Changed a feature", "changing a feature", "修改特征"],
    delete_feature: ["Removed a feature", "removing a feature", "删除特征"],
    set_parameters: ["Set the sizes", "setting the sizes", "设置尺寸"],
  };
  const SOLID = { box: ["box", "长方体"], cylinder: ["cylinder", "圆柱"], cone: ["cone", "圆锥"], sphere: ["ball", "球"],
                  torus: ["ring", "圆环"], prism: ["prism", "棱柱"], wedge: ["wedge", "楔形"] };
  const TOOL = {
    create_drawing: ["Started a new {k}", "starting a new {k}", "新建{k}"],
    draw_from_spec: ["Drew it from the specification", "drawing it from the specification", "按规格绘图"],
    revise_drawing: ["Updated the design", "updating the design", "修改设计参数"],
    revise_from_document: ["Updated it from the document", "updating it from the document", "按文档更新"],
    rollback: ["Went back to an earlier version", "going back to an earlier version", "回到较早的版本"],
    recover: ["Repaired the file", "repairing the file", "修复文件"],
    import_drawing: ["Imported a DWG drawing", "importing a DWG drawing", "导入 DWG 图纸"],
    run_script: ["Made a custom edit", "making a custom edit", "执行自定义修改"],
    apply_constraints: ["Checked the geometry rules", "checking the geometry rules", "检查几何约束"],
    validate_drawing: ["Checked the drawing", "checking the drawing", "检查图纸"],
    apply_operations: ["Edited it", "editing", "修改"],
  };

  const num = (v) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v));
  const fill = (s, vars) => String(s).replace(/\{(\w+)\}/g, (_, k) => (vars && k in vars ? vars[k] : ""));

  function detail(b) {
    const d = [];
    if (b.op === "set_parameters" && b.params) {
      return Object.entries(b.params).slice(0, 4).map(([k, v]) => `${k} = ${num(v)}`).join(", ");
    }
    if (b.thread) d.push(b.thread);
    else if (b.size) d.push(b.size);
    if (b.diameter != null) d.push("Ø" + num(b.diameter));
    else if (b.radius != null && /circle|arc|hole|cylinder|sphere|fillet|primitive/.test(b.op)) {
      d.push(b.op === "fillet" ? "R" + num(b.radius) : "Ø" + num(b.radius * 2));
    }
    if (b.width != null && b.height != null && b.op !== "primitive") d.push(`${num(b.width)} × ${num(b.height)}`);
    if (b.length != null && /pad|linear_pattern/.test(b.op)) d.push(num(b.length));
    if (b.depth != null && /pocket|hole/.test(b.op)) d.push(num(b.depth));
    if (b.occurrences != null) d.push("× " + num(b.occurrences));
    if (b.rows != null && b.cols != null) d.push(`${num(b.rows)} × ${num(b.cols)}`);
    if (b.op === "array_polar" && b.count != null) d.push("× " + num(b.count));
    if (b.text) d.push(`“${String(b.text).slice(0, 24)}”`);
    if (b.op === "create_layer" && b.name) d.push(b.name);
    return d.join(" ");
  }

  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  // brief: {op, n?, ...params}; mode: "done" (Added 4 Ø8 circles) or "doing" (adding 4 Ø8 circles)
  function opText(b, lang, mode) {
    lang = lang || pick();
    const n = b.n || (b.op === "add_standard_hole" && b.count) || 1;
    const det = detail(b);
    if (b.op === "...") return lang === "zh" ? `还有 ${n} 步` : `and ${n} more steps`;
    if (b.op === "primitive") {
      const s = SOLID[b.kind] || [b.kind || "shape", b.kind || "形体"];
      if (lang === "zh") return (mode === "doing" ? "正在" : "") + `添加${n > 1 ? " " + n + " 个" : ""}${s[1]}${det ? " " + det : ""}`;
      return `${mode === "doing" ? "adding" : "Added"} ${n > 1 ? n + " " + s[0] + "s" : "a " + s[0]}${det ? " " + det : ""}`;
    }
    const noun = NOUN[b.op];
    if (noun) {
      if (lang === "zh") return (mode === "doing" ? "正在" : "") + `添加${n > 1 ? " " + n + " 个" : ""}${det ? " " + det + " " : ""}${noun[3]}`;
      const verb = mode === "doing" ? "adding" : "Added";
      const art = /^[aeiouAEIOU]/.test(det || noun[1]) ? "an" : "a";
      return `${verb} ${n > 1 ? n + " " : art + " "}${det ? det + " " : ""}${n > 1 ? noun[2] : noun[1]}`;
    }
    const ph = PHRASE[b.op];
    const times = n > 1 ? (lang === "zh" ? `（${n} 次）` : ` (×${n})`) : "";
    if (ph) {
      const d = det ? (b.op === "set_parameters" ? (lang === "zh" ? "：" : ": ") + det : ` (${det})`) : "";
      if (lang === "zh") return (mode === "doing" ? "正在" : "") + ph[2] + d + times;
      return (mode === "doing" ? ph[1] : ph[0]) + d + times;
    }
    const raw = String(b.op || "?").replace(/_/g, " ");
    return (mode === "doing" ? (lang === "zh" ? "正在执行 " : "doing: ") + raw : (lang === "zh" ? "执行了 " : "Did: ") + raw) + times;
  }

  function toolText(tool, kind, lang, mode) {
    lang = lang || pick();
    const t = TOOL[tool];
    const k = kind === "part" ? (lang === "zh" ? "零件" : "part") : (lang === "zh" ? "图纸" : "drawing");
    if (!t) return String(tool || "").replace(/_/g, " ");
    const s = lang === "zh" ? (mode === "doing" ? "正在" : "") + t[2] : mode === "doing" ? t[1] : t[0];
    return fill(s, { k });
  }

  // one sentence for a finished call (progress event "done"/"error", or a history record)
  function summary(ev, lang) {
    lang = lang || pick();
    const kind = /\.fcstd$/i.test(ev.drawing || ev.name || "") ? "part" : "drawing";
    let steps = ev.ops || ev.steps;
    // sketches are scaffolding for the 3D feature that follows: the feature tells the story
    if (steps && steps.some((s) => s.op !== "add_sketch")) {
      const merged = [], same = (a, b) => JSON.stringify({ ...a, n: 0 }) === JSON.stringify({ ...b, n: 0 });
      for (const s of steps.filter((x) => x.op !== "add_sketch")) {
        const last = merged[merged.length - 1];
        if (last && same(last, s)) last.n = (last.n || 1) + (s.n || 1); else merged.push({ ...s });
      }
      steps = merged;
    }
    if (steps && steps.length && ev.tool === "apply_operations") {
      const parts = steps.slice(0, 3).map((s, i) => {
        const t = opText(s, lang, "done");
        return i === 0 || lang === "zh" ? t : t.charAt(0).toLowerCase() + t.slice(1);
      });
      let s = parts.join(lang === "zh" ? "，" : ", ");
      if (steps.length > 3) s += lang === "zh" ? ` 等 ${steps.length} 项` : ` and ${steps.length - 3} more`;
      return s;
    }
    return toolText(ev.tool, kind, lang, "done");
  }

  function verdict(ev, lang) {
    lang = lang || pick();
    const T = UI[lang];
    if (ev.passed == null) return "";
    if (ev.passed && !ev.issues) return T.noProblems;
    if (ev.passed) return fill(T.notes, { n: ev.issues });
    return ev.issues === 1 ? T.oneProblem : fill(T.problems, { n: ev.issues || "" });
  }

  function t(key, vars, lang) { lang = lang || pick(); return fill((UI[lang] || UI.en)[key] ?? UI.en[key] ?? key, vars); }

  global.AgentCADFriendly = { pick, t, opText, toolText, summary, verdict, fill, UI };
})(typeof window !== "undefined" ? window : globalThis);
