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

const conditionLabelById = Object.fromEntries(conditionLibrary.map((condition) => [condition.id, condition.label]));

const operatorLabels = {
  and: "全部满足",
  or: "任一满足",
  score: "评分达标"
};

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
    <section className="surface strategy-surface">
      <div className="section-title">
        <div>
          <span className="section-kicker">人工可调策略</span>
          <h2>策略条件</h2>
        </div>
        <span className="strategy-name">{strategy.name}</span>
      </div>
      <div className="strategy-grid">
        <div className="condition-library">
          <h3>条件库</h3>
          <input aria-label="搜索指标、市值、资金流向" placeholder="搜索 MACD、量比、换手率、形态..." />
          <ul className="condition-list">
            {conditionLibrary.map((condition) => (
              <li key={condition.id}>
                <strong>{condition.label}</strong>
                <small>{condition.category}</small>
              </li>
            ))}
          </ul>
        </div>
        <div className="active-strategy">
          <h3>入场组合</h3>
          {strategy.entry_groups.map((group) => (
            <div className="group" key={group.id}>
              <strong>{operatorLabels[group.operator]}</strong>
              {group.conditions.map((condition) => (
                <p key={condition.id}>{conditionLabelById[condition.condition_id] ?? condition.condition_id}</p>
              ))}
            </div>
          ))}
          <div className="parameter-panel">
            <h3>核心参数</h3>
            <label>
              流通市值下限
              <input
                aria-label="流通市值下限"
                type="number"
                value={numberParam(strategy, "market_cap_between", "min")}
                onChange={(event) => updateEntryParam("market_cap_between", "min", Number(event.target.value))}
              />
            </label>
            <label>
              流通市值上限
              <input
                aria-label="流通市值上限"
                type="number"
                value={numberParam(strategy, "market_cap_between", "max")}
                onChange={(event) => updateEntryParam("market_cap_between", "max", Number(event.target.value))}
              />
            </label>
            <label>
              近N日主力净流入下限
              <input
                aria-label="近N日主力净流入下限"
                type="number"
                value={numberParam(strategy, "capital_flow_n_day_sum_at_least", "min")}
                onChange={(event) => updateEntryParam("capital_flow_n_day_sum_at_least", "min", Number(event.target.value))}
              />
            </label>
            <label>
              量比下限
              <input
                aria-label="量比下限"
                type="number"
                step="0.1"
                value={numberParam(strategy, "volume_ratio_between", "min")}
                onChange={(event) => updateEntryParam("volume_ratio_between", "min", Number(event.target.value))}
              />
            </label>
          </div>
          <div className="strategy-note">
            <strong>可扩展方向</strong>
            <span>后续可把条件库项目拖入组合，并为每个条件独立设置窗口、阈值和数据滞后天数。</span>
          </div>
        </div>
      </div>
    </section>
  );
}
