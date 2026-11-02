import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The page talks to a running `agentcad viewer` (its /api, the wording in /friendly.js, the logo). In development
// Vite forwards those paths to it: AGENTCAD_VIEWER=http://localhost:<port>, by default the "agentcad-viewer" entry of
// .claude/launch.json, which serves this checkout's playground/.
const viewer = process.env.AGENTCAD_VIEWER || "http://localhost:8781"

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  // `npm run build` writes the page into the Python package, which serves it at / and its files at /app/
  // (agentcad/viewer.py): installing AgentCAD needs no Node.
  base: command === "build" ? "/app/" : "/",
  build: {
    outDir: path.resolve(__dirname, "../../src/agentcad/viewer_static/app"),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,  // one bundle with three.js, read from this computer
  },
  server: {
    proxy: Object.fromEntries(["/api", "/friendly.js", "/logo.svg"].map((p) => [p, { target: viewer }])),
  },
}))
