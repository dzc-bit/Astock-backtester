import { Play } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BacktestResult } from "../types";

type Props = {
  result: BacktestResult | null;
  onRun: () => void;
};

export function ResultsOverview({ result, onRun }: Props) {
  const issueCount = result?.preflight_issues.length ?? 0;

  return (
    <section className="surface results-surface">
      <div className="section-title">
        <div>
          <span className="section-kicker">策略收益与风险</span>
          <h2>收益概览</h2>
        </div>
        <button className="primary-button" type="button" onClick={onRun}>
          <Play size={16} aria-hidden="true" />
          运行历史回测
        </button>
      </div>
      {result ? (
        <>
          <div className="metrics">
            <span>总收益 {(result.metrics.total_return_pct * 100).toFixed(2)}%</span>
            <span>最大回撤 {(result.metrics.max_drawdown_pct * 100).toFixed(2)}%</span>
            <span>胜率 {(result.metrics.win_rate_pct * 100).toFixed(2)}%</span>
            <span>交易次数 {result.metrics.trade_count}</span>
          </div>
          <div className="risk-strip">
            <strong>风险提示</strong>
            <span>{issueCount === 0 ? "数据预检未发现阻断项" : `发现 ${issueCount} 条数据或策略预检提示`}</span>
            <span>资金校准：{result.trades.some((trade) => trade.buy_reason.some((reason) => reason.includes("inflow"))) ? "已使用资金面条件" : "未使用资金面校准"}</span>
          </div>
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
      ) : (
        <div className="empty-state">
          <strong>尚未运行回测</strong>
          <span>调整策略和参数后，点击“运行历史回测”查看收益曲线、回撤和交易原因。</span>
        </div>
      )}
    </section>
  );
}
