import type { DatasetCoverage } from "../types";

type Props = {
  coverage: DatasetCoverage[];
  onRefresh: () => void;
};

const datasetLabels: Record<string, { label: string; source: string }> = {
  daily_bars: { label: "日线行情", source: "a-stock-data / 本地缓存" },
  capital_flow: { label: "资金流向", source: "东方财富资金流 / 本地缓存" },
  market_cap: { label: "市值数据", source: "A股基础指标 / 本地缓存" }
};

export function DataCenter({ coverage, onRefresh }: Props) {
  return (
    <section className="surface data-center">
      <div className="section-title">
        <div>
          <span className="section-kicker">数据健康</span>
          <h2>数据中心</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onRefresh}>刷新覆盖范围</button>
      </div>
      {coverage.length === 0 ? (
        <div className="empty-state">
          <strong>等待数据覆盖信息</strong>
          <span>如果本地缓存为空，运行回测前需要先导入 a-stock-data 历史数据。</span>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>数据集</th>
                <th>股票数</th>
                <th>覆盖日期</th>
                <th>缺失行</th>
                <th>来源状态</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((item) => {
                const meta = datasetLabels[item.dataset] ?? { label: "扩展数据", source: "本地缓存" };
                return (
                  <tr key={item.dataset}>
                    <td>
                      <strong>{meta.label}</strong>
                      <small className="muted-code">本地历史缓存</small>
                    </td>
                    <td>{item.symbols}</td>
                    <td>{item.start_date ?? "-"} 至 {item.end_date ?? "-"}</td>
                    <td>{item.missing_rows}</td>
                    <td>
                      <span className={item.missing_rows === 0 ? "health-pill good" : "health-pill warn"}>
                        {item.missing_rows === 0 ? "覆盖正常" : "需要补齐"}
                      </span>
                      <small>{meta.source}</small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
