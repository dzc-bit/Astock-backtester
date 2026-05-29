import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const stylesPathCandidates = [resolve(process.cwd(), "frontend/src/styles.css"), resolve(process.cwd(), "src/styles.css")];
const stylesPath = stylesPathCandidates.find((candidate) => existsSync(candidate));

if (!stylesPath) {
  throw new Error("Could not locate frontend/src/styles.css for workspace layout test.");
}

const styles = readFileSync(stylesPath, "utf8");

describe("workspace desktop layout", () => {
  it("lets the data center span the full workspace width", () => {
    expect(styles).toMatch(/\.data-center\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
  });
});
