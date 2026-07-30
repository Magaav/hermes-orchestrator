import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), {
    name: "visao-build-contract",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "ui-build.json",
        source: JSON.stringify({ app: "visao-vendas", version: "mvp-v1", base: "/" }, null, 2) + "\n"
      });
    }
  }],
  server: {
    host: "127.0.0.1",
    port: 5182,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:18083" }
  },
  optimizeDeps: {
    exclude: ["@jsquash/avif"]
  },
  worker: {
    format: "es"
  },
  build: { outDir: "dist", sourcemap: false }
});
