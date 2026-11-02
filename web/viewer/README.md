# Live viewer on shadcn/ui

The page `agentcad viewer` serves: React, Tailwind CSS 4, shadcn/ui (Radix, "nova" preset), lucide icons and
three.js. It talks to the viewer's API (`agentcad/viewer.py`) and takes its wording from `viewer_static/friendly.js`
(both languages):

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
npm run build    # type-checks, then writes the page into src/agentcad/viewer_static/app/
```

The build is committed with the Python package, so installing AgentCAD needs no Node: after changing anything
here, run `npm run build` and commit `src/agentcad/viewer_static/app/` with the change. The viewer serves its
`index.html` at `/` and the rest at `/app/assets/`.

For `npm run dev`, start the viewer it talks to with the "agentcad-viewer" entry of `.claude/launch.json` (this
checkout's `playground/`), or set `AGENTCAD_VIEWER` to another one.
