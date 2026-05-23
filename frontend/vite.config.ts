import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    port: 1420,
    strictPort: false
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true
  }
});
