import type { DatasetCoverage } from "../types";

type Props = {
  coverage: DatasetCoverage[];
  onRefresh: () => void;
};

export function DataCenter({ coverage, onRefresh }: Props) {
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Data Center</h2>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Dataset</th>
            <th>Symbols</th>
            <th>Date Range</th>
            <th>Missing Rows</th>
          </tr>
        </thead>
        <tbody>
          {coverage.map((item) => (
            <tr key={item.dataset}>
              <td>{item.dataset}</td>
              <td>{item.symbols}</td>
              <td>{item.start_date ?? "-"} to {item.end_date ?? "-"}</td>
              <td>{item.missing_rows}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
