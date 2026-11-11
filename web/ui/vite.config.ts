/// <reference types="vitest/config" />
// Experiment Studio's window. Built into web/studio/app/, which the Python service serves at
// /studio/app/ and as the page at /. The pure modules in web/studio/*.js (model, compute,
// sequence, analytics, the Cesium and Three renderers) are imported from there, so the
// node tests in tests/web keep testing the code this bundle runs.
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const studio = fileURLToPath(new URL("../studio", import.meta.url));
const service = "http://127.0.0.1:8765";

export default defineConfig({
  base: "/studio/app/",
  plugins: [react(), tailwindcss()],
  resolve: { dedupe: ["react", "react-dom"] },
  server: {
    port: 5180,
    strictPort: true,
    fs: { allow: [fileURLToPath(new URL(".", import.meta.url)), studio] },
    // The service owns the data, the engine assets and the compute core.
    proxy: Object.fromEntries(
      ["/api", "/studio/vendor", "/studio/assets", "/studio/wasm"].map((path) => [path, { target: service }]),
    ),
  },
  build: {
    outDir: "../studio/app",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1200,
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    restoreMocks: true,
  },
});
