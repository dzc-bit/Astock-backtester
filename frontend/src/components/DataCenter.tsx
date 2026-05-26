import { useEffect, useMemo, useState } from "react";
import { ensureDataService, fetchDailyBars, importDailyBars, loadDailyBarsCoverage } from "../api";
import type { DailyBarsCoverageItem, DataServiceStatus, DatasetCoverage } from "../types";

type Props = {
  cacheDir: string;
  coverage: DatasetCoverage[];
  onRefresh: () => Promise<void> | void;
};

const defaultStartDate = "2024-01-02";
const defaultEndDate = "2024-01-08";

const datasetLabels: Record<string, { label: string; source: string }> = {
  daily_bars: { label: "日线行情", source: "a-stock-data / 本地缓存" },
  capital_flow: { label: "资金流向", source: "东方财富资金流 / 本地缓存" },
  market_cap: { label: "市值数据", source: "A股基础指标 / 本地缓存" }
};

function formatList(values: string[]): string {
  return values.length === 0 ? "无" : values.join(", ");
}

export function DataCenter({ cacheDir, coverage, onRefresh }: Props) {
  const [service, setService] = useState<DataServiceStatus | null>(null);
  const [symbolsInput, setSymbolsInput] = useState("600519");
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);
  const [importPath, setImportPath] = useState("");
  const [items, setItems] = useState<DailyBarsCoverageItem[]>([]);
  const [message, setMessage] = useState("正在连接本地数据服务");
  const [busy, setBusy] = useState(false);

  const symbols = useMemo(
    () =>
      symbolsInput
        .split(/[,\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    [symbolsInput]
  );

  const refreshDetails = async (
    activeService: DataServiceStatus,
    selectedSymbols = symbols,
    selectedStartDate = startDate,
    selectedEndDate = endDate
  ) => {
    if (selectedSymbols.length === 0) {
      setItems([]);
      return;
    }
    const response = await loadDailyBarsCoverage(
      activeService.base_url,
      selectedSymbols,
      selectedStartDate,
      selectedEndDate
    );
    setItems(response.items);
  };

  useEffect(() => {
    let cancelled = false;
    void ensureDataService(cacheDir)
      .then(async (status) => {
        if (cancelled) {
          return;
        }
        setService(status);
        setMessage(status.message);
        await refreshDetails(status, ["600519"], defaultStartDate, defaultEndDate);
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setMessage(error.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [cacheDir]);

  const handleRefreshDetails = async () => {
    if (!service) {
      return;
    }
    setBusy(true);
    try {
      await refreshDetails(service);
      setMessage("覆盖范围已刷新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刷新覆盖范围失败");
    } finally {
      setBusy(false);
    }
  };

  const handleFetch = async () => {
    if (!service || symbols.length === 0) {
      return;
    }
    setBusy(true);
    try {
      const result = await fetchDailyBars(service.base_url, symbols, startDate, endDate);
      setMessage(result.message);
      await onRefresh();
      await refreshDetails(service);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "补全缺失数据失败");
    } finally {
      setBusy(false);
    }
  };

  const handleImportSample = async () => {
    if (!service) {
      return;
    }
    setBusy(true);
    try {
      const result = await importDailyBars(service.base_url, "sample");
      setMessage(result.message);
      await onRefresh();
      await refreshDetails(service);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入示例数据失败");
    } finally {
      setBusy(false);
    }
  };

  const handleImportFile = async () => {
    if (!service || !importPath.trim()) {
      return;
    }
    setBusy(true);
    try {
      const result = await importDailyBars(service.base_url, "file", importPath.trim());
      setMessage(result.message);
      await onRefresh();
      await refreshDetails(service);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入本地文件失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="surface data-center">
      <div className="section-title">
        <div>
          <span className="section-kicker">数据健康</span>
          <h2>数据中心</h2>
        </div>
        <button className="secondary-button" type="button" onClick={handleRefreshDetails} disabled={!service || busy}>
          刷新覆盖范围
        </button>
      </div>

      <div className="data-service-panel">
        <div className="service-summary">
          <strong>{service ? "本地服务已连接" : "本地服务未连接"}</strong>
          <span>{service ? `${service.base_url} / ${service.cache_dir}` : message}</span>
        </div>
        <div className="service-form">
          <label>
            股票代码
            <input value={symbolsInput} onChange={(event) => setSymbolsInput(event.target.value)} />
          </label>
          <label>
            开始日期
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>
          <label>
            结束日期
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>
          <label>
            导入文件路径
            <input
              value={importPath}
              onChange={(event) => setImportPath(event.target.value)}
              placeholder="C:\\data\\daily.csv"
            />
          </label>
        </div>
        <div className="service-actions">
          <button className="primary-button" type="button" onClick={handleFetch} disabled={!service || busy || symbols.length === 0}>
            补全缺失数据
          </button>
          <button className="secondary-button" type="button" onClick={handleImportSample} disabled={!service || busy}>
            导入示例数据
          </button>
          <button className="secondary-button" type="button" onClick={handleImportFile} disabled={!service || busy || !importPath.trim()}>
            导入本地文件
          </button>
        </div>
        <p className="muted-code" role="status">
          {message}
        </p>
      </div>

      {coverage.length === 0 ? (
        <div className="empty-state">
          <strong>等待数据覆盖信息</strong>
          <span>如果本地缓存为空，运行回测前需要先导入或补全 a-stock-data 历史数据。</span>
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

      <div className="coverage-details">
        {items.map((item) => (
          <article key={item.symbol} className="coverage-item">
            <strong>{item.symbol}</strong>
            <span>{item.start_date ?? "-"} 至 {item.end_date ?? "-"}，{item.row_count} 行</span>
            <span>缺失日期: {formatList(item.missing_dates)}</span>
            <span>缺失资金流: {formatList(item.missing_capital_flow_dates)}</span>
            <span>缺失市值: {formatList(item.missing_market_cap_dates)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
