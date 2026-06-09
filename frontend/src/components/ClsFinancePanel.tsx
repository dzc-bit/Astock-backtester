import { Activity, Eye, Flame, Gauge, RadioTower, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ClsFinancePoolItem, ClsFinanceResponse } from "../types";

type Props = {
  finance: ClsFinanceResponse | null;
  isLoading?: boolean;
};

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

function formatMinute(minute: number): string {
  const value = minute.toString().padStart(4, "0");
  return `${value.slice(0, 2)}:${value.slice(2)}`;
}

function tlinePath(finance: ClsFinanceResponse): string {
  const points = finance.tline.slice(-80);
  if (points.length === 0) {
    return "";
  }
  const values = points.map((point) => point.last_px);
  const min = Math.min(...values, finance.preclose_px ?? values[0]);
  const max = Math.max(...values, finance.preclose_px ?? values[0]);
  const span = max - min || 1;
  return points
    .map((point, index) => {
      const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 100;
      const y = 80 - ((point.last_px - min) / span) * 60;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
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
  const emotion = finance?.emotion ?? null;
  const latestPoint = finance?.tline.at(-1) ?? null;
  const path = finance ? tlinePath(finance) : "";
  const upPool = finance?.up_pool ?? [];
  const anchors = finance?.anchors.slice(0, 8) ?? [];

  return (
    <section className="surface cls-finance-panel" aria-label="财联社看盘">
      <div className="section-title">
        <div>
          <span className="section-kicker">财联社</span>
          <h2>财联社看盘</h2>
        </div>
        <div className="cls-finance-actions">
          {finance ? (
            <button className="secondary-button compact cls-finance-detail-button" type="button" onClick={() => setIsPoolOpen(true)}>
              <Eye size={15} aria-hidden="true" />
              查看涨停明细
            </button>
          ) : null}
          <span className="status-pill compact cls-finance-source">
            <RadioTower size={15} aria-hidden="true" />
            {finance ? `更新 ${formatTime(finance.updated_at)}` : isLoading ? "加载中" : "待连接"}
          </span>
        </div>
      </div>

      {!finance ? (
        <div className="empty-state">
          <strong>{isLoading ? "正在加载财联社看盘" : "暂无财联社看盘"}</strong>
          <span>后端 `/market/finance` 返回后，会显示财联社盘面分时、市场热度、涨停明细和盘面锚点。</span>
        </div>
      ) : (
        <div className="cls-finance-body">
          <div className="cls-finance-main">
            <div className="cls-finance-chart-head">
              <div>
                <span>上证分时</span>
                <strong>{latestPoint ? latestPoint.last_px.toFixed(2) : "--"}</strong>
              </div>
              <span className={(latestPoint?.change ?? 0) >= 0 ? "market-up" : "market-down"}>
                {formatPercent(latestPoint?.change)}
              </span>
            </div>
            <svg className="cls-finance-tline" viewBox="0 0 100 90" role="img" aria-label="财联社上证指数分时线" preserveAspectRatio="none">
              <line x1="0" x2="100" y1="50" y2="50" />
              {path ? <path d={path} /> : null}
            </svg>
            <div className="cls-finance-ticks">
              <span>{finance.tline[0] ? formatMinute(finance.tline[0].minute) : "--"}</span>
              <span>{latestPoint ? formatMinute(latestPoint.minute) : "--"}</span>
            </div>
          </div>

          <div className="cls-finance-side">
            <div className="cls-finance-stats" aria-label="财联社市场热度">
              <article>
                <Gauge size={16} aria-hidden="true" />
                <span>市场热度</span>
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
          </div>
        </div>
      )}
      {finance && isPoolOpen ? <LimitUpPoolDialog items={upPool} onClose={() => setIsPoolOpen(false)} /> : null}
    </section>
  );
}
