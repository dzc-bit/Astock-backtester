import type { MarketRefreshMeta, MarketSessionPhase } from "./types";

const TRADING_INTERVAL_MS = 60_000;
const CLOSED_INTERVAL_MS = 5 * 60_000;
const FAILURE_RETRY_MS = 2 * 60_000;

export function detectMarketSessionPhase(now = new Date()): MarketSessionPhase {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(now);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  const weekday = value("weekday");
  const hour = Number(value("hour"));
  const minute = Number(value("minute"));
  const minutes = hour * 60 + minute;
  if (weekday === "Sat" || weekday === "Sun") {
    return "non_trading";
  }
  if (minutes < 9 * 60 + 30) {
    return "pre_open";
  }
  if (minutes >= 11 * 60 + 30 && minutes < 13 * 60) {
    return "lunch_break";
  }
  if (minutes >= 15 * 60) {
    return "post_close";
  }
  return "trading";
}

export function refreshIntervalForPhase(phase: MarketSessionPhase, hasError = false): number {
  if (hasError) {
    return FAILURE_RETRY_MS;
  }
  return phase === "trading" ? TRADING_INTERVAL_MS : CLOSED_INTERVAL_MS;
}

export function refreshIntervalForMarketResult(
  phase: MarketSessionPhase,
  _diagnostics: string[] | undefined,
  hasError = false
): number {
  return refreshIntervalForPhase(phase, hasError);
}

export function marketPhaseLabel(phase: MarketSessionPhase): string {
  return {
    trading: "交易时段",
    pre_open: "盘前",
    lunch_break: "午间休市",
    post_close: "收盘后",
    non_trading: "非交易时段"
  }[phase];
}

export function initialMarketRefreshMeta(): MarketRefreshMeta {
  const phase = detectMarketSessionPhase();
  return {
    phase,
    status: "idle",
    message: "等待实时行情刷新",
    next_refresh_ms: refreshIntervalForPhase(phase)
  };
}
