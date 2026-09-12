import type { BacktestResult, BacktestSettingsConfig, StrategyConfig } from "./types";

/**
 * Single-file HTML backtest report (equity-curve SVG + metrics table + trade
 * sheet + optional AI commentary). Generated entirely in the browser and
 * downloaded as a Blob; no backend round-trip and no new dependencies.
 */

const REPORT_CSS = `
:root { color-scheme: light; }
body { font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; margin: 0; background: #f4f7fa; color: #17212f; }
main { max-width: 960px; margin: 0 auto; padding: 32px 24px 48px; }
header h1 { margin: 0 0 4px; font-size: 24px; }
header p { margin: 0 0 24px; color: #526071; font-size: 13px; }
section { background: #fff; border: 1px solid #dde5ee; border-radius: 10px; padding: 20px; margin-bottom: 20px; }
h2 { margin: 0 0 12px; font-size: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid #e8edf3; padding: 7px 8px; text-align: left; white-space: nowrap; }
th { color: #526071; font-weight: 600; background: #f8fafc; }
td.rise, span.rise { color: #d92d20; }
td.fall, span.fall { color: #079455; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.metric { border: 1px solid #e8edf3; border-radius: 8px; padding: 10px 12px; }
.metric span { display: block; color: #526071; font-size: 12px; }
.metric strong { font-size: 17px; }
.ai-note { border-left: 3px solid #0f766e; background: #f2faf8; padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 0; }
footer { color: #8a97a8; font-size: 12px; margin-top: 8px; }
`;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatPercent(value: number | null | undefined, digits = 2): string {
  return value == null ? "--" : `${(value * 100).toFixed(digits)}%`;
}

function buildEquitySvg(result: BacktestResult): string {
  const points = result.equity_curve.filter((point) => Number.isFinite(point.equity));
  if (points.length < 2) {
    return "<p>权益曲线数据不足，未绘制图形。</p>";
  }
  const width = 860;
  const height = 240;
  const padding = 8;
  const equities = points.map((point) => point.equity);
  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const span = max - min || 1;
  const stepX = (width - padding * 2) / (points.length - 1);
  const coords = points.map((point, index) => {
    const x = padding + index * stepX;
    const y = height - padding - ((point.equity - min) / span) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const first = equities[0];
  const last = equities[equities.length - 1];
  const trendClass = last >= first ? "rise" : "fall";
  return `
  <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="权益曲线 SVG">
    <polyline fill="none" stroke="#0f766e" stroke-width="2" points="${coords.join(" ")}" />
  </svg>
  <p>区间 <span class="${trendClass}">${formatPercent(last / first - 1)}</span>（${escapeHtml(points[0].trade_date)} 至 ${escapeHtml(points[points.length - 1].trade_date)}）</p>`;
}

function buildMetricsTable(result: BacktestResult): string {
  const rows: Array<[string, string]> = [
    ["总收益", formatPercent(result.metrics.total_return_pct)],
    ["年化收益", formatPercent(result.metrics.annualized_return_pct)],
    ["最大回撤", formatPercent(result.metrics.max_drawdown_pct)],
    ["胜率", formatPercent(result.metrics.win_rate_pct)],
    ["交易次数", String(result.metrics.trade_count)],
    ["平均仓位", formatPercent(result.metrics.average_position_pct)],
    ["最大仓位", formatPercent(result.metrics.max_position_pct)]
  ];
  return `<div class="metrics-grid">${rows
    .map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`)
    .join("")}</div>`;
}

function buildTradesTable(result: BacktestResult): string {
  if (result.trades.length === 0) {
    return "<p>本次回测没有产生交易。</p>";
  }
  const rows = result.trades
    .slice(0, 300)
    .map(
      (trade) => `<tr>
      <td>${escapeHtml(trade.symbol)}</td>
      <td>${escapeHtml(trade.buy_signal_date)}</td>
      <td>${escapeHtml(trade.buy_date)}</td>
      <td>${escapeHtml(trade.sell_date ?? "持仓中")}</td>
      <td>${trade.buy_price.toFixed(2)}</td>
      <td>${trade.sell_price == null ? "--" : trade.sell_price.toFixed(2)}</td>
      <td class="${(trade.pnl_pct ?? 0) >= 0 ? "rise" : "fall"}">${formatPercent(trade.pnl_pct)}</td>
    </tr>`
    )
    .join("");
  return `<table><thead><tr><th>代码</th><th>信号日</th><th>买入日</th><th>卖出日</th><th>买价</th><th>卖价</th><th>盈亏</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function buildStrategySummary(strategy: StrategyConfig, settings: BacktestSettingsConfig): string {
  const entry = strategy.entry_groups
    .flatMap((group) => group.conditions)
    .map((condition) => condition.expression ?? condition.condition_id)
    .join("；");
  const exit = strategy.exit_rules
    .map((condition) => condition.expression ?? condition.condition_id)
    .join("；") || "仅固定持仓/止盈止损";
  return `<p>入场条件（${strategy.entry_groups[0]?.operator ?? "and"}）：${escapeHtml(entry || "无")}</p>
  <p>离场规则：${escapeHtml(exit)}</p>
  <p>区间：${escapeHtml(settings.start_date)} 至 ${escapeHtml(settings.end_date)} · 初始资金 ${settings.initial_cash.toLocaleString("zh-CN")} · 最大持仓 ${settings.max_positions} 只</p>`;
}

export function buildBacktestReportHtml(options: {
  result: BacktestResult;
  strategy: StrategyConfig;
  settings: BacktestSettingsConfig;
  aiCommentary?: string | null;
}): string {
  const { result, strategy, settings, aiCommentary } = options;
  const generatedAt = new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date());
  const aiSection = aiCommentary
    ? `<section><h2>AI 解读</h2><p class="ai-note">${escapeHtml(aiCommentary)}（AI 生成内容，仅供辅助观察，不构成投资建议）</p></section>`
    : "";
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>A股策略回测报告 · ${escapeHtml(generatedAt)}</title>
<style>${REPORT_CSS}</style>
</head>
<body>
<main>
<header>
  <h1>A股策略回测报告</h1>
  <p>生成时间 ${escapeHtml(generatedAt)} · ${escapeHtml(strategy.name || "未命名策略")}</p>
</header>
<section><h2>指标概览</h2>${buildMetricsTable(result)}</section>
<section><h2>历史权益曲线</h2>${buildEquitySvg(result)}</section>
${aiSection}
<section><h2>策略与参数</h2>${buildStrategySummary(strategy, settings)}</section>
<section><h2>交易明细（最多 300 笔）</h2>${buildTradesTable(result)}</section>
<footer>本报告由 A股策略回测工作台 本地生成，历史回测结果不代表未来收益，不构成投资建议。</footer>
</main>
</body>
</html>`;
}

export function downloadBacktestReport(options: {
  result: BacktestResult;
  strategy: StrategyConfig;
  settings: BacktestSettingsConfig;
  aiCommentary?: string | null;
}): void {
  const html = buildBacktestReportHtml(options);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `A股回测报告_${options.result.metrics.trade_count}笔_${new Date().toISOString().slice(0, 10)}.html`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
