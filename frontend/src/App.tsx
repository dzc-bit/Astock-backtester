import { useMemo, useState } from "react";
import { defaultStrategy } from "./strategyDefaults";
import type { StrategyConfig } from "./types";

export function App() {
  const [strategy] = useState<StrategyConfig>(defaultStrategy);
  const enabledCount = useMemo(
    () => strategy.market_filters.length + strategy.entry_groups.flatMap((group) => group.conditions).length,
    [strategy]
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>A-Stock Backtester</h1>
          <p>Daily historical strategy research for A-share data.</p>
        </div>
        <strong>{enabledCount} active conditions</strong>
      </header>
      <section className="panel">
        <h2>{strategy.name}</h2>
        <p>Market cap, capital flow, market heat, and technical conditions are ready for editing.</p>
      </section>
    </main>
  );
}
