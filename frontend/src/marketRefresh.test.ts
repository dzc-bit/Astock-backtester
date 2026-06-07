import { expect, it } from "vitest";
import { detectMarketSessionPhase, refreshIntervalForPhase } from "./marketRefresh";

it("detects weekend and lunch-break market phases in China time", () => {
  expect(detectMarketSessionPhase(new Date("2026-06-07T02:00:00Z"))).toBe("non_trading");
  expect(detectMarketSessionPhase(new Date("2026-06-05T04:00:00Z"))).toBe("lunch_break");
});

it("uses lower refresh pressure outside trading and after failures", () => {
  expect(refreshIntervalForPhase("trading")).toBe(60_000);
  expect(refreshIntervalForPhase("post_close")).toBe(300_000);
  expect(refreshIntervalForPhase("non_trading", true)).toBe(120_000);
});
