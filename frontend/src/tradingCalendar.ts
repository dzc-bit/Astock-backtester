type HolidayRange = readonly [start: string, end: string];

// Future ranges are maintained ahead of the annual exchange closure notice so
// date defaults do not silently treat every weekday as a trading day.
export const A_SHARE_HOLIDAY_RANGES: Readonly<Record<number, readonly HolidayRange[]>> = {
  2024: [
    ["2024-01-01", "2024-01-01"],
    ["2024-02-09", "2024-02-17"],
    ["2024-04-04", "2024-04-06"],
    ["2024-05-01", "2024-05-05"],
    ["2024-06-10", "2024-06-10"],
    ["2024-09-15", "2024-09-17"],
    ["2024-10-01", "2024-10-07"]
  ],
  2025: [
    ["2025-01-01", "2025-01-01"],
    ["2025-01-28", "2025-02-04"],
    ["2025-04-04", "2025-04-06"],
    ["2025-05-01", "2025-05-05"],
    ["2025-05-31", "2025-06-02"],
    ["2025-10-01", "2025-10-08"]
  ],
  2026: [
    ["2026-01-01", "2026-01-03"],
    ["2026-02-15", "2026-02-23"],
    ["2026-04-04", "2026-04-06"],
    ["2026-05-01", "2026-05-05"],
    ["2026-06-19", "2026-06-21"],
    ["2026-09-25", "2026-09-27"],
    ["2026-10-01", "2026-10-07"]
  ],
  2027: [
    ["2027-01-01", "2027-01-03"],
    ["2027-02-05", "2027-02-13"],
    ["2027-04-03", "2027-04-05"],
    ["2027-05-01", "2027-05-05"],
    ["2027-06-07", "2027-06-09"],
    ["2027-09-13", "2027-09-15"],
    ["2027-10-01", "2027-10-07"]
  ],
  2028: [
    ["2028-01-01", "2028-01-03"],
    ["2028-01-25", "2028-02-02"],
    ["2028-04-03", "2028-04-05"],
    ["2028-05-01", "2028-05-05"],
    ["2028-05-27", "2028-05-29"],
    ["2028-09-02", "2028-09-04"],
    ["2028-10-01", "2028-10-07"]
  ]
};

export function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isAShareTradingDay(date: Date): boolean {
  if (date.getDay() === 0 || date.getDay() === 6) {
    return false;
  }
  const text = formatLocalDate(date);
  return !(A_SHARE_HOLIDAY_RANGES[date.getFullYear()] ?? []).some(
    ([start, end]) => start <= text && text <= end
  );
}

export function previousAShareTradingDay(date: Date): Date {
  const previous = new Date(date);
  previous.setHours(0, 0, 0, 0);
  while (!isAShareTradingDay(previous)) {
    previous.setDate(previous.getDate() - 1);
  }
  return previous;
}

export function recentAShareTradingDateRange(days = 5): { startDate: string; endDate: string } {
  const end = previousAShareTradingDay(new Date());
  const start = new Date(end);
  let counted = 1;
  while (counted < days) {
    start.setDate(start.getDate() - 1);
    if (isAShareTradingDay(start)) {
      counted += 1;
    }
  }
  return { startDate: formatLocalDate(start), endDate: formatLocalDate(end) };
}

export function recentAShareTradingDateRangeEnding(
  endDate: string,
  days = 5
): { startDate: string; endDate: string } {
  const end = new Date(`${endDate}T00:00:00`);
  const start = new Date(end);
  let counted = 1;
  while (counted < days) {
    start.setDate(start.getDate() - 1);
    if (isAShareTradingDay(start)) {
      counted += 1;
    }
  }
  return { startDate: formatLocalDate(start), endDate };
}
