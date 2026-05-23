import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BacktestResult } from "../types";

type Props = {
  result: BacktestResult | null;
  onRun: () => void;
};

export function ResultsOverview({ result, onRun }: Props) {
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Result Overview</h2>
        <button type="button" onClick={onRun}>Run Demo Backtest</button>
      </div>
      {result ? (
        <>
          <div className="metrics">
            <span>Total return {(result.metrics.total_return_pct * 100).toFixed(2)}%</span>
            <span>Max drawdown {(result.metrics.max_drawdown_pct * 100).toFixed(2)}%</span>
            <span>Win rate {(result.metrics.win_rate_pct * 100).toFixed(2)}%</span>
            <span>Trades {result.metrics.trade_count}</span>
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={result.equity_curve}>
                <XAxis dataKey="trade_date" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="equity" stroke="#1167b1" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <p>No result yet.</p>
      )}
    </section>
  );
}
