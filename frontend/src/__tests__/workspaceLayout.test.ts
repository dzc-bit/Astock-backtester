import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const stylesPathCandidates = [resolve(process.cwd(), "frontend/src/styles.css"), resolve(process.cwd(), "src/styles.css")];
const stylesPath = stylesPathCandidates.find((candidate) => existsSync(candidate));

if (!stylesPath) {
  throw new Error("Could not locate frontend/src/styles.css for workspace layout test.");
}

const styles = readFileSync(stylesPath, "utf8");
const appPathCandidates = [resolve(process.cwd(), "frontend/src/App.tsx"), resolve(process.cwd(), "src/App.tsx")];
const appPath = appPathCandidates.find((candidate) => existsSync(candidate));

if (!appPath) {
  throw new Error("Could not locate frontend/src/App.tsx for workspace layout test.");
}

const appSource = readFileSync(appPath, "utf8");

describe("workspace desktop layout", () => {
  it("lets the data center span the full workspace width", () => {
    expect(styles).toMatch(/\.data-center\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;/s);
  });

  it("keeps the data center in a responsive single-column layout without desktop overflow", () => {
    expect(styles).toMatch(/\.data-center\s+\.table-wrap\s*\{[^}]*overflow-x:\s*hidden;/s);
    expect(styles).toMatch(/\.data-center\s+table\s*\{[^}]*min-width:\s*0;/s);
    expect(styles).toMatch(/\.data-center\s+td\s*\{[^}]*overflow-wrap:\s*anywhere;/s);
  });

  it("lets data-center status and source labels wrap inside narrow table cells", () => {
    expect(styles).toMatch(
      /\.data-center\s+\.health-pill\s*\{[^}]*box-sizing:\s*border-box;[^}]*max-width:\s*100%;[^}]*min-width:\s*0;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;/s
    );
    expect(styles).toMatch(/\.data-center\s+td:last-child\s+small\s*\{[^}]*max-width:\s*100%;[^}]*overflow-wrap:\s*anywhere;/s);
  });

  it("keeps CLS diagnostics scrollable within the fixed-height finance panel", () => {
    expect(styles).toMatch(
      /\.cls-finance-diagnostics\s*\{[^}]*max-height:\s*120px;[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain;/s
    );
  });

  it("keeps CLS actions compact with the detail button left and the external link right", () => {
    expect(styles).toMatch(
      /\.section-title\s*>\s*\.cls-finance-actions\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*auto;[^}]*grid-template-areas:[^}]*"detail open"[^}]*"source source"/s
    );
    expect(styles).toMatch(/\.cls-finance-detail-button\s*\{[^}]*grid-area:\s*detail;[^}]*min-height:\s*30px;/s);
    expect(styles).toMatch(/\.cls-finance-open-button\s*\{[^}]*grid-area:\s*open;/s);
  });

  it("keeps realtime market index quotes in a compact row instead of stacking full width", () => {
    expect(styles).toMatch(/\.market-news-layout,\s*\.market-insight-layout\s*\{[^}]*grid-template-columns:\s*minmax\(620px,\s*1\.45fr\)\s*minmax\(360px,\s*0\.9fr\);/s);
    expect(styles).toMatch(/\.index-quote\s*\{\s*grid-column:\s*auto;\s*\}/s);
  });

  it("aligns the realtime, CLS finance, news, and summary panels to the same desktop columns", () => {
    expect(styles).toMatch(
      /\.market-news-layout,\s*\.market-insight-layout\s*\{[^}]*grid-template-columns:\s*minmax\(620px,\s*1\.45fr\)\s*minmax\(360px,\s*0\.9fr\);[^}]*align-items:\s*start;/s
    );
    expect(styles).toMatch(/\.cls-finance-panel,\s*\.news-summary-panel\s*\{[^}]*height:\s*390px;[^}]*max-height:\s*390px;/s);
    expect(styles).not.toMatch(/\.market-insight-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.12fr\)\s*minmax\(340px,\s*0\.88fr\);/s);
  });

  it("keeps the trades table inside the results overview height with its own scroll", () => {
    expect(styles).toMatch(/\.results-trades-grid\s*>\s*\.surface\s*\{[^}]*min-height:\s*0;/s);
    expect(styles).toMatch(/\.trades-surface\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s);
    expect(styles).toMatch(/\.trades-scroll\s*\{[^}]*flex:\s*1\s+1\s+0;[^}]*min-height:\s*0;[^}]*overflow:\s*auto;/s);
    expect(styles).not.toMatch(/\.trades-scroll\s*\{[^}]*min-height:\s*420px;/s);
  });

  it("loads the chart-heavy results overview outside the initial application chunk", () => {
    expect(appSource).not.toContain('import { ResultsOverview } from "./components/ResultsOverview";');
    expect(appSource).toContain('lazy(() => import("./components/ResultsOverview")');
    expect(appSource).toContain("<Suspense fallback=");
  });
});
