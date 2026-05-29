import { Sparkles } from "lucide-react";
import type { RecommendedStrategy, StrategyConfig } from "../types";

type StrategyMetadata = {
  scenario: string;
  featured: boolean;
  required_datasets: string[];
  capability_note: string | null;
};

type RecommendedStrategyView = RecommendedStrategy & Partial<StrategyMetadata>;

type Props = {
  items: RecommendedStrategyView[];
  disabled?: boolean;
  onApply: (strategy: StrategyConfig) => void;
};

const datasetLabels: Record<string, string> = {
  daily_bars: "日线行情",
  market_cap: "市值覆盖",
  capital_flow: "资金流"
};

export function RecommendedStrategies({ items, disabled = false, onApply }: Props) {
  if (items.length === 0) {
    return null;
  }

  const featuredItems = items.filter((item) => item.featured).slice(0, 3);
  const scenarioGroups = Array.from(
    items.reduce((groups, item) => {
      const scenario = item.scenario?.trim() || "通用场景";
      const bucket = groups.get(scenario) ?? [];
      bucket.push(item);
      groups.set(scenario, bucket);
      return groups;
    }, new Map<string, RecommendedStrategyView[]>())
  );

  const renderDatasetChips = (item: RecommendedStrategyView) => {
    if (!item.required_datasets?.length) {
      return null;
    }

    return (
      <div className="strategy-chip-row">
        {item.required_datasets.map((dataset) => (
          <span key={`${item.id}-${dataset}`}>{datasetLabels[dataset] ?? dataset}</span>
        ))}
      </div>
    );
  };

  return (
    <section className="recommended-strategies" aria-label="推荐策略">
      {featuredItems.length > 0 ? (
        <section className="recommended-section" aria-label="精选主推">
          <div className="recommended-head">
            <Sparkles size={18} aria-hidden="true" />
            <div>
              <span>精选主推</span>
              <h3>当前可直接运行的策略</h3>
            </div>
          </div>
          <div className="recommended-featured-grid">
            {featuredItems.map((item) => (
              <article className="recommended-card" key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <p>{item.description}</p>
                </div>
                <small>适用行情：{item.suitable_market}</small>
                {renderDatasetChips(item)}
                {item.capability_note ? <p>{item.capability_note}</p> : null}
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
      ) : null}
      <section className="recommended-section" aria-label="按行情场景选择">
        <div className="recommended-head">
          <Sparkles size={18} aria-hidden="true" />
          <div>
            <span>按行情场景选择</span>
            <h3>根据盘面状态找备选策略</h3>
          </div>
        </div>
        <div className="recommended-scenarios">
          {scenarioGroups.map(([scenario, strategies], index) => (
            <section className="scenario-group" aria-labelledby={`recommended-scenario-${index}`} key={scenario}>
              <h4 id={`recommended-scenario-${index}`}>{scenario}</h4>
              <div className="recommended-grid">
                {strategies.map((item) => (
                  <article className="recommended-card" key={item.id}>
                    <div>
                      <strong>{item.name}</strong>
                      <p>{item.description}</p>
                    </div>
                    <small>{item.suitable_market}</small>
                    {renderDatasetChips(item)}
                    {item.capability_note ? <small>{item.capability_note}</small> : null}
                    <div className="strategy-chip-row">
                      {item.example_conditions.slice(0, 2).map((condition) => (
                        <span key={condition}>{condition}</span>
                      ))}
                    </div>
                    <button className="primary-button" type="button" disabled={disabled} onClick={() => onApply(item.strategy)}>
                      套用{item.name}
                    </button>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </section>
    </section>
  );
}
