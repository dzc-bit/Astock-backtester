import type { Trade } from "../types";

type Props = {
  trades: Trade[];
};

function translateReason(reason: string): string {
  if (reason.includes("float market cap")) {
    return reason
      .replace("float market cap", "流通市值")
      .replace("in", "位于区间");
  }
  if (reason.includes("main net inflow")) {
    return reason.replace("main net inflow", "主力净流入");
  }
  if (reason.includes("volume ratio")) {
    return reason.replace("volume ratio", "量比").replace("in", "位于区间");
  }
  if (reason.includes("turnover")) {
    return reason.replace("turnover", "换手率").replace("in", "位于区间");
  }
  if (reason.includes("MACD histogram")) {
    return reason.replace("MACD histogram", "MACD柱线");
  }
  if (reason.includes("return")) {
    return reason.replace("return", "前期涨幅").replace("in", "位于区间");
  }
  if (reason.includes("close") && reason.includes("above MA")) {
    return reason.replace("close", "收盘价").replace("above", "高于");
  }
  if (reason.includes("close") && reason.includes("below MA")) {
    return reason.replace("close", "收盘价").replace("below", "低于");
  }
  if (reason.includes("broke prior") && reason.includes("high")) {
    return reason
      .replace("close", "收盘价")
      .replace("broke prior", "突破前")
      .replace("high", "高点");
  }
  if (reason.includes("broke prior") && reason.includes("low")) {
    return reason
      .replace("close", "收盘价")
      .replace("broke prior", "跌破前")
      .replace("low", "低点");
  }
  if (reason.includes("fixed holding days reached")) {
    return reason.replace("fixed holding days reached", "达到固定持仓天数");
  }
  if (reason.includes("take profit touched")) {
    return reason.replace("take profit touched", "触及止盈");
  }
  if (reason.includes("stop loss touched")) {
    return reason.replace("stop loss touched", "触及止损");
  }
  if (reason.includes("market rising ratio")) {
    return reason.replace("market rising ratio", "市场上涨家数占比");
  }
  if (reason.includes("unavailable before enough history")) {
    return reason.replace("unavailable before enough history", "历史长度不足，暂不可用");
  }
  return "未识别的策略条件说明";
}

export function TradesTable({ trades }: Props) {
  return (
    <section className="surface trades-surface">
      <div className="section-title">
        <div>
          <span className="section-kicker">信号解释</span>
          <h2>交易明细</h2>
        </div>
        <span className="status-pill compact">{trades.length} 笔</span>
      </div>
      <div className="table-wrap trades-scroll">
        <table>
          <thead>
            <tr>
              <th>股票</th>
              <th>买入</th>
              <th>卖出</th>
              <th>触发原因</th>
              <th>收益</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={5}>暂无交易记录</td>
              </tr>
            ) : (
              trades.map((trade) => (
                <tr key={`${trade.symbol}-${trade.buy_date}`}>
                  <td>{trade.symbol}</td>
                  <td>{trade.buy_date} @ {trade.buy_price}</td>
                  <td>{trade.sell_date ?? "持仓中"}</td>
                  <td>{trade.buy_reason.map(translateReason).join("；")}</td>
                  <td className={trade.pnl_pct == null ? "" : trade.pnl_pct >= 0 ? "up-text" : "down-text"}>
                    {trade.pnl_pct == null ? "持仓中" : `${(trade.pnl_pct * 100).toFixed(2)}%`}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
