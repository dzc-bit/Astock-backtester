import { conditionLibrary } from "../strategyDefaults";
import type { StrategyConfig } from "../types";

type Props = {
  strategy: StrategyConfig;
};

export function StrategyEditor({ strategy }: Props) {
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
        </div>
      </div>
    </section>
  );
}
