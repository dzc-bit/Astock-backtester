import { useEffect, useState } from "react";
import { loadCoverage, runConfiguredBacktest } from "./api";
import { BacktestSettings } from "./components/BacktestSettings";
import { DataCenter } from "./components/DataCenter";
import { ResultsOverview } from "./components/ResultsOverview";
import { StrategyEditor } from "./components/StrategyEditor";
import { TradesTable } from "./components/TradesTable";
import { defaultSettings, defaultStrategy } from "./strategyDefaults";
import type { BacktestResult, BacktestSettingsConfig, DatasetCoverage, StrategyConfig } from "./types";

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
      setError(caught instanceof Error ? caught.message : "Backtest failed.");
    }
  };

  useEffect(() => {
    void refreshCoverage();
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>A-Stock Backtester</h1>
          <p>Daily historical strategy research for A-share data.</p>
        </div>
        <strong>Conservative daily backtest</strong>
      </header>
      <div className="workspace">
        <DataCenter coverage={coverage} onRefresh={refreshCoverage} />
        <StrategyEditor strategy={strategy} onStrategyChange={setStrategy} />
        <BacktestSettings settings={settings} onSettingsChange={setSettings} />
        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        <ResultsOverview result={result} onRun={runBacktest} />
        <TradesTable trades={result?.trades ?? []} />
      </div>
    </main>
  );
}
