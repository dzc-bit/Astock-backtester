import { Activity, Radio, TrendingDown, TrendingUp } from "lucide-react";
import type { RealtimeMarketSnapshot } from "../types";

type Props = {
  snapshot: RealtimeMarketSnapshot | null;
  isLoading?: boolean;
};

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function movementClass(value: number | null | undefined): "up-text" | "down-text" | "flat-text" {
  if (value == null || Number.isNaN(value) || value === 0) {
    return "flat-text";
  }
  return value > 0 ? "up-text" : "down-text";
}

export function MarketDashboard({ snapshot, isLoading = false }: Props) {
  const breadth = snapshot?.breadth;
  const statusLabel = snapshot?.status === "live" ? "实时" : snapshot?.status === "stale" ? "本地兜底" : "待连接";

  return (
    <section className="surface market-dashboard" aria-label="今日实时行情">
      <div className="section-title">
        <div>
          <span className="section-kicker">本地数据 + 实时接口</span>
          <h2>今日实时行情</h2>
        </div>
        <span className={`status-pill compact market-status ${snapshot?.status ?? "loading"}`}>
          <Radio size={15} aria-hidden="true" />
          {isLoading ? "刷新中" : statusLabel}
        </span>
      </div>

      <div className="market-grid">
        <div className="index-strip">
          {(snapshot?.indexes ?? []).slice(0, 3).map((quote) => (
            <article className="index-quote" key={quote.symbol}>
              <span>{quote.name}</span>
              <strong>{formatNumber(quote.last)}</strong>
              <small className={movementClass(quote.change_pct)}>
                {formatPercent(quote.change_pct)} / {formatNumber(quote.change)}
              </small>
            </article>
          ))}
          {!snapshot && (
            <article className="index-quote">
              <span>行情连接</span>
              <strong>--</strong>
              <small>等待本地服务返回实时接口</small>
            </article>
          )}
        </div>

        <div className="breadth-panel">
          <div>
            <span>红绿家数</span>
            <strong>
              <TrendingUp size={18} aria-hidden="true" /> 红 {breadth?.up ?? "--"}
            </strong>
            <strong className="down-text">
              <TrendingDown size={18} aria-hidden="true" /> 绿 {breadth?.down ?? "--"}
            </strong>
          </div>
          <small>平盘 {breadth?.flat ?? "--"} / 合计 {breadth?.total ?? "--"}</small>
        </div>

        <div className="sector-panel">
          <div className="sector-head">
            <span>强势板块</span>
            <Activity size={18} aria-hidden="true" />
          </div>
          <div className="sector-list">
            {(snapshot?.strong_sectors ?? []).slice(0, 5).map((sector) => (
              <span key={`${sector.name}-${sector.leading_symbol ?? ""}`}>
                {sector.name}
                <strong className={movementClass(sector.change_pct)}>{formatPercent(sector.change_pct)}</strong>
              </span>
            ))}
            {snapshot && snapshot.strong_sectors.length === 0 ? <span>暂无板块数据</span> : null}
            {!snapshot ? <span>等待行情快照</span> : null}
          </div>
          <div className="yesterday-sector-track">
            <span>昨日强势追踪</span>
            <div className="sector-list compact">
              {(snapshot?.yesterday_strong_sectors ?? []).slice(0, 4).map((sector) => (
                <span key={`yesterday-${sector.name}-${sector.leading_symbol ?? ""}`}>
                  {sector.name}
                  <strong className={movementClass(sector.change_pct)}>{formatPercent(sector.change_pct)}</strong>
                </span>
              ))}
              {snapshot && (snapshot.yesterday_strong_sectors ?? []).length === 0 ? <span>等待昨日板块数据</span> : null}
              {!snapshot ? <span>等待行情快照</span> : null}
            </div>
          </div>
        </div>
      </div>

      <p className="market-footnote">
        来源 {snapshot?.source ?? "--"} / 更新 {formatTime(snapshot?.updated_at)} / {snapshot?.message ?? "正在等待实时行情"}
      </p>
    </section>
  );
}
