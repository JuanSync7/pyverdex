import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Defaults build straight into the FastAPI package so `pyverify serve` ships
// the UI at "/". The GitHub Pages workflow overrides VITE_BASE (e.g. /pyverify/)
// and VITE_OUT (dist) to build a static, backend-optional showcase.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: {
    outDir: process.env.VITE_OUT || "../src/pyverify/server/static",
    emptyOutDir: true,
  },
});
