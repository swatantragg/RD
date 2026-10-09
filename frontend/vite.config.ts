import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import pkg from "./package.json";

// `npm run dev` serves the UI on :5173 and proxies /api to the API on :8000.
export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: { port: 5173, proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500, sourcemap: false },
});
