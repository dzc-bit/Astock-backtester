import react from "@vitejs/plugin-react";
import { realpathSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";

const frontendRoot = realpathSync(fileURLToPath(new URL(".", import.meta.url)));

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  server: {
    port: 1420,
    strictPort: false
  },
  build: {
    outDir: resolve(frontendRoot, "../dist"),
    emptyOutDir: true
  }
});
