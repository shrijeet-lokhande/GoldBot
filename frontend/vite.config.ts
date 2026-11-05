import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

// In dev mode the Vite server proxies API + WebSocket traffic to the Python
// backend so the dashboard works with a single origin.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  server: {
    port: 5173,
    open: false,
    proxy: {
      "/api": {
        target: process.env.GOLDBOT_BACKEND_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: process.env.GOLDBOT_BACKEND_URL ?? "http://127.0.0.1:8000",
        ws: true,
      },
    },
  },
})
