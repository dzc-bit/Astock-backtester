import react from "@vitejs/plugin-react";
import { realpathSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

const frontendRoot = realpathSync(fileURLToPath(new URL(".", import.meta.url)));

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/testSetup.ts"]
  }
});
