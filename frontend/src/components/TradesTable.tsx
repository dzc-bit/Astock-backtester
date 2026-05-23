import type { Trade } from "../types";

type Props = {
  trades: Trade[];
};

export function TradesTable({ trades }: Props) {
  return (
    <section className="surface">
      <h2>Trade Explanations</h2>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Buy</th>
            <th>Sell</th>
            <th>Reason</th>
            <th>PnL</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.symbol}-${trade.buy_date}`}>
              <td>{trade.symbol}</td>
              <td>{trade.buy_date} @ {trade.buy_price}</td>
              <td>{trade.sell_date ?? "-"}</td>
              <td>{trade.buy_reason.join("; ")}</td>
              <td>{trade.pnl_pct == null ? "-" : `${(trade.pnl_pct * 100).toFixed(2)}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
