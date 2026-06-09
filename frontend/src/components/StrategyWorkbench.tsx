import { CheckCircle2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { isBuiltInStrategyPreset } from "../savedStrategies";
import { conditionLibrary, defaultStrategy } from "../strategyDefaults";
import type {
  BacktestSettingsConfig,
  ConditionNode,
  ConditionValidationResult,
  DatasetCoverage,
  RecommendedStrategy,
  SavedStrategyPreset,
  StrategyConfig
} from "../types";
import { RecommendedStrategies } from "./RecommendedStrategies";

type Props = {
  coverage: DatasetCoverage[];
  settings: BacktestSettingsConfig;
  strategy: StrategyConfig;
  onSettingsChange: (settings: BacktestSettingsConfig) => void;
  onStrategyChange: (strategy: StrategyConfig) => void;
  disabled?: boolean;
  conditionValidation: ConditionValidationResult | null;
  isValidatingCondition?: boolean;
  validationExamples: string[];
  recommendedStrategies: RecommendedStrategy[];
  savedStrategies: SavedStrategyPreset[];
  strategySaveMessage?: string | null;
  pendingStrategySaveName?: string | null;
  onValidateCondition: (text: string) => void;
  validateConditionText: (text: string, mode?: "entry" | "exit") => Promise<ConditionValidationResult>;
  onApplySavedStrategy: (preset: SavedStrategyPreset) => void;
  onDeleteSavedStrategy: (presetId: string) => void;
  onConfirmPendingStrategySave?: () => void;
  onDismissPendingStrategySave?: () => void;
  onSettingsDraftErrorsChange?: (errors: string[]) => void;
};

type ParamType = "currency" | "days" | "number" | "percent";

type ConditionParam = {
  key: string;
  label: string;
  type: ParamType;
  options: number[];
};

type ConditionMeta = {
  id: string;
  label: string;
  category: string;
  params: ConditionParam[];
};

const conditionExamplesById: Record<string, string> = {
  market_rising_ratio_at_least: "市场上涨家数占比大于55%",
  market_cap_between: "流通市值10亿到300亿",
  capital_flow_n_day_sum_at_least: "近3日主力净流入大于300万",
  capital_flow_today_at_least: "当日主力净流入大于300万",
  capital_flow_n_day_positive_count_at_least: "近3日主力净流入为正至少2天",
  macd_histogram_at_least: "MACD柱线大于0",
  close_above_ma: "收盘价站上20日均线",
  close_below_ma: "收盘价跌破3日均线",
  volume_ratio_between: "量比2日介于1.2到2.5",
  turnover_between: "换手率2%到8%",
  past_return_between: "近5日涨幅0%到12%",
  past_return_at_most: "近5日涨幅小于12%",
  breakout_above_n_day_high: "突破20日新高",
  breakdown_below_n_day_low: "跌破20日低点"
};

const stockPools = [
  { value: "all", label: "全A" },
  { value: "main_board", label: "沪深主板" },
  { value: "gem", label: "创业板" },
  { value: "star", label: "科创板" },
  { value: "beijing", label: "北交所" },
  { value: "custom", label: "自选代码" }
] as const;

const positionSizingModes = [
  { value: "fixed_ratio", label: "单股固定仓位" },
  { value: "equal_slots", label: "按剩余仓位等分" }
] as const;

const conditionMetaById = Object.fromEntries(
  (conditionLibrary as ConditionMeta[]).map((condition) => [condition.id, condition])
);
conditionMetaById.close_below_ma = {
  id: "close_below_ma",
  label: "收盘价跌破均线",
  category: "趋势",
  params: [{ key: "window", label: "均线周期", type: "days", options: [3, 5, 10, 20, 60] }]
};
conditionMetaById.breakdown_below_n_day_low = {
  id: "breakdown_below_n_day_low",
  label: "跌破前低离场",
  category: "离场",
  params: [{ key: "window", label: "前低窗口", type: "days", options: [10, 20, 40, 60] }]
};

const operatorLabels = {
  and: "全部满足",
  or: "任一满足",
  score: "评分达标"
};

const defaultExamples = [
  "收盘价站上20日均线",
  "量比2日介于1.2到2.5",
  "流通市值10亿到300亿",
  "换手率2%到8%",
  "近3日主力净流入大于300万",
  "突破20日新高"
];

const entryTemplates = [
  "收盘价站上N日均线",
  "量比N日介于A到B",
  "流通市值X亿到Y亿",
  "换手率A%到B%",
  "近N日涨幅小于X%",
  "近N日主力净流入大于X万/亿",
  "突破N日新高",
  "MACD柱线大于X"
];

const exitExamples = [
  "收盘价跌破3日均线",
  "跌破20日低点",
  "突破20日最低",
  "创20日新低"
];

const exitTemplates = ["收盘价跌破N日均线", "跌破N日低点", "创N日新低"];

const numericSettingLabels: Partial<Record<keyof BacktestSettingsConfig, string>> = {
  initial_cash: "初始资金",
  position_size_pct: "单股仓位比例",
  fixed_holding_days: "固定持仓天数",
  max_positions: "最大持仓数",
  max_daily_buys: "每日最多买入",
  take_profit_pct: "止盈比例",
  stop_loss_pct: "止损比例",
  slippage_rate: "滑点比例",
  fee_rate: "手续费率",
  min_listing_days: "最少上市天数"
};

function formatOption(value: number, type: ParamType): string {
  if (type === "percent") {
    return `${(value * 100).toFixed(value < 0.01 && value > -0.01 ? 2 : 0)}%`;
  }
  if (type === "currency") {
    if (Math.abs(value) >= 100000000) {
      return `${(value / 100000000).toFixed(value % 100000000 === 0 ? 0 : 1)}亿`;
    }
    return `${(value / 10000).toFixed(0)}万`;
  }
  if (type === "days") {
    return `${value}日`;
  }
  return String(value);
}

function formatParamValue(value: number | string | boolean, type?: ParamType): string {
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (typeof value === "number") {
    return formatOption(value, type ?? "number");
  }
  return String(value);
}

function describeConditionParams(condition: ConditionNode, meta?: ConditionMeta): string {
  const params = Object.entries(condition.params);
  if (params.length === 0) {
    return "无额外参数";
  }
  return params
    .map(([key, value]) => {
      const param = meta?.params.find((item) => item.key === key);
      return `${param?.label ?? key}: ${formatParamValue(value, param?.type)}`;
    })
    .join(" / ");
}

function readableConditionText(condition: ConditionNode, meta?: ConditionMeta): string {
  return condition.expression ?? conditionExamplesById[condition.condition_id] ?? meta?.label ?? "自定义条件";
}

function describeSellRule(condition: ConditionNode, meta?: ConditionMeta): string {
  const text = readableConditionText(condition, meta);
  const params = describeConditionParams(condition, meta);
  return params === "无额外参数" ? text : `${text}（${params}）`;
}

function parseSymbols(value: string): string[] {
  return value
    .split(/[,\s，、]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function settingDateRange(coverage: DatasetCoverage[]): { min?: string; max?: string } {
  const daily = coverage.find((item) => item.dataset === "daily_bars");
  const today = new Date().toISOString().slice(0, 10);
  const max = daily?.end_date && daily.end_date < today ? daily.end_date : today;
  return {
    min: daily?.start_date ?? undefined,
    max
  };
}

function firstGroup(strategy: StrategyConfig) {
  return strategy.entry_groups[0] ?? { id: "entry", operator: "and" as const, conditions: [] };
}

function buildCondition(conditionId: string, index: number): ConditionNode {
  const meta = conditionMetaById[conditionId] as ConditionMeta | undefined;
  const params = Object.fromEntries((meta?.params ?? []).map((param) => [param.key, param.options[Math.min(1, param.options.length - 1)]]));
  return {
    id: `${conditionId}-${Date.now()}-${index}`,
    condition_id: conditionId,
    enabled: true,
    params,
    data_lag_days: 0,
    weight: null
  };
}

function cloneCondition(condition: ConditionNode, index: number): ConditionNode {
  return {
    ...condition,
    id: `${condition.condition_id}-${Date.now()}-${index}`,
    enabled: true
  };
}

function conditionSignature(condition: ConditionNode): string {
  return JSON.stringify({
    condition_id: condition.condition_id,
    data_lag_days: condition.data_lag_days,
    params: Object.fromEntries(Object.entries(condition.params).sort(([left], [right]) => left.localeCompare(right)))
  });
}

function validateDrafts(drafts: Record<string, string>): string[] {
  return Object.entries(drafts).flatMap(([key, value]) => {
    const label = numericSettingLabels[key as keyof BacktestSettingsConfig] ?? key;
    if (value.trim() === "") {
      return [`${label}不能为空。`];
    }
    if (!Number.isFinite(Number(value))) {
      return [`${label}必须是数字。`];
    }
    return [];
  });
}

function formatSavedTime(value: string): string {
  if (value === "builtin") {
    return "内置基础策略";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function StrategyWorkbench({
  coverage,
  settings,
  strategy,
  onSettingsChange,
  onStrategyChange,
  disabled = false,
  conditionValidation,
  isValidatingCondition = false,
  validationExamples,
  recommendedStrategies,
  savedStrategies,
  strategySaveMessage = null,
  pendingStrategySaveName = null,
  onValidateCondition,
  validateConditionText,
  onApplySavedStrategy,
  onDeleteSavedStrategy,
  onConfirmPendingStrategySave,
  onDismissPendingStrategySave,
  onSettingsDraftErrorsChange
}: Props) {
  const dateRange = settingDateRange(coverage);
  const examples = validationExamples.length > 0 ? validationExamples : defaultExamples;
  const [conditionText, setConditionText] = useState(examples[0]);
  const [exitConditionText, setExitConditionText] = useState("收盘价跌破3日均线");
  const [exitValidation, setExitValidation] = useState<ConditionValidationResult | null>(null);
  const [isValidatingExit, setIsValidatingExit] = useState(false);
  const [customSymbolsText, setCustomSymbolsText] = useState(settings.custom_symbols.join(","));
  const [settingDrafts, setSettingDrafts] = useState<Record<string, string>>({});
  const [entryAddMessage, setEntryAddMessage] = useState<string | null>(null);
  const [exitAddMessage, setExitAddMessage] = useState<string | null>(null);
  const group = firstGroup(strategy);

  const updateSettings = (patch: Partial<BacktestSettingsConfig>) => {
    onSettingsChange({ ...settings, ...patch });
  };

  const updateNumericSetting = <Key extends keyof BacktestSettingsConfig>(
    key: Key,
    value: string,
    transform: (input: number) => BacktestSettingsConfig[Key] = (input) => input as BacktestSettingsConfig[Key]
  ) => {
    const nextDrafts = { ...settingDrafts, [String(key)]: value };
    setSettingDrafts(nextDrafts);
    onSettingsDraftErrorsChange?.(validateDrafts(nextDrafts));
    if (value.trim() === "") {
      return;
    }
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      return;
    }
    updateSettings({ [key]: transform(parsed) } as Partial<BacktestSettingsConfig>);
  };

  const percentValue = (value: number | null, fallback: number): string => String(((value ?? fallback) * 100).toFixed(2).replace(/\.?0+$/, ""));
  const settingValue = (key: keyof BacktestSettingsConfig, fallback: string): string => settingDrafts[String(key)] ?? fallback;

  const updateGroup = (patch: Partial<typeof group>) => {
    onStrategyChange({
      ...strategy,
      entry_groups: [
        {
          ...group,
          ...patch
        },
        ...strategy.entry_groups.slice(1)
      ]
    });
  };

  const updateCondition = (conditionId: string, patch: Partial<ConditionNode>) => {
    updateGroup({
      conditions: group.conditions.map((condition) =>
        condition.id === conditionId ? { ...condition, ...patch } : condition
      )
    });
  };

  const addValidatedCondition = () => {
    if (!conditionValidation?.ok || !conditionValidation.condition) {
      return;
    }
    const nextSignature = conditionSignature(conditionValidation.condition);
    const duplicate = group.conditions.find((condition) => conditionSignature(condition) === nextSignature);
    if (duplicate) {
      setEntryAddMessage("该入场条件已存在，不会重复加入。");
      if (conditionValidation.condition.expression && !duplicate.expression) {
        updateCondition(duplicate.id, { expression: conditionValidation.condition.expression });
      }
      return;
    }
    const next = cloneCondition(conditionValidation.condition, group.conditions.length);
    setEntryAddMessage("已加入入场条件。");
    updateGroup({
      conditions: [...group.conditions, next]
    });
  };

  const validateExitCondition = async () => {
    setIsValidatingExit(true);
    try {
      setExitValidation(await validateConditionText(exitConditionText, "exit"));
    } catch (caught) {
      setExitValidation({
        ok: false,
        normalized_text: exitConditionText.trim(),
        condition: null,
        errors: [{ code: "request_failed", message: caught instanceof Error ? caught.message : "离场条件校验失败。" }],
        examples: exitExamples
      });
    } finally {
      setIsValidatingExit(false);
    }
  };

  const addValidatedExitCondition = () => {
    if (!exitValidation?.ok || !exitValidation.condition) {
      return;
    }
    const nextSignature = conditionSignature(exitValidation.condition);
    const duplicate = strategy.exit_rules.find((condition) => conditionSignature(condition) === nextSignature);
    if (duplicate) {
      setExitAddMessage("该离场条件已存在，不会重复加入。");
      if (exitValidation.condition.expression && !duplicate.expression) {
        onStrategyChange({
          ...strategy,
          exit_rules: strategy.exit_rules.map((condition) =>
            condition.id === duplicate.id ? { ...condition, expression: exitValidation.condition?.expression } : condition
          )
        });
      }
      return;
    }
    setExitAddMessage("已加入离场条件。");
    onStrategyChange({
      ...strategy,
      exit_rules: [...strategy.exit_rules, cloneCondition(exitValidation.condition, strategy.exit_rules.length)]
    });
  };

  const removeExitCondition = (conditionId: string) => {
    onStrategyChange({
      ...strategy,
      exit_rules: strategy.exit_rules.filter((condition) => condition.id !== conditionId)
    });
  };

  const removeCondition = (conditionId: string) => {
    const next = group.conditions.filter((condition) => condition.id !== conditionId);
    updateGroup({ conditions: next.length > 0 ? next : [buildCondition("market_cap_between", 0)] });
  };

  const applyCoverageDates = () => {
    updateSettings({
      start_date: dateRange.min ?? settings.start_date,
      end_date: dateRange.max ?? settings.end_date
    });
  };

  const resetStrategy = () => {
    setEntryAddMessage(null);
    setExitAddMessage(null);
    onStrategyChange(defaultStrategy);
  };

  const applyRecommendedStrategy = (nextStrategy: StrategyConfig) => {
    onStrategyChange(nextStrategy);
  };

  return (
    <section className="surface strategy-workbench">
      <fieldset className="workbench-fieldset" disabled={disabled}>
      <div className="section-title">
        <div>
          <span className="section-kicker">策略与历史回滚配置</span>
          <h2>策略配置</h2>
        </div>
        <button className="secondary-button" type="button" onClick={resetStrategy}>
          <RotateCcw size={16} aria-hidden="true" />
          重置策略
        </button>
      </div>
      <div className="section-aliases" aria-label="原配置模块">
        <h3>回测设置</h3>
        <h3>策略条件</h3>
      </div>
      {strategySaveMessage ? (
        <div className="strategy-save-banner">
          <div>
            <strong>{strategySaveMessage}</strong>
            {pendingStrategySaveName ? <span>建议名称：{pendingStrategySaveName}</span> : null}
          </div>
          {pendingStrategySaveName && onConfirmPendingStrategySave && onDismissPendingStrategySave ? (
            <div className="strategy-save-actions">
              <button className="primary-button compact" type="button" onClick={onConfirmPendingStrategySave}>
                保存策略
              </button>
              <button className="secondary-button compact" type="button" onClick={onDismissPendingStrategySave}>
                暂不保存
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <section className="saved-strategies-panel" aria-label="已保存策略">
        <div className="saved-strategies-head">
          <div>
            <span className="section-kicker">运行完成后可保存到这里</span>
            <h3>已保存策略</h3>
          </div>
          <span className="status-pill compact">{savedStrategies.length} 个</span>
        </div>
        {savedStrategies.length === 0 ? (
          <div className="saved-strategy-empty">
            完成入场规则、离场规则并运行回测后，可选择把当前策略保存到这里，后续可以一键再次套用。
          </div>
        ) : (
          <div className="saved-strategy-grid">
            {savedStrategies.map((preset) => {
              const presetGroup = firstGroup(preset.strategy);
              return (
                <article className="saved-strategy-card" key={preset.id}>
                  <div className="saved-strategy-copy">
                    <strong>{preset.name}</strong>
                    <small>保存于 {formatSavedTime(preset.saved_at)}</small>
                    <p>
                      入场 {presetGroup.conditions.length} 条 / 离场 {preset.strategy.exit_rules.length} 条
                    </p>
                  </div>
                  <div className="strategy-chip-row">
                    {presetGroup.conditions.slice(0, 2).map((condition) => {
                      const meta = conditionMetaById[condition.condition_id] as ConditionMeta | undefined;
                      return <span key={condition.id}>{readableConditionText(condition, meta)}</span>;
                    })}
                    {preset.strategy.exit_rules[0] ? (
                      <span>
                        离场：
                        {readableConditionText(
                          preset.strategy.exit_rules[0],
                          conditionMetaById[preset.strategy.exit_rules[0].condition_id] as ConditionMeta | undefined
                        )}
                      </span>
                    ) : null}
                  </div>
                  <div className="saved-strategy-actions">
                    <button
                      className="primary-button"
                      type="button"
                      onClick={() => onApplySavedStrategy(preset)}
                      aria-label={`套用已保存策略${preset.name}`}
                    >
                      套用已保存策略
                    </button>
                    {isBuiltInStrategyPreset(preset.id) ? null : (
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => onDeleteSavedStrategy(preset.id)}
                        aria-label={`删除已保存策略${preset.name}`}
                      >
                        删除
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <RecommendedStrategies
        items={recommendedStrategies}
        disabled={disabled}
        onApply={applyRecommendedStrategy}
      />

      <div className="workbench-grid">
        <div className="config-panel">
          <h3>回测范围</h3>
          <div className="settings-grid">
            <label>
              股票池
              <select
                aria-label="股票池"
                value={settings.stock_pool}
                onChange={(event) => updateSettings({ stock_pool: event.target.value as BacktestSettingsConfig["stock_pool"] })}
              >
                {stockPools.map((pool) => (
                  <option key={pool.value} value={pool.value}>
                    {pool.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              自选代码
              <input
                aria-label="自选代码"
                disabled={settings.stock_pool !== "custom"}
                value={customSymbolsText}
                onChange={(event) => {
                  setCustomSymbolsText(event.target.value);
                  updateSettings({ custom_symbols: parseSymbols(event.target.value) });
                }}
                placeholder="600519, 000001"
              />
            </label>
            <label>
              开始日期
              <input
                type="date"
                min={dateRange.min}
                max={dateRange.max}
                value={settings.start_date}
                onChange={(event) => updateSettings({ start_date: event.target.value })}
              />
            </label>
            <label>
              结束日期
              <input
                type="date"
                min={dateRange.min}
                max={dateRange.max}
                value={settings.end_date}
                onChange={(event) => updateSettings({ end_date: event.target.value })}
              />
            </label>
          </div>
          <div className="inline-actions">
            <button className="secondary-button" type="button" onClick={applyCoverageDates} disabled={!dateRange.min || !dateRange.max}>
              套用数据中心日期
            </button>
            <span className="muted-code">
              可用范围 {dateRange.min ?? "-"} 至 {dateRange.max ?? "-"}
            </span>
          </div>
        </div>

        <div className="config-panel">
          <h3>资金与撮合</h3>
          <div className="settings-grid">
            <label>
              初始资金
              <span className="setting-example">样例：100000</span>
              <input
                type="number"
                aria-label="初始资金"
                min={1}
                step={10000}
                value={settingValue("initial_cash", String(settings.initial_cash))}
                onChange={(event) => updateNumericSetting("initial_cash", event.target.value)}
              />
            </label>
            <label>
              固定持仓天数
              <span className="setting-example">样例：3</span>
              <input
                type="number"
                aria-label="固定持仓天数"
                min={1}
                step={1}
                value={settingValue("fixed_holding_days", String(settings.fixed_holding_days))}
                onChange={(event) => updateNumericSetting("fixed_holding_days", event.target.value, Math.round)}
              />
            </label>
            <label>
              仓位模式
              <span className="setting-example">固定仓位更贴近实盘</span>
              <select
                aria-label="仓位模式"
                value={settings.position_sizing_mode}
                onChange={(event) => updateSettings({ position_sizing_mode: event.target.value as BacktestSettingsConfig["position_sizing_mode"] })}
              >
                {positionSizingModes.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              单股仓位（%）
              <span className="setting-example">样例：20</span>
              <input
                type="number"
                aria-label="单股仓位（%）"
                min={0.1}
                max={100}
                step={1}
                value={settingValue("position_size_pct", percentValue(settings.position_size_pct, 0.2))}
                onChange={(event) => updateNumericSetting("position_size_pct", event.target.value, (value) => value / 100)}
              />
            </label>
            <label>
              最大持仓数
              <span className="setting-example">样例：5</span>
              <input
                type="number"
                aria-label="最大持仓数"
                min={1}
                step={1}
                value={settingValue("max_positions", String(settings.max_positions))}
                onChange={(event) => updateNumericSetting("max_positions", event.target.value, Math.round)}
              />
            </label>
            <label>
              每日最多买入
              <span className="setting-example">样例：2</span>
              <input
                type="number"
                aria-label="每日最多买入"
                min={1}
                step={1}
                value={settingValue("max_daily_buys", String(settings.max_daily_buys))}
                onChange={(event) => updateNumericSetting("max_daily_buys", event.target.value, Math.round)}
              />
            </label>
            <label>
              止盈比例（%）
              <span className="setting-example">样例：8</span>
              <input
                type="number"
                aria-label="止盈比例"
                min={0.01}
                step={0.1}
                value={settingValue("take_profit_pct", percentValue(settings.take_profit_pct, 0.08))}
                onChange={(event) => updateNumericSetting("take_profit_pct", event.target.value, (value) => value / 100)}
              />
            </label>
            <label>
              止损比例（%）
              <span className="setting-example">样例：-5</span>
              <input
                type="number"
                aria-label="止损比例"
                max={-0.01}
                step={0.1}
                value={settingValue("stop_loss_pct", percentValue(settings.stop_loss_pct, -0.05))}
                onChange={(event) => updateNumericSetting("stop_loss_pct", event.target.value, (value) => value / 100)}
              />
            </label>
            <label>
              滑点比例（%）
              <span className="setting-example">样例：0.05</span>
              <input
                type="number"
                aria-label="滑点比例"
                min={0}
                step={0.01}
                value={settingValue("slippage_rate", percentValue(settings.slippage_rate, 0))}
                onChange={(event) => updateNumericSetting("slippage_rate", event.target.value, (value) => value / 100)}
              />
            </label>
            <label>
              手续费率（%）
              <span className="setting-example">样例：0.03</span>
              <input
                type="number"
                aria-label="手续费率"
                min={0}
                step={0.01}
                value={settingValue("fee_rate", percentValue(settings.fee_rate, 0))}
                onChange={(event) => updateNumericSetting("fee_rate", event.target.value, (value) => value / 100)}
              />
            </label>
            <label>
              最少上市天数
              <span className="setting-example">样例：60</span>
              <input
                type="number"
                aria-label="最少上市天数"
                min={0}
                step={1}
                value={settingValue("min_listing_days", String(settings.min_listing_days))}
                onChange={(event) => updateNumericSetting("min_listing_days", event.target.value, Math.round)}
              />
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={settings.exclude_st}
                onChange={(event) => updateSettings({ exclude_st: event.target.checked })}
              />
              过滤 ST
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={settings.conservative_execution}
                onChange={(event) => updateSettings({ conservative_execution: event.target.checked })}
              />
              保守撮合
            </label>
          </div>
          <div className="inline-actions">
            <span className="muted-code">A股买入按 100 股整手取整，仓位按当前总权益计算。</span>
          </div>
        </div>
      </div>

      <div className="strategy-grid">
        <div className="condition-library">
          <h3>写入条件</h3>
          <section aria-label="条件写法帮助" className="condition-help-grid">
            <article className="condition-expression-box condition-help-card">
              <div className="condition-help-copy">
                <h4 className="condition-help-title">入场条件写法模板</h4>
                <p className="condition-help-text">写不出来时，先照着模板替换数字，再点校验条件。</p>
              </div>
              <div className="condition-examples">
                {entryTemplates.map((template) => (
                  <span key={template} className="template-chip">
                    {template}
                  </span>
                ))}
              </div>
            </article>
            <article className="condition-expression-box condition-help-card">
              <div className="condition-help-copy">
                <h4 className="condition-help-title">离场条件写法模板</h4>
                <p className="condition-help-text">离场尽量写成明确触发句，避免“感觉走弱”这类无法回测的描述。</p>
              </div>
              <div className="condition-examples">
                {exitTemplates.map((template) => (
                  <span key={template} className="template-chip">
                    {template}
                  </span>
                ))}
              </div>
            </article>
          </section>
          <div className="condition-examples" aria-label="条件样例">
            {examples.slice(0, 8).map((example) => (
              <button className="example-chip" type="button" key={example} onClick={() => setConditionText(example)}>
                {example}
              </button>
            ))}
          </div>
          <ul className="condition-list">
            {(conditionLibrary as ConditionMeta[]).map((condition) => (
              <li key={condition.id}>
                <div>
                  <strong>{condition.label}</strong>
                  <span>样例：{conditionExamplesById[condition.id] ?? "按上方样例输入后校验"}</span>
                </div>
                <small>{condition.category}</small>
              </li>
            ))}
          </ul>
        </div>

        <div className="active-strategy">
          <div className="active-strategy-head">
            <h3>入场组合</h3>
            <label>
              组合方式
              <select
                aria-label="组合方式"
                value={group.operator}
                onChange={(event) => updateGroup({ operator: event.target.value as typeof group.operator })}
              >
                <option value="and">全部满足</option>
                <option value="or">任一满足</option>
                <option value="score">评分达标</option>
              </select>
            </label>
          </div>
          <span className="status-pill compact">{operatorLabels[group.operator]}</span>
          <div className="entry-rules-panel">
            <div className="active-strategy-head">
              <h3>入场规则</h3>
              <span className="status-pill compact">校验通过后直接写入回测买入判断</span>
            </div>
            <div className="condition-expression-box exit-expression-box entry-expression-box">
              <span className="condition-example-label">样例：{examples[0]}</span>
              <label>
                新增入场条件表达式
                <input
                  aria-label="新增条件表达式"
                  value={conditionText}
                  onChange={(event) => setConditionText(event.target.value)}
                  placeholder="例：收盘价站上20日均线"
                />
              </label>
              <div className="inline-actions">
                <button
                  className="secondary-button"
                  type="button"
                  aria-label="校验条件"
                  onClick={() => onValidateCondition(conditionText)}
                >
                  <CheckCircle2 size={16} aria-hidden="true" />
                  {isValidatingCondition ? "校验中" : "校验入场条件"}
                </button>
                <button
                  className="primary-button"
                  type="button"
                  aria-label="添加已校验条件"
                  onClick={addValidatedCondition}
                  disabled={!conditionValidation?.ok || !conditionValidation.condition}
                >
                  <Plus size={16} aria-hidden="true" />
                  添加入场条件
                </button>
              </div>
              <div className={`condition-validation ${conditionValidation?.ok ? "ok" : conditionValidation ? "bad" : ""}`}>
                {conditionValidation?.ok && conditionValidation.condition ? (
                  <span>
                    可识别：{conditionMetaById[conditionValidation.condition.condition_id]?.label ?? conditionValidation.condition.condition_id}
                  </span>
                ) : conditionValidation ? (
                  <span>{conditionValidation.errors[0]?.message ?? "无法识别条件，请参考样例改写。"}</span>
                ) : (
                  <span>入场条件校验成功后，会直接写入策略并参与回测买入判断。</span>
                )}
              </div>
              {entryAddMessage ? <div className="condition-validation ok">{entryAddMessage}</div> : null}
            </div>
          </div>
          <div className="condition-config-list">
            {group.conditions.map((condition) => {
              const meta = conditionMetaById[condition.condition_id] as ConditionMeta | undefined;
              return (
                <article className="condition-config" key={condition.id}>
                  <div className="condition-config-title">
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={condition.enabled}
                        onChange={(event) => updateCondition(condition.id, { enabled: event.target.checked })}
                      />
                      <strong>{meta?.label ?? condition.condition_id}</strong>
                    </label>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label={`删除${meta?.label ?? condition.condition_id}`}
                      onClick={() => removeCondition(condition.id)}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </div>
                  <p className="condition-expression">条件：{readableConditionText(condition, meta)}</p>
                  <p className="condition-param-summary">解析参数：{describeConditionParams(condition, meta)}</p>
                </article>
              );
            })}
          </div>
          <div className="exit-rules-panel">
            <div className="active-strategy-head">
              <h3>离场规则</h3>
              <span className="status-pill compact">A股 T+1：买入当日不卖出</span>
            </div>
            <div className="exit-rule-summary">
              <span>固定持仓 {settings.fixed_holding_days} 天</span>
              <span>止盈 {settings.take_profit_pct == null ? "未启用" : `${(settings.take_profit_pct * 100).toFixed(2).replace(/\.?0+$/, "")}%`}</span>
              <span>止损 {settings.stop_loss_pct == null ? "未启用" : `${(settings.stop_loss_pct * 100).toFixed(2).replace(/\.?0+$/, "")}%`}</span>
            </div>
            <div className="condition-expression-box exit-expression-box">
              <span className="condition-example-label">样例：收盘价跌破3日均线；跌破20日低点；突破20日最低</span>
              <label>
                新增离场条件表达式
                <input
                  aria-label="新增离场条件表达式"
                  value={exitConditionText}
                  onChange={(event) => setExitConditionText(event.target.value)}
                  placeholder="例：收盘价跌破3日均线"
                />
              </label>
              <div className="inline-actions">
                <button className="secondary-button" type="button" onClick={validateExitCondition}>
                  <CheckCircle2 size={16} aria-hidden="true" />
                  {isValidatingExit ? "校验中" : "校验离场条件"}
                </button>
                <button
                  className="primary-button"
                  type="button"
                  onClick={addValidatedExitCondition}
                  disabled={!exitValidation?.ok || !exitValidation.condition}
                >
                  <Plus size={16} aria-hidden="true" />
                  添加离场条件
                </button>
              </div>
              <div className={`condition-validation ${exitValidation?.ok ? "ok" : exitValidation ? "bad" : ""}`}>
                {exitValidation?.ok && exitValidation.condition ? (
                  <span>
                    离场可识别：{conditionMetaById[exitValidation.condition.condition_id]?.label ?? exitValidation.condition.condition_id}
                  </span>
                ) : exitValidation ? (
                  <span>{exitValidation.errors[0]?.message ?? "无法识别离场条件，请参考样例改写。"}</span>
                ) : (
                  <span>离场条件校验成功后，会直接写入策略并参与回测卖出判断。</span>
                )}
              </div>
              {exitAddMessage ? <div className="condition-validation ok">{exitAddMessage}</div> : null}
            </div>
            <div className="condition-examples" aria-label="离场条件样例">
              {exitExamples.map((example) => (
                <button className="example-chip" type="button" key={example} onClick={() => setExitConditionText(example)}>
                  {example}
                </button>
              ))}
            </div>
            <div className="condition-config-list">
              {strategy.exit_rules.map((condition) => {
                const meta = conditionMetaById[condition.condition_id] as ConditionMeta | undefined;
                return (
                  <article className="condition-config exit-rule-config" key={condition.id}>
                    <div className="condition-config-title">
                      <strong>{meta?.label ?? "离场条件"}</strong>
                      <button
                        className="icon-button"
                        type="button"
                        aria-label={`删除离场${meta?.label ?? "条件"}`}
                        onClick={() => removeExitCondition(condition.id)}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    </div>
                    <p className="condition-expression">卖出触发：{readableConditionText(condition, meta)}</p>
                    <p className="condition-param-summary">规则说明：{describeSellRule(condition, meta)}</p>
                  </article>
                );
              })}
              {strategy.exit_rules.length === 0 ? (
                <p className="condition-param-summary">当前没有技术离场条件，仅使用固定持仓、止盈、止损。</p>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      </fieldset>
    </section>
  );
}
