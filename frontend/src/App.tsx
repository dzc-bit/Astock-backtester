import { useEffect, useState } from "react";
import { Activity, Database, Flame, ShieldAlert, TrendingUp } from "lucide-react";
import { loadCoverage, runConfiguredBacktest } from "./api";
import { BacktestSettings } from "./components/BacktestSettings";
import { DataCenter } from "./components/DataCenter";
import { ResultsOverview } from "./components/ResultsOverview";
import { StrategyEditor } from "./components/StrategyEditor";
import { TradesTable } from "./components/TradesTable";
import { UpdatePanel } from "./components/UpdatePanel";
import { defaultSettings, defaultStrategy } from "./strategyDefaults";
import type { BacktestResult, BacktestSettingsConfig, DatasetCoverage, StrategyConfig } from "./types";

function formatPercent(value: number | null | undefined): string {
  return value == null ? "--" : `${(value * 100).toFixed(2)}%`;
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function translateError(message: string): string {
  if (message.includes("No cached daily bars found")) {
    return "未找到已缓存的日线行情，请先确认 a-stock-data 数据包已导入到本地缓存。";
  }
  if (message.includes("Selected strategy requires capital-flow data")) {
    return "当前策略需要资金流向数据，请检查数据中心的资金流向覆盖情况。";
  }
  if (message.includes("Required column is missing")) {
    return "历史数据字段不完整，请在数据中心补齐所选策略需要的行情、资金或市值字段。";
  }
  if (message.includes("unknown condition_id")) {
    return "策略条件暂不支持，请从条件库中选择已注册的 A 股条件。";
  }
  if (
    message.includes("must be") ||
    message.includes("condition group") ||
    message.includes("strategy must") ||
    message.includes("end_date")
  ) {
    return "回测参数不合法，请检查日期、资金、持仓、费用和止盈止损设置。";
  }
  return "回测运行失败，请检查数据中心覆盖范围和策略参数。";
}

export function App() {
  const [coverage, setCoverage] = useState<DatasetCoverage[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [strategy, setStrategy] = useState<StrategyConfig>(defaultStrategy);
  const [settings, setSettings] = useState<BacktestSettingsConfig>(defaultSettings);
  const [error, setError] = useState<string | null>(null);

  const refreshCoverage = async () => {
    setCoverage(await loadCoverage(".astock-cache"));
  };

  const runBacktest = async () => {
    try {
      setError(null);
      setResult(await runConfiguredBacktest(strategy, settings));
    } catch (caught) {
      setError(caught instanceof Error ? translateError(caught.message) : "回测运行失败。");
    }
  };

  useEffect(() => {
    void refreshCoverage();
  }, []);

  const coverageSymbols = coverage.reduce((sum, item) => sum + item.symbols, 0);
  const heatFilter = strategy.market_filters.find((node) => node.condition_id === "market_rising_ratio_at_least");
  const heatThreshold = typeof heatFilter?.params.min_ratio === "number" ? heatFilter.params.min_ratio : 0.5;
  const hasCapitalFlow = coverage.some((item) => item.dataset === "capital_flow" && item.symbols > 0);
  const issueCount = result?.preflight_issues.length ?? 0;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-copy">
          <span className="eyebrow">A股历史回测</span>
          <h1>A股策略回测工作台</h1>
          <p>基于本地 a-stock-data 历史数据，调参、回滚、查看策略预期收益。</p>
        </div>
        <div className="topbar-actions" aria-label="运行状态">
          <UpdatePanel />
          <span className="status-pill"><Activity size={16} aria-hidden="true" /> 保守日线撮合</span>
          <span className="status-pill"><Database size={16} aria-hidden="true" /> 本地缓存</span>
        </div>
      </header>
      <section className="summary-band" aria-label="工作台概览">
        <article className="summary-card heat-card">
          <div>
            <span>市场热度</span>
            <strong>{formatPercent(heatThreshold)}</strong>
          </div>
          <Flame size={24} aria-hidden="true" />
          <small>入场前要求上涨家数占比达到阈值</small>
        </article>
        <article className="summary-card">
          <div>
            <span>资金流向</span>
            <strong>{hasCapitalFlow ? "已接入" : "待导入"}</strong>
          </div>
          <TrendingUp size={24} aria-hidden="true" />
          <small>{hasCapitalFlow ? "主力净流入可参与筛选" : "资金面条件会提示缺失风险"}</small>
        </article>
        <article className="summary-card">
          <div>
            <span>收益表现</span>
            <strong>{formatPercent(result?.metrics.total_return_pct)}</strong>
          </div>
          <Activity size={24} aria-hidden="true" />
          <small>最大回撤 {formatPercent(result?.metrics.max_drawdown_pct)}</small>
        </article>
        <article className="summary-card">
          <div>
            <span>风险提示</span>
            <strong>{issueCount === 0 ? "0项" : `${issueCount}项`}</strong>
          </div>
          <ShieldAlert size={24} aria-hidden="true" />
          <small>当前覆盖股票数 {formatCompact(coverageSymbols)}</small>
        </article>
      </section>
      <div className="workspace">
        <DataCenter coverage={coverage} onRefresh={refreshCoverage} />
        <BacktestSettings settings={settings} onSettingsChange={setSettings} />
        <StrategyEditor strategy={strategy} onStrategyChange={setStrategy} />
        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        <ResultsOverview result={result} onRun={runBacktest} />
        <TradesTable trades={result?.trades ?? []} />
      </div>
    </main>
  );
}
