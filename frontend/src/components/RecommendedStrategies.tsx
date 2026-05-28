import { Sparkles } from "lucide-react";
import type { RecommendedStrategy, StrategyConfig } from "../types";

type Props = {
  items: RecommendedStrategy[];
  disabled?: boolean;
  onApply: (strategy: StrategyConfig) => void;
};

export function RecommendedStrategies({ items, disabled = false, onApply }: Props) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="recommended-strategies" aria-label="推荐策略">
      <div className="recommended-head">
        <Sparkles size={18} aria-hidden="true" />
        <h3>推荐策略</h3>
      </div>
      <div className="recommended-grid">
        {items.map((item) => (
          <article className="recommended-card" key={item.id}>
            <div>
              <strong>{item.name}</strong>
              <p>{item.description}</p>
            </div>
            <small>{item.suitable_market}</small>
            <div className="strategy-chip-row">
              {item.example_conditions.slice(0, 3).map((condition) => (
                <span key={condition}>{condition}</span>
              ))}
            </div>
            <em>{item.risk_note}</em>
            <button className="primary-button" type="button" disabled={disabled} onClick={() => onApply(item.strategy)}>
              套用{item.name}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
