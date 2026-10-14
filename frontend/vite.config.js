import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files go to ../static, which the Python server serves. `npm run dev` proxies the API to a running server.
export default defineConfig({
  plugins: [react()],
  build: { outDir: process.env.CF_OUT || "../static", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
});
