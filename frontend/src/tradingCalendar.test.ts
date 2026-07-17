import { describe, expect, it } from "vitest";
import { isAShareTradingDay } from "./tradingCalendar";

describe("A-share trading calendar", () => {
  it.each([
    "2027-02-08",
    "2027-10-04",
    "2028-01-26",
    "2028-10-02"
  ])("excludes the %s market holiday", (date) => {
    expect(isAShareTradingDay(new Date(`${date}T00:00:00`))).toBe(false);
  });
});
