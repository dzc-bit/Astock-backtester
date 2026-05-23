import { useEffect, useState } from "react";
import { loadCoverage, runDemoBacktest } from "./api";
import { BacktestSettings } from "./components/BacktestSettings";
import { DataCenter } from "./components/DataCenter";
import { ResultsOverview } from "./components/ResultsOverview";
import { StrategyEditor } from "./components/StrategyEditor";
import { TradesTable } from "./components/TradesTable";
import { defaultStrategy } from "./strategyDefaults";
import type { BacktestResult, DatasetCoverage } from "./types";

export function App() {
  const [coverage, setCoverage] = useState<DatasetCoverage[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);

  const refreshCoverage = async () => {
    setCoverage(await loadCoverage(".astock-cache"));
  };

  const runBacktest = async () => {
    setResult(await runDemoBacktest());
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
        <StrategyEditor strategy={defaultStrategy} />
        <BacktestSettings />
        <ResultsOverview result={result} onRun={runBacktest} />
        <TradesTable trades={result?.trades ?? []} />
      </div>
    </main>
  );
}
