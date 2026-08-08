import { invoke } from "@tauri-apps/api/core";
import { Activity, ExternalLink, Eye, Flame, Gauge, RadioTower, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { isTauriRuntime } from "../tauriRuntime";
import type { ClsFinanceEmotion, ClsFinancePoolItem, ClsFinanceResponse, ClsFinanceTlinePoint } from "../types";

type Props = {
  finance: ClsFinanceResponse | null;
  isLoading?: boolean;
};

const CLS_FINANCE_PAGE_URL = "https://www.cls.cn/finance";

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

function formatPercent(value: number | null | undefined): string {
  return value == null ? "--" : `${(value * 100).toFixed(2)}%`;
}

function compactText(value: string | null | undefined, maxLength = 48): string {
  const normalized = (value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "--";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}...`;
}

function joinNames(names: string[], maxItems = 4): string {
  const uniqueNames = Array.from(new Set(names.map((name) => name.trim()).filter(Boolean)));
  if (uniqueNames.length === 0) {
    return "暂无明确板块";
  }
  const visible = uniqueNames.slice(0, maxItems);
  const suffix = uniqueNames.length > visible.length ? ` 等 ${uniqueNames.length} 个` : "";
  return `${visible.join("、")}${suffix}`;
}

function marketMoodLabel(value: number | null | undefined): string {
  if (value == null) {
    return "等待热度";
  }
  if (value >= 50) {
    return "热度偏强";
  }
  if (value >= 40) {
    return "热度中性";
  }
  return "热度偏弱";
}

function isTonghuashunMarketDegree(emotion: ClsFinanceEmotion | null): boolean {
  return emotion?.market_degree_source === "ths-market-summary";
}

function marketDegreeStatTitle(emotion: ClsFinanceEmotion | null): string {
  return isTonghuashunMarketDegree(emotion) ? "大盘评分" : "市场热度";
}

function marketDegreeCardTitle(emotion: ClsFinanceEmotion | null): string {
  return isTonghuashunMarketDegree(emotion) ? "大盘评分" : "盘面热度";
}

function marketDegreeMeta(emotion: ClsFinanceEmotion | null): string {
  if (isTonghuashunMarketDegree(emotion)) {
    return emotion?.market_degree_label ?? "同花顺大盘评级";
  }
  return marketMoodLabel(emotion?.market_degree);
}

function marketDegreeSummaryLabel(emotion: ClsFinanceEmotion | null): string {
  if (isTonghuashunMarketDegree(emotion)) {
    return emotion?.market_degree_label ?? "同花顺大盘评级";
  }
  return "财联社市场热度";
}

function marketDegreeSentiment(emotion: ClsFinanceEmotion | null): "positive" | "neutral" {
  const value = emotion?.market_degree;
  if (value == null) {
    return "neutral";
  }
  return value >= (isTonghuashunMarketDegree(emotion) ? 5 : 50) ? "positive" : "neutral";
}

function hasAvailableFinanceFields(finance: ClsFinanceResponse): boolean {
  const emotion = finance.emotion;
  return (
    finance.preclose_px != null ||
    finance.tline.length > 0 ||
    finance.anchors.length > 0 ||
    finance.up_pool.length > 0 ||
    emotion?.market_degree != null ||
    Boolean(emotion?.shsz_balance) ||
    Boolean(emotion?.shsz_balance_change) ||
    emotion?.breadth != null ||
    emotion?.up_limit != null ||
    emotion?.open_limit != null ||
    Boolean(emotion?.performance)
  );
}

function buildBriefingCards(finance: ClsFinanceResponse) {
  const emotion = finance.emotion ?? null;
  const anchorNames = finance.anchors.map((anchor) => anchor.name);
  const firstReason = compactText(finance.up_pool[0]?.reason, 46);
  const breadth = emotion?.breadth;
  const anchorUpCount = finance.anchors.filter((anchor) => anchor.direction !== "down").length;
  const anchorDownCount = finance.anchors.filter((anchor) => anchor.direction === "down").length;
  return [
    {
      title: marketDegreeCardTitle(emotion),
      sentiment: marketDegreeSentiment(emotion),
      meta: `${finance.tline.length} 个分时点 / ${marketDegreeMeta(emotion)}`,
      summary: `${marketDegreeSummaryLabel(emotion)} ${emotion?.market_degree != null ? emotion.market_degree.toFixed(1) : "--"}，涨停 ${emotion?.up_limit ?? "--"} 家，开板 ${emotion?.open_limit ?? "--"} 家。`,
      headlines: [
        breadth ? `上涨 ${breadth.up} / 下跌 ${breadth.down}` : "暂无完整涨跌分布",
        emotion?.performance ? `指数表现 ${emotion.performance}` : "等待指数表现"
      ]
    },
    {
      title: "重点板块",
      sentiment: finance.anchors.length > 0 ? "positive" : "neutral",
      meta:
        finance.anchors.length > 0
          ? `${finance.anchors.length} 个锚点 / ${anchorUpCount} 强 ${anchorDownCount} 弱`
          : "0 个锚点 / 暂无锚点",
      summary: joinNames(anchorNames),
      headlines:
        finance.anchors.length > 0
          ? finance.anchors.slice(0, 2).map((anchor) => `${anchor.direction === "down" ? "走弱" : "走强"}：${anchor.name}`)
          : ["暂无明确要点"]
    },
    {
      title: "涨停动因",
      sentiment: (finance.up_pool.length > 0 ? "positive" : "neutral") as "positive" | "neutral",
      meta: `${finance.up_pool.length} 个样本 / ${finance.up_pool.length > 0 ? "涨停池" : "暂无涨停池"}`,
      summary: finance.up_pool.length > 0 ? `涨停池 ${finance.up_pool.length} 只，首条原因：${firstReason}` : "暂无涨停池明细。",
      headlines: finance.up_pool.length > 0 ? [`${finance.up_pool.length} 只涨停样本`, "查看涨停明细获取个股列表"] : ["暂无明确要点"]
    }
  ];
}

type TlineChart = {
  path: string;
  latestChange: number | null;
  range: number;
};

function minuteOfDay(value: number): number | null {
  const hour = Math.floor(value / 100);
  const minute = value % 100;
  if (hour < 0 || hour > 23 || minute < 0 || minute >= 60) {
    return null;
  }
  return hour * 60 + minute;
}

function tradingPosition(point: ClsFinanceTlinePoint): { x: number; session: "morning" | "afternoon" } | null {
  const minute = minuteOfDay(point.minute);
  if (minute == null) {
    return null;
  }
  const morningOpen = 9 * 60 + 30;
  const morningClose = 11 * 60 + 30;
  const afternoonOpen = 13 * 60;
  const afternoonClose = 15 * 60;
  if (minute >= morningOpen && minute <= morningClose) {
    return { x: 7 + ((minute - morningOpen) / (morningClose - morningOpen)) * 40, session: "morning" };
  }
  if (minute >= afternoonOpen && minute <= afternoonClose) {
    return { x: 53 + ((minute - afternoonOpen) / (afternoonClose - afternoonOpen)) * 40, session: "afternoon" };
  }
  return null;
}

function pointChange(point: ClsFinanceTlinePoint, preclose: number | null | undefined): number | null {
  if (preclose != null && preclose > 0) {
    return point.last_px / preclose - 1;
  }
  return point.change ?? null;
}

function buildTlineChart(finance: ClsFinanceResponse): TlineChart {
  const chartPoints = finance.tline
    .map((point) => {
      const position = tradingPosition(point);
      const change = pointChange(point, finance.preclose_px);
      return position && change != null ? { ...position, change } : null;
    })
    .filter((point): point is { x: number; session: "morning" | "afternoon"; change: number } => point !== null);
  const range = Math.max(0.003, ...chartPoints.map((point) => Math.abs(point.change)));
  let previousSession: "morning" | "afternoon" | null = null;
  const path = chartPoints
    .map((point) => {
      const y = Math.max(10, Math.min(90, 50 - (point.change / range) * 38));
      const command = previousSession === point.session ? "L" : "M";
      previousSession = point.session;
      return `${command} ${point.x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const latestPoint = finance.tline.at(-1);
  return {
    path,
    latestChange: latestPoint ? pointChange(latestPoint, finance.preclose_px) : null,
    range,
  };
}

async function openFinancePage(url: string | null | undefined): Promise<void> {
  const target = url?.trim();
  if (!target) {
    return;
  }
  if (isTauriRuntime()) {
    await invoke("open_external_url", { url: target });
    return;
  }
  window.open(target, "_blank", "noopener,noreferrer");
}

function LimitUpPoolDialog({
  items,
  onClose
}: {
  items: ClsFinancePoolItem[];
  onClose: () => void;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="modal-backdrop">
      <section className="cls-finance-pool-modal" role="dialog" aria-modal="true" aria-label="财联社涨停明细">
        <div className="modal-head">
          <div>
            <span className="section-kicker">财联社</span>
            <h2>涨停明细</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭涨停明细" onClick={onClose} ref={closeButtonRef}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="cls-finance-pool-modal-meta">
          <span>共 {items.length} 条</span>
        </div>

        <div className="cls-finance-pool-modal-body">
          {items.length > 0 ? (
            items.map((item) => (
              <article className="cls-finance-pool-card" key={`${item.symbol}-${item.time ?? ""}`}>
                <div className="cls-finance-pool-card-head">
                  <div>
                    <strong>{item.name}</strong>
                    <span>{item.symbol}</span>
                  </div>
                  <span className="market-up">{formatPercent(item.change_pct)}</span>
                </div>
                <p>{compactText(item.reason, 96)}</p>
                <div className="cls-finance-plates">
                  {item.plates.length > 0 ? (
                    item.plates.map((plate) => <span key={`${item.symbol}-${plate.code || plate.name}`}>{plate.name}</span>)
                  ) : (
                    <span>暂无板块</span>
                  )}
                </div>
              </article>
            ))
          ) : (
            <span className="cls-finance-muted">暂无涨停明细</span>
          )}
        </div>
      </section>
    </div>
  );
}

export function ClsFinancePanel({ finance, isLoading = false }: Props) {
  const [isPoolOpen, setIsPoolOpen] = useState(false);
  const financePageUrl = finance?.source_url?.trim() || CLS_FINANCE_PAGE_URL;
  const emotion = finance?.emotion ?? null;
  const latestPoint = finance?.tline.at(-1) ?? null;
  const tlineChart = finance ? buildTlineChart(finance) : null;
  const upPool = finance?.up_pool ?? [];
  const anchors = finance?.anchors.slice(0, 8) ?? [];
  const briefingCards = finance ? buildBriefingCards(finance) : [];
  const usingRecentSuccess = finance?.source.includes("+recent-success-cache") ?? false;
  const financeUnavailable = Boolean(finance && !usingRecentSuccess && !hasAvailableFinanceFields(finance));
  const financeDiagnostics = finance?.diagnostics ?? [];

  return (
    <section className="surface cls-finance-panel" aria-label="财联社看盘">
      <div className="section-title">
        <div>
          <span className="section-kicker">财联社</span>
          <h2>财联社看盘</h2>
        </div>
        <div className="cls-finance-actions">
          <span className="status-pill compact cls-finance-source">
            <RadioTower size={15} aria-hidden="true" />
            {finance
              ? `${financeUnavailable ? "CLS 数据暂不可用" : usingRecentSuccess ? "最近成功数据" : "CLS 实时数据"} / 更新 ${formatTime(finance.updated_at)}`
              : isLoading
                ? "加载中"
                : "待连接"}
          </span>
          {finance && !financeUnavailable ? (
            <button
              className="secondary-button compact cls-finance-detail-button"
              type="button"
              aria-label="查看涨停明细"
              onClick={() => setIsPoolOpen(true)}
            >
              <Eye size={15} aria-hidden="true" />
              涨停明细
            </button>
          ) : null}
          <button
            className="icon-button cls-finance-open-button"
            type="button"
            aria-label="打开财联社看盘页"
            title="打开财联社看盘页"
            onClick={() => void openFinancePage(financePageUrl)}
          >
            <ExternalLink size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {finance && financeUnavailable && financeDiagnostics.length > 0 ? (
        <div
          className="cls-finance-diagnostics"
          role="status"
          aria-label="财联社数据诊断"
          tabIndex={0}
        >
          <strong>财联社数据诊断</strong>
          <span>来源 {finance.source}</span>
          {financeDiagnostics.map((item, index) => (
            <span key={`${item}-${index}`}>{item}</span>
          ))}
        </div>
      ) : null}

      {!finance ? (
        <div className="empty-state">
          <strong>{isLoading ? "正在加载财联社看盘" : "暂无财联社看盘"}</strong>
          <span>后端 `/market/finance` 返回后，会显示财联社盘面分时、市场热度、涨停明细和盘面锚点。</span>
        </div>
      ) : financeUnavailable ? (
        <div className="empty-state">
          <strong>CLS 数据暂不可用</strong>
          <span>当前未取得可展示的财联社看盘字段，请查看上方数据诊断。</span>
        </div>
      ) : (
        <div className="cls-finance-body">
          <div className="cls-finance-main">
            <div className="cls-finance-chart-head">
              <div>
                <span>上证分时</span>
                <strong>{latestPoint ? latestPoint.last_px.toFixed(2) : "--"}</strong>
              </div>
              <span className={(tlineChart?.latestChange ?? 0) >= 0 ? "market-up" : "market-down"}>
                {formatPercent(tlineChart?.latestChange)}
              </span>
            </div>
            <div className="cls-finance-chart-context">
              <span>昨收 {finance.preclose_px != null ? finance.preclose_px.toFixed(2) : "--"}</span>
              <span>范围 +/-{tlineChart ? `${(tlineChart.range * 100).toFixed(2)}%` : "--"}</span>
            </div>
            <svg
              className="cls-finance-tline"
              viewBox="0 0 100 100"
              role="img"
              aria-label="财联社上证指数分时线，以昨收为零轴"
              preserveAspectRatio="none"
            >
              <line className="cls-finance-gridline" x1="7" x2="93" y1="12" y2="12" />
              <line className="cls-finance-baseline" x1="7" x2="93" y1="50" y2="50" aria-label="上证指数昨收基准" />
              <line className="cls-finance-gridline" x1="7" x2="93" y1="88" y2="88" />
              {tlineChart?.path ? (
                <path
                  className={
                    (tlineChart.latestChange ?? 0) > 0
                      ? "is-up"
                      : (tlineChart.latestChange ?? 0) < 0
                        ? "is-down"
                        : "is-flat"
                  }
                  d={tlineChart.path}
                />
              ) : null}
            </svg>
            <div className="cls-finance-ticks">
              <span>09:30</span>
              <span>11:30</span>
              <span>13:00</span>
              <span>15:00</span>
            </div>
          </div>

          <div className="cls-finance-side">
            <div className="cls-finance-stats" aria-label={marketDegreeSummaryLabel(emotion)}>
              <article>
                <Gauge size={16} aria-hidden="true" />
                <span>{marketDegreeStatTitle(emotion)}</span>
                <strong>{emotion?.market_degree != null ? emotion.market_degree.toFixed(1) : "--"}</strong>
              </article>
              <article>
                <Flame size={16} aria-hidden="true" />
                <span>涨停数</span>
                <strong>涨停 {emotion?.up_limit ?? "--"}</strong>
              </article>
              <article>
                <Activity size={16} aria-hidden="true" />
                <span>开板</span>
                <strong>开板 {emotion?.open_limit ?? "--"}</strong>
              </article>
            </div>

            <div className="cls-finance-anchors" aria-label="财联社盘面锚点">
              {anchors.length > 0 ? (
                anchors.map((anchor) => (
                  <span className={`cls-anchor ${anchor.direction}`} key={`${anchor.code}-${anchor.c_time ?? ""}`}>
                    {anchor.name}
                  </span>
                ))
              ) : (
                <span className="cls-finance-muted">暂无盘面锚点</span>
              )}
            </div>

            <div className="cls-finance-briefing-list" aria-label="财联社盘面归纳">
              {briefingCards.map((card) => (
                <article className={`news-summary-topic cls-finance-briefing-card ${card.sentiment}`} key={card.title}>
                  <div className="news-summary-topic-head">
                    <div>
                      <span>{card.meta}</span>
                      <h3>{card.title}</h3>
                    </div>
                    <Sparkles size={17} aria-hidden="true" />
                  </div>
                  <p className="news-summary-brief">{card.summary}</p>
                  <div className="news-summary-teasers" aria-label={`${card.title}精要`}>
                    {card.headlines.map((headline) => (
                      <span className="news-summary-chip" key={headline}>
                        {compactText(headline, 34)}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      )}
      {finance && isPoolOpen ? <LimitUpPoolDialog items={upPool} onClose={() => setIsPoolOpen(false)} /> : null}
    </section>
  );
}
