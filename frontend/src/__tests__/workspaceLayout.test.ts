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

  it("keeps realtime market index quotes in a compact row instead of stacking full width", () => {
    expect(styles).toMatch(/\.market-news-layout\s*\{[^}]*grid-template-columns:\s*minmax\(620px,\s*1\.45fr\)\s*minmax\(360px,\s*0\.9fr\);/s);
    expect(styles).toMatch(/\.index-quote\s*\{\s*grid-column:\s*auto;\s*\}/s);
  });

  it("keeps the trades table inside the results overview height with its own scroll", () => {
    expect(styles).toMatch(/\.results-trades-grid\s*>\s*\.surface\s*\{[^}]*min-height:\s*0;/s);
    expect(styles).toMatch(/\.trades-surface\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s);
    expect(styles).toMatch(/\.trades-scroll\s*\{[^}]*flex:\s*1\s+1\s+0;[^}]*min-height:\s*0;[^}]*overflow:\s*auto;/s);
    expect(styles).not.toMatch(/\.trades-scroll\s*\{[^}]*min-height:\s*420px;/s);
  });
});
