import { Play } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BacktestResult, DailyStrategyMatches } from "../types";

type Props = {
  result: BacktestResult | null;
  isRunning?: boolean;
  phases?: string[];
  progressMessage?: string | null;
  onRun: () => void;
  riskAlertCount?: number;
  onOpenRiskAlerts: () => void;
};

function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  return value.toFixed(2);
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

function movementClass(value: number | null | undefined): "up-text" | "down-text" | "flat-text" {
  if (value == null || Number.isNaN(value) || value === 0) {
    return "flat-text";
  }
  return value > 0 ? "up-text" : "down-text";
}

function isToday(value: string | null | undefined): boolean {
  if (!value) {
    return false;
  }
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(new Date());
  return value === today;
}

function MatchedStocksPanel({ dailyMatches }: { dailyMatches?: DailyStrategyMatches | null }) {
  const hasPayload = Boolean(dailyMatches);
  const rawItems = dailyMatches?.matches ?? [];
  const items = [...rawItems].sort((left, right) => (right.rank_score ?? 0) - (left.rank_score ?? 0));
  const matchesAreToday = isToday(dailyMatches?.trade_date);
  const title = matchesAreToday ? "今日 user 模式候选" : "本地最近交易日候选";
  const kicker = matchesAreToday ? "当日符合用户策略的个股" : "本地最近交易日/非实时";
  const dateLabel = dailyMatches
    ? `信号日 ${dailyMatches.signal_date} / 展示日 ${dailyMatches.trade_date} / 本地回测快照`
    : "等待 latest_strategy_matches";
  const priceLabel = matchesAreToday ? "本地收盘价" : "本地最近收盘价";
  return (
    <section className="matched-stocks-panel" aria-label="策略命中">
      <div className="matched-stocks-head">
        <div>
          <span className="section-kicker">{kicker}</span>
          <h3>{title}</h3>
          <small>{dateLabel}</small>
        </div>
        <strong>{hasPayload ? `${items.length} 只` : "待对接"}</strong>
      </div>
      {items.length > 0 ? (
        <div className="matched-stocks-list">
          {items.slice(0, 12).map((stock) => (
            <article className="matched-stock-card" key={`${stock.symbol}-${stock.trade_date ?? ""}`}>
              <div className="matched-stock-id">
                <strong>{stock.symbol}</strong>
                <span>{stock.name || "--"}</span>
              </div>
              <div className="matched-stock-quote">
                <strong className={movementClass(stock.change_pct)}>{formatPercent(stock.change_pct)}</strong>
                <span>{priceLabel} {formatPrice(stock.close)}</span>
                {stock.rank_score != null ? <small>评分 {stock.rank_score.toFixed(2)}</small> : null}
              </div>
              <div className="matched-stock-reasons">
                {stock.reasons.length > 0 ? (
                  stock.reasons.slice(0, 4).map((reason) => <span key={reason}>{reason}</span>)
                ) : (
                  <span>命中策略条件</span>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="matched-stocks-empty">
          <strong>{hasPayload ? `${matchesAreToday ? "今日" : "本地最近交易日"}没有股票命中当前策略` : "等待回测结果返回策略候选"}</strong>
          <span>
            {hasPayload
              ? "可以放宽入场条件、扩大股票池，或查看数据中心是否缺少行情/资金字段。"
              : "回测完成后，这里会展示代码、名称、本地收盘价、涨跌幅、匹配理由和 rank_score。"}
          </span>
        </div>
      )}
    </section>
  );
}

export function ResultsOverview({
  result,
  isRunning = false,
  phases = [],
  progressMessage = null,
  onRun,
  riskAlertCount = 0,
  onOpenRiskAlerts
}: Props) {
  const issueCount = result?.preflight_issues.length ?? 0;
  const chartStart = result?.equity_curve[0]?.trade_date;
  const chartEnd = result?.equity_curve.at(-1)?.trade_date;
  const zeroTradeHint = result && result.metrics.trade_count === 0
    ? "本次没有产生交易。常见原因是日期范围过短、股票池过窄、条件过严或本地字段缺失。"
    : null;

  return (
    <section className="surface results-surface">
      <div className="section-title">
        <div>
          <span className="section-kicker">策略收益与风险</span>
          <h2>收益概览</h2>
        </div>
        <button className="primary-button" type="button" onClick={onRun} disabled={isRunning}>
          <Play size={16} aria-hidden="true" />
          {isRunning ? "回测运行中" : "运行历史回测"}
        </button>
      </div>
      {isRunning || phases.length > 0 ? (
        <div className="run-progress" role="status" aria-label="回测运行进度">
          {phases.map((phase, index) => (
            <span key={phase} className={index === phases.length - 1 && isRunning ? "active" : "done"}>
              {phase}
            </span>
          ))}
        </div>
      ) : null}
      {progressMessage && (!result || !isRunning) ? (
        <div className="run-live-state">
          <strong>{isRunning ? "回测正在撮合" : "回测完成"}</strong>
          <span>{progressMessage}</span>
        </div>
      ) : null}
      {isRunning && !result && !progressMessage ? (
        <div className="run-live-state">
          <strong>回测正在撮合</strong>
          <span>正在扫描历史交易日，首笔开仓或平仓会立即写入右侧交易明细。</span>
        </div>
      ) : null}
      {result ? (
        <>
          <div className="metrics">
            <span>总收益 {(result.metrics.total_return_pct * 100).toFixed(2)}%</span>
            <span>年化收益 {(result.metrics.annualized_return_pct * 100).toFixed(2)}%</span>
            <span>最大回撤 {(result.metrics.max_drawdown_pct * 100).toFixed(2)}%</span>
            <span>胜率 {(result.metrics.win_rate_pct * 100).toFixed(2)}%</span>
            <span>交易次数 {result.metrics.trade_count}</span>
            <span>平均仓位 {(result.metrics.average_position_pct * 100).toFixed(2)}%</span>
            <span>最大仓位 {(result.metrics.max_position_pct * 100).toFixed(2)}%</span>
          </div>
          <div className="risk-strip">
            <strong>风险提示</strong>
            <span>
              {riskAlertCount > 0
                ? `市场风险清单发现 ${riskAlertCount} 只 ST 或退市风险股票`
                : issueCount === 0
                  ? "数据预检未发现阻断项"
                  : `发现 ${issueCount} 条数据或策略预检提示`}
            </span>
            <span>资金校准：{result.trades.some((trade) => trade.buy_reason.some((reason) => reason.includes("inflow"))) ? "已使用资金面条件" : "未使用资金面校准"}</span>
            <button className="secondary-button" type="button" onClick={onOpenRiskAlerts}>
              查看风险清单
            </button>
          </div>
          {zeroTradeHint ? (
            <div className="risk-strip no-trade-hint">
              <strong>无交易说明</strong>
              <span>{zeroTradeHint}</span>
            </div>
          ) : null}
          <MatchedStocksPanel dailyMatches={result.latest_strategy_matches} />
          <div className="chart">
            <div className="chart-head">
              <strong>历史权益曲线</strong>
              {chartStart && chartEnd ? <span>回测区间 {chartStart} 至 {chartEnd}</span> : null}
            </div>
            <div className="chart-body">
              <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={220}>
                <LineChart data={result.equity_curve}>
                  <XAxis dataKey="trade_date" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="equity" stroke="#0f766e" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      ) : !isRunning ? (
        <div className="empty-state">
          <strong>尚未运行回测</strong>
          <span>调整策略和参数后，点击“运行历史回测”查看收益曲线、回撤和交易原因。</span>
          <button className="secondary-button" type="button" onClick={onOpenRiskAlerts}>
            查看风险清单
          </button>
        </div>
      ) : null}
    </section>
  );
}
