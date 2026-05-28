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

function buildMarketCommentary(snapshot: RealtimeMarketSnapshot | null): string {
  if (!snapshot || snapshot.status === "unavailable") {
    return "行情评价：实时接口没接上时不要硬猜方向，先把数据源恢复，再谈策略。";
  }
  const breadth = snapshot.breadth;
  const mainIndex = snapshot.indexes[0];
  const indexPct = mainIndex?.change_pct ?? 0;
  const upRatio = breadth && breadth.total > 0 ? breadth.up / breadth.total : null;
  const sectorCount = snapshot.strong_sectors.length;
  const todaySectorNames = new Set(snapshot.strong_sectors.map((sector) => sector.name));
  const yesterdaySectors = snapshot.yesterday_strong_sectors ?? [];
  const continuedSectors = yesterdaySectors
    .filter((sector) => todaySectorNames.has(sector.name))
    .slice(0, 2)
    .map((sector) => sector.name);
  const yesterdayText =
    yesterdaySectors.length === 0
      ? "昨日强势数据还没补齐，别只凭记忆追热点。"
      : continuedSectors.length > 0
        ? `昨日强势延续：${continuedSectors.join("、")}仍在榜，资金没完全散场，但量能掉线就别硬追。`
        : "昨日强势未延续：资金切换很快，追昨天热点容易被挂在高位。";
  const withYesterday = (text: string) => `${text} ${yesterdayText}`;
  if (upRatio != null && upRatio > 0.62 && indexPct > 0) {
    return withYesterday(sectorCount > 0
      ? "行情评价：红盘占优且指数在推，但别把普涨当主线，强势板块不延续就容易追在情绪高点。"
      : "行情评价：涨的是面，不是线；没有板块确认时，追高胜率会被摊薄。");
  }
  if (upRatio != null && upRatio < 0.42 && indexPct <= 0) {
    return withYesterday("行情评价：绿盘压过红盘，指数也不配合，这种盘面先防回撤，别急着证明自己比市场聪明。");
  }
  if (indexPct > 0 && upRatio != null && upRatio < 0.5) {
    return withYesterday("行情评价：指数红、个股弱，典型权重护盘味道，策略要更挑剔，别被指数表情骗了。");
  }
  return withYesterday("行情评价：盘面分歧不小，能做的是等条件确认，不是把每次波动都解释成机会。");
}

function buildClosingSectorReview(snapshot: RealtimeMarketSnapshot | null): string | null {
  if (!snapshot || snapshot.strong_sectors.length === 0) {
    return null;
  }
  const updatedAt = new Date(snapshot.updated_at);
  const beijingHour = Number(
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      hour12: false
    })
      .formatToParts(updatedAt)
      .find((part) => part.type === "hour")?.value
  );
  const showAsClosingReview = beijingHour >= 15 || snapshot.status === "stale";
  if (!showAsClosingReview) {
    return null;
  }
  const leaders = snapshot.strong_sectors
    .slice(0, 3)
    .map((sector) => `${sector.name}${formatPercent(sector.change_pct)}`)
    .join("、");
  const todaySectorNames = new Set(snapshot.strong_sectors.map((sector) => sector.name));
  const yesterdaySectors = snapshot.yesterday_strong_sectors ?? [];
  const continuedSectors = yesterdaySectors
    .filter((sector) => todaySectorNames.has(sector.name))
    .slice(0, 2)
    .map((sector) => sector.name);
  const yesterdayText =
    continuedSectors.length > 0
      ? `昨日强势延续在 ${continuedSectors.join("、")}，次日先看承接。`
      : yesterdaySectors.length > 0
        ? "昨日强势没有明显延续，次日别把旧热点当新主线。"
        : "昨日板块追踪不足，次日观察要保守一点。";
  const breadth = snapshot.breadth;
  const upRatio = breadth && breadth.total > 0 ? breadth.up / breadth.total : null;
  const breadthText =
    upRatio == null
      ? "红绿家数缺失，强度只看板块会偏窄"
      : upRatio >= 0.55
        ? "红盘占优，板块强度有扩散"
        : upRatio <= 0.45
          ? "绿盘偏多，板块更像局部抱团"
          : "红绿接近，主线还没有压倒性优势";
  return `收盘后板块解读：${leaders} 领涨；${breadthText}。${yesterdayText} 次日优先看这些方向是否继续放量，否则不要把一日强势当成趋势。`;
}

export function MarketDashboard({ snapshot, isLoading = false }: Props) {
  const breadth = snapshot?.breadth;
  const statusLabel = snapshot?.status === "live" ? "实时" : snapshot?.status === "stale" ? "本地兜底" : "待连接";
  const closingSectorReview = buildClosingSectorReview(snapshot);

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
      <div className="market-commentary">{buildMarketCommentary(snapshot)}</div>
      {closingSectorReview ? <div className="market-commentary closing-review">{closingSectorReview}</div> : null}
    </section>
  );
}
