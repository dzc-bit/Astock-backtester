import { conditionLibrary } from "../strategyDefaults";
import type { StrategyConfig } from "../types";

type Props = {
  strategy: StrategyConfig;
  onStrategyChange: (strategy: StrategyConfig) => void;
};

function numberParam(strategy: StrategyConfig, conditionId: string, param: string): number {
  const condition = strategy.entry_groups.flatMap((group) => group.conditions).find((node) => node.condition_id === conditionId);
  const value = condition?.params[param];
  return typeof value === "number" ? value : Number(value ?? 0);
}

export function StrategyEditor({ strategy, onStrategyChange }: Props) {
  const updateEntryParam = (conditionId: string, param: string, value: number) => {
    onStrategyChange({
      ...strategy,
      entry_groups: strategy.entry_groups.map((group) => ({
        ...group,
        conditions: group.conditions.map((condition) =>
          condition.condition_id === conditionId
            ? { ...condition, params: { ...condition.params, [param]: value } }
            : condition
        )
      }))
    });
  };

  return (
    <section className="surface">
      <div className="section-title">
        <h2>Strategy Editor</h2>
        <span>{strategy.name}</span>
      </div>
      <div className="strategy-grid">
        <div>
          <h3>Condition Library</h3>
          <input aria-label="Search indicators, market cap, capital flow" />
          <ul className="condition-list">
            {conditionLibrary.map((condition) => (
              <li key={condition.id}>
                <strong>{condition.label}</strong>
                <small>{condition.category}</small>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Entry Groups</h3>
          {strategy.entry_groups.map((group) => (
            <div className="group" key={group.id}>
              <strong>{group.operator.toUpperCase()}</strong>
              {group.conditions.map((condition) => (
                <p key={condition.id}>{condition.condition_id}</p>
              ))}
            </div>
          ))}
          <div className="parameter-panel">
            <h3>Core Parameters</h3>
            <label>
              Minimum float market cap
              <input
                aria-label="Minimum float market cap"
                type="number"
                value={numberParam(strategy, "market_cap_between", "min")}
                onChange={(event) => updateEntryParam("market_cap_between", "min", Number(event.target.value))}
              />
            </label>
            <label>
              Maximum float market cap
              <input
                aria-label="Maximum float market cap"
                type="number"
                value={numberParam(strategy, "market_cap_between", "max")}
                onChange={(event) => updateEntryParam("market_cap_between", "max", Number(event.target.value))}
              />
            </label>
            <label>
              N-day main net inflow minimum
              <input
                aria-label="N-day main net inflow minimum"
                type="number"
                value={numberParam(strategy, "capital_flow_n_day_sum_at_least", "min")}
                onChange={(event) => updateEntryParam("capital_flow_n_day_sum_at_least", "min", Number(event.target.value))}
              />
            </label>
            <label>
              Volume ratio minimum
              <input
                aria-label="Volume ratio minimum"
                type="number"
                step="0.1"
                value={numberParam(strategy, "volume_ratio_between", "min")}
                onChange={(event) => updateEntryParam("volume_ratio_between", "min", Number(event.target.value))}
              />
            </label>
          </div>
        </div>
      </div>
    </section>
  );
}
