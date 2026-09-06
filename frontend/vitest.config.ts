import react from "@vitejs/plugin-react";
import { realpathSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";
import { readPackageVersion } from "./appVersion";

const frontendRoot = realpathSync(fileURLToPath(new URL(".", import.meta.url)));

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(readPackageVersion(frontendRoot))
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/testSetup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.*", "src/testSetup.ts", "src/__tests__/**"]
    }
  }
});
