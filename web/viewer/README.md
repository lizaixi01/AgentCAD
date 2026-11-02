# Live viewer on shadcn/ui

The live viewer's next page: React, Tailwind CSS 4, shadcn/ui (Radix, "nova" preset), lucide icons and three.js.
It does what the packaged page (`src/agentcad/viewer_static/index.html`) does, against the same API
(`agentcad/viewer.py`) and with the same wording (`viewer_static/friendly.js`, both languages):

- the files, with search, a kind filter, a thumbnail on hover, "show in folder", and adding files (the + button,
  dragging them onto the page, or Ctrl+V)
- the open file: 3D parts in three.js (damped orbit, zoom toward the pointer, double-click to frame), drawings in
  model space (wheel zoom at the cursor, drag or middle-button pan, double-click to see it all), highlighted changes
  and their legend, layer toggles, before / after, full screen, the zoom bar
- the latest run's status and progress, the activity feed (click opens the file), "follow the assistant", the
  celebration when a run finishes
- the file's versions (an earlier one shows with a "back to now" banner) and its technical details
- who is connected, save as a web page or a picture, language, theme (automatic, light, dark)

Switching files or versions keeps the last picture on screen until the next is ready, then cross-fades; a part's
camera glides to the new framing.

```
npm install
npm run dev      # http://localhost:5173, forwarding /api to AGENTCAD_VIEWER (default http://localhost:8781)
npm run build    # type-checks, then writes dist/
```

Start the viewer it talks to with the "agentcad-viewer" entry of `.claude/launch.json` (this checkout's
`playground/`), or set `AGENTCAD_VIEWER` to another one. Serving `dist/` from the Python package is not done yet.
