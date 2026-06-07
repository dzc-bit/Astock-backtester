import { useEffect, useMemo, useState } from "react";
import {
  ensureDataService,
  fetchDailyBars,
  importDailyBars,
  loadDailyBarsCoverage,
  loadDataServiceHealth,
  loadDataServiceLogs,
  loadSyncJob,
  startFullMarketSync
} from "../api";
import type { DailyBarsCoverageItem, DataServiceStatus, DatasetCoverage, ServiceLogEntry, SyncJobStatus } from "../types";

type Props = {
  cacheDir: string;
  coverage: DatasetCoverage[];
  onCoverageChange: (coverage: DatasetCoverage[]) => void;
  onServiceReady?: (service: DataServiceStatus) => void;
};

type BusyAction = "refresh" | "fetch" | "sample" | "file" | "sync" | null;

function formatLocalDate(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function previousBusinessDay(date: Date): Date {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  while (next.getDay() === 0 || next.getDay() === 6) {
    next.setDate(next.getDate() - 1);
  }
  return next;
}

function recentBusinessDateRange(days = 5): { startDate: string; endDate: string } {
  const end = previousBusinessDay(new Date());
  const start = new Date(end);
  let counted = 1;
  while (counted < days) {
    start.setDate(start.getDate() - 1);
    if (start.getDay() !== 0 && start.getDay() !== 6) {
      counted += 1;
    }
  }
  return { startDate: formatLocalDate(start), endDate: formatLocalDate(end) };
}

function dailyBarsCoverage(coverage: DatasetCoverage[]): DatasetCoverage | undefined {
  return coverage.find((item) => item.dataset === "daily_bars");
}

function coverageFillDateRange(coverage: DatasetCoverage[]): { startDate: string; endDate: string } {
  const fallback = recentBusinessDateRange();
  const daily = dailyBarsCoverage(coverage);
  if (daily?.end_date && daily.symbols >= 100 && daily.end_date < fallback.endDate) {
    return { startDate: daily.end_date, endDate: fallback.endDate };
  }
  return fallback;
}

const datasetLabels: Record<string, { label: string; source: string }> = {
  daily_bars: { label: "日线行情", source: "a-stock-data / 本地缓存" },
  capital_flow: { label: "资金流向", source: "东方财富资金流 / 本地缓存" },
  market_cap: { label: "市值数据", source: "A股基础指标 / 本地缓存" }
};

function formatList(values: string[]): string {
  return values.length === 0 ? "无" : values.join(", ");
}

function operationMessage(logs: { message: string }[]): string {
  return logs.at(-1)?.message ?? "数据操作已完成";
}

function isSyncRunning(job: SyncJobStatus | null): boolean {
  return job?.status === "running";
}

function latestCoverageEndDate(coverage: DatasetCoverage[]): string | null {
  const dailyEndDate = dailyBarsCoverage(coverage)?.end_date;
  if (dailyEndDate) {
    return dailyEndDate;
  }
  const dates = coverage
    .map((item) => item.end_date)
    .filter((value): value is string => Boolean(value))
    .sort();
  return dates.at(-1) ?? null;
}

export function DataCenter({ cacheDir, coverage, onCoverageChange, onServiceReady }: Props) {
  const [service, setService] = useState<DataServiceStatus | null>(null);
  const [symbolsInput, setSymbolsInput] = useState("600519");
  const [startDate, setStartDate] = useState(() => coverageFillDateRange(coverage).startDate);
  const [endDate, setEndDate] = useState(() => coverageFillDateRange(coverage).endDate);
  const [dateRangeTouched, setDateRangeTouched] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [items, setItems] = useState<DailyBarsCoverageItem[]>([]);
  const [logs, setLogs] = useState<ServiceLogEntry[]>([]);
  const [syncJob, setSyncJob] = useState<SyncJobStatus | null>(null);
  const [message, setMessage] = useState("正在连接本地数据服务");
  const [busyAction, setBusyAction] = useState<BusyAction>(null);
  const syncRunning = isSyncRunning(syncJob);
  const busy = busyAction !== null || syncRunning;

  const symbols = useMemo(
    () =>
      symbolsInput
        .split(/[,\s]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    [symbolsInput]
  );

  const reconnectService = async () => {
    const status = await ensureDataService(cacheDir);
    setService(status);
    onServiceReady?.(status);
    await refreshServiceState(status);
    return status;
  };

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

  const applyCoverageDateRange = (nextCoverage: DatasetCoverage[]) => {
    const range = coverageFillDateRange(nextCoverage);
    if (!dateRangeTouched) {
      setStartDate(range.startDate);
      setEndDate(range.endDate);
      return range;
    }
    return { startDate, endDate };
  };

  const refreshServiceState = async (activeService: DataServiceStatus) => {
    const [health, recentLogs] = await Promise.all([
      loadDataServiceHealth(activeService.base_url),
      loadDataServiceLogs(activeService.base_url)
    ]);
    onCoverageChange(health.coverage);
    setLogs(recentLogs.items);
    return applyCoverageDateRange(health.coverage);
  };

  const refreshLogs = async (activeService: DataServiceStatus) => {
    const recentLogs = await loadDataServiceLogs(activeService.base_url);
    setLogs(recentLogs.items);
  };

  useEffect(() => {
    let cancelled = false;
    void ensureDataService(cacheDir)
      .then(async (status) => {
        if (cancelled) {
          return;
        }
        setService(status);
        onServiceReady?.(status);
        setMessage(status.message);
        const range = await refreshServiceState(status);
        await refreshDetails(status, ["600519"], range.startDate, range.endDate);
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

  useEffect(() => {
    const activeSyncJob = syncJob;
    if (!service || !activeSyncJob || !isSyncRunning(activeSyncJob)) {
      return;
    }
    let cancelled = false;
    const timer = window.setInterval(() => {
      void loadSyncJob(service.base_url, activeSyncJob.job_id)
        .then(async (result) => {
          if (cancelled) {
            return;
          }
          setSyncJob(result.job);
          setMessage(
            result.job.status === "running"
              ? `正在下载全市场历史数据，已完成 ${result.job.completed_symbols}/${result.job.total_symbols}`
              : `全市场下载完成，导入 ${result.job.imported_rows} 行`
          );
          if (result.job.status !== "running") {
            await refreshServiceState(service);
          }
        })
        .catch((error: Error) => {
          if (!cancelled) {
            setMessage(error.message);
          }
        });
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [service, syncJob?.job_id, syncJob?.status]);

  const handleRefreshDetails = async () => {
    if (!service) {
      return;
    }
    setBusyAction("refresh");
    setMessage("正在刷新覆盖范围");
    try {
      await refreshDetails(service);
      await refreshServiceState(service);
      setMessage("覆盖范围已刷新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刷新覆盖范围失败");
    } finally {
      setBusyAction(null);
    }
  };

  const handleFetch = async () => {
    if (!service || symbols.length === 0) {
      return;
    }
    setBusyAction("fetch");
    setMessage("正在补全缺失数据");
    try {
      const result = await fetchDailyBars(service.base_url, symbols, startDate, endDate);
      setMessage(operationMessage(result.logs));
      onCoverageChange(result.coverage);
      const nextRange = coverageFillDateRange(result.coverage);
      const fetchedEndDate = latestCoverageEndDate(result.coverage);
      const detailRange = dateRangeTouched
        ? { startDate, endDate: fetchedEndDate && fetchedEndDate > endDate ? fetchedEndDate : endDate }
        : nextRange;
      if (!dateRangeTouched) {
        setStartDate(nextRange.startDate);
        setEndDate(nextRange.endDate);
      } else if (fetchedEndDate && fetchedEndDate > endDate) {
        setEndDate(fetchedEndDate);
      }
      await refreshLogs(service);
      await refreshDetails(service, symbols, detailRange.startDate, detailRange.endDate);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "补全缺失数据失败");
      let activeService = service;
      try {
        activeService = await reconnectService();
      } catch {
        // Keep the original operation error visible if reconnect also fails.
      }
      await refreshLogs(activeService);
    } finally {
      setBusyAction(null);
    }
  };

  const handleImportSample = async () => {
    if (!service) {
      return;
    }
    setBusyAction("sample");
    setMessage("正在导入示例数据");
    try {
      const result = await importDailyBars(service.base_url, "sample");
      setMessage(operationMessage(result.logs));
      onCoverageChange(result.coverage);
      await refreshLogs(service);
      await refreshDetails(service);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入示例数据失败");
      let activeService = service;
      try {
        activeService = await reconnectService();
      } catch {
        // Keep the original operation error visible if reconnect also fails.
      }
      await refreshLogs(activeService);
    } finally {
      setBusyAction(null);
    }
  };

  const handleImportFile = async () => {
    if (!service || !importPath.trim()) {
      return;
    }
    setBusyAction("file");
    setMessage("正在导入本地文件");
    try {
      const result = await importDailyBars(service.base_url, "file", importPath.trim());
      setMessage(operationMessage(result.logs));
      onCoverageChange(result.coverage);
      await refreshLogs(service);
      await refreshDetails(service);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "导入本地文件失败");
      let activeService = service;
      try {
        activeService = await reconnectService();
      } catch {
        // Keep the original operation error visible if reconnect also fails.
      }
      await refreshLogs(activeService);
    } finally {
      setBusyAction(null);
    }
  };

  const handleFullMarketSync = async () => {
    if (!service) {
      return;
    }
    setBusyAction("sync");
    setMessage("正在下载全市场历史数据");
    try {
      const result = await startFullMarketSync(service.base_url, startDate, endDate);
      setSyncJob(result.job);
      if (result.job.status === "running") {
        setMessage(`正在下载全市场历史数据，已完成 ${result.job.completed_symbols}/${result.job.total_symbols}`);
      } else {
        setMessage(`全市场下载完成，导入 ${result.job.imported_rows} 行`);
        await refreshServiceState(service);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "全市场下载失败");
      await refreshLogs(service);
    } finally {
      setBusyAction(null);
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
          {busyAction === "refresh" ? "正在刷新覆盖范围" : "刷新覆盖范围"}
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
            <input
              type="date"
              value={startDate}
              onChange={(event) => {
                setDateRangeTouched(true);
                setStartDate(event.target.value);
              }}
            />
          </label>
          <label>
            结束日期
            <input
              type="date"
              value={endDate}
              onChange={(event) => {
                setDateRangeTouched(true);
                setEndDate(event.target.value);
              }}
            />
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
          <button className="primary-button" type="button" onClick={handleFullMarketSync} disabled={!service || busy}>
            {busyAction === "sync" ? "正在下载全市场历史数据" : "下载全市场历史数据"}
          </button>
          <button className="primary-button" type="button" onClick={handleFetch} disabled={!service || busy || symbols.length === 0}>
            {busyAction === "fetch" ? "正在补全缺失数据" : "补全缺失数据"}
          </button>
          <button className="secondary-button" type="button" onClick={handleImportSample} disabled={!service || busy}>
            {busyAction === "sample" ? "正在导入示例数据" : "导入示例数据"}
          </button>
          <button className="secondary-button" type="button" onClick={handleImportFile} disabled={!service || busy || !importPath.trim()}>
            {busyAction === "file" ? "正在导入本地文件" : "导入本地文件"}
          </button>
        </div>
        <p className={`operation-status ${busy ? "is-busy" : ""}`} role="status" aria-label="数据中心状态">
          {message}
        </p>
        {syncJob ? (
          <div className="sync-progress" role="status">
            <strong>已完成 {syncJob.completed_symbols}/{syncJob.total_symbols}</strong>
            <span>失败 {syncJob.failed_symbols}，导入 {syncJob.imported_rows} 行</span>
            {syncJob.current_symbol ? <span>当前 {syncJob.current_symbol}</span> : null}
            <progress value={syncJob.completed_symbols + syncJob.failed_symbols} max={syncJob.total_symbols || 1} />
          </div>
        ) : null}
        {logs.length > 0 ? (
          <div className="service-log-list" aria-label="本地服务日志">
            {logs.slice(0, 5).map((entry, index) => (
              <span key={`${entry.timestamp ?? index}-${entry.message}`} className={`service-log ${entry.level}`}>
                {entry.message}
              </span>
            ))}
          </div>
        ) : null}
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
                        {item.missing_rows === 0 ? "数据已就绪" : "建议补齐"}
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
            <span>{item.start_date ?? "-"} 至 {item.end_date ?? "-"}，{item.rows} 行</span>
            <span>缺失交易日: {formatList(item.missing_trade_dates)}</span>
            <span>缺失资金流: {formatList(item.missing_capital_flow_dates)}</span>
            <span>缺失市值: {formatList(item.missing_market_cap_dates)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
