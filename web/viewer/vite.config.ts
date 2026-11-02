import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The page talks to a running `agentcad viewer` (its /api, the wording in /friendly.js, the logo). In development
// Vite forwards those paths to it: AGENTCAD_VIEWER=http://localhost:<port>, by default the "agentcad-viewer" entry of
// .claude/launch.json, which serves this checkout's playground/.
const viewer = process.env.AGENTCAD_VIEWER || "http://localhost:8781"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: Object.fromEntries(["/api", "/friendly.js", "/logo.svg"].map((p) => [p, { target: viewer }])),
  },
})
