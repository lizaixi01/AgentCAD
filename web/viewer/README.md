# Live viewer prototype (shadcn/ui)

A static prototype of the live viewer's next look: React, Tailwind CSS 4, shadcn/ui (Radix, "nova" preset) and
lucide icons. The data is the mock-up's (`src/data.ts`); nothing talks to the AgentCAD viewer API yet, and the
viewer the Python package serves (`src/agentcad/viewer_static/`) is unchanged.

```
npm install
npm run dev      # http://localhost:5173
npm run build    # type-checks, then writes dist/
```

Layout: three cards on a grey page. Left, the drawings (search, a kind filter, the folder they live in). Middle,
the open file: breadcrumb, the status of the latest run, the canvas with its zoom bar. Right, what happened
(activity timeline), the file's versions and its technical details. Theme: automatic, light or dark (the
header button); the dark theme is a slate grey, not black.
