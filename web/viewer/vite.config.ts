import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Two pages: index.html, the live viewer, and setup.html, the setup wizard (agentcad setup --gui). Each talks to the
// server that serves it (its /api, the logo; the viewer also the wording in /friendly.js). In development Vite
// forwards those paths to it: AGENTCAD_VIEWER=http://localhost:<port>, by default the "agentcad-viewer" entry of
// .claude/launch.json, which serves this checkout's playground/ (for setup.html, the "agentcad-setup-demo" entry).
const viewer = process.env.AGENTCAD_VIEWER || "http://localhost:8781"

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // `npm run build` writes the pages into the Python package, which serves each at / and their files at /app/
  // (agentcad/viewer.py, agentcad/setup_gui.py): installing AgentCAD needs no Node.
  base: command === "build" ? "/app/" : "/",
  build: {
    outDir: path.resolve(__dirname, "../../src/agentcad/viewer_static/app"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,  // one bundle with three.js, read from this computer
    rollupOptions: { input: { viewer: path.resolve(__dirname, "index.html"), setup: path.resolve(__dirname, "setup.html") } },
  },
  server: {
    proxy: Object.fromEntries(["/api", "/friendly.js", "/logo.svg"].map((p) => [p, { target: viewer }])),
  },
}))
