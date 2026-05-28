import { Play } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BacktestResult } from "../types";

type Props = {
  result: BacktestResult | null;
  isRunning?: boolean;
  phases?: string[];
  progressMessage?: string | null;
  onRun: () => void;
  riskAlertCount?: number;
  onOpenRiskAlerts: () => void;
};

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
      {isRunning && !result ? (
        <div className="run-live-state">
          <strong>回测正在撮合</strong>
          <span>{progressMessage ?? "正在扫描历史交易日，首笔开仓或平仓会立即写入右侧交易明细。"}</span>
        </div>
      ) : null}
      {result ? (
        <>
          <div className="metrics">
            <span>总收益 {(result.metrics.total_return_pct * 100).toFixed(2)}%</span>
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
          <div className="chart">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={result.equity_curve}>
                <XAxis dataKey="trade_date" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="equity" stroke="#0f766e" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
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
