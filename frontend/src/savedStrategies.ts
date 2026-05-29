import type { ConditionGroup, ConditionNode, SavedStrategyPreset, StrategyConfig } from "./types";
import { defaultStrategy } from "./strategyDefaults";

const STORAGE_KEY = "astock-saved-strategies";
const BUILTIN_ID_PREFIX = "builtin-";

const builtInStrategies: SavedStrategyPreset[] = [
  {
    id: "builtin-default",
    name: "基础均衡策略",
    saved_at: "builtin",
    strategy: cloneStrategyConfig(defaultStrategy)
  },
  {
    id: "builtin-breakout",
    name: "放量突破策略",
    saved_at: "builtin",
    strategy: {
      name: "放量突破策略",
      market_filters: [],
      entry_groups: [
        {
          id: "entry",
          operator: "and",
          conditions: [
            {
              id: "builtin-breakout-high",
              condition_id: "breakout_above_n_day_high",
              enabled: true,
              params: { window: 20 },
              data_lag_days: 0,
              expression: "突破20日新高"
            },
            {
              id: "builtin-breakout-volume",
              condition_id: "volume_ratio_between",
              enabled: true,
              params: { window: 2, min: 1.2, max: 2.5 },
              data_lag_days: 0,
              expression: "量比2日介于1.2到2.5"
            }
          ]
        }
      ],
      exit_rules: [
        {
          id: "builtin-breakout-exit",
          condition_id: "close_below_ma",
          enabled: true,
          params: { window: 3 },
          data_lag_days: 0,
          expression: "收盘价跌破3日均线"
        }
      ],
      score_threshold: null
    }
  },
  {
    id: "builtin-low-absorb",
    name: "回踩均线策略",
    saved_at: "builtin",
    strategy: {
      name: "回踩均线策略",
      market_filters: [],
      entry_groups: [
        {
          id: "entry",
          operator: "and",
          conditions: [
            {
              id: "builtin-pullback-ma",
              condition_id: "close_above_ma",
              enabled: true,
              params: { window: 20 },
              data_lag_days: 0,
              expression: "收盘价站上20日均线"
            },
            {
              id: "builtin-pullback-cap",
              condition_id: "market_cap_between",
              enabled: true,
              params: { min: 1000000000, max: 30000000000 },
              data_lag_days: 0,
              expression: "流通市值10亿到300亿"
            }
          ]
        }
      ],
      exit_rules: [
        {
          id: "builtin-pullback-exit",
          condition_id: "breakdown_below_n_day_low",
          enabled: true,
          params: { window: 20 },
          data_lag_days: 0,
          expression: "跌破20日低点"
        }
      ],
      score_threshold: null
    }
  }
];

function sortParams(params: ConditionNode["params"]): ConditionNode["params"] {
  return Object.fromEntries(Object.entries(params).sort(([left], [right]) => left.localeCompare(right)));
}

function normalizeCondition(condition: ConditionNode) {
  return {
    condition_id: condition.condition_id,
    enabled: condition.enabled,
    params: sortParams(condition.params),
    data_lag_days: condition.data_lag_days,
    expression: condition.expression ?? null,
    weight: condition.weight ?? null
  };
}

function normalizeGroup(group: ConditionGroup) {
  return {
    operator: group.operator,
    conditions: group.conditions.map(normalizeCondition)
  };
}

function uniqueSavedStrategyName(baseName: string, existingNames: string[]): string {
  const normalizedBase = baseName.trim() || "自定义策略";
  if (!existingNames.includes(normalizedBase)) {
    return normalizedBase;
  }
  let index = 2;
  while (existingNames.includes(`${normalizedBase}（${index}）`)) {
    index += 1;
  }
  return `${normalizedBase}（${index}）`;
}

export function cloneStrategyConfig(strategy: StrategyConfig): StrategyConfig {
  return JSON.parse(JSON.stringify(strategy)) as StrategyConfig;
}

export function strategySignature(strategy: StrategyConfig): string {
  return JSON.stringify({
    name: strategy.name.trim(),
    market_filters: strategy.market_filters.map(normalizeCondition),
    entry_groups: strategy.entry_groups.map(normalizeGroup),
    exit_rules: strategy.exit_rules.map(normalizeCondition),
    score_threshold: strategy.score_threshold ?? null
  });
}

export function hasSavableRules(strategy: StrategyConfig): boolean {
  return strategy.entry_groups.some((group) => group.conditions.length > 0) && strategy.exit_rules.length > 0;
}

export function loadSavedStrategies(): SavedStrategyPreset[] {
  const builtins = builtInStrategies.map((item) => ({
    ...item,
    strategy: cloneStrategyConfig(item.strategy)
  }));
  if (typeof window === "undefined") {
    return builtins;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return builtins;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return builtins;
    }
    const customItems = parsed.flatMap((item) => {
      if (
        !item ||
        typeof item !== "object" ||
        typeof item.id !== "string" ||
        typeof item.name !== "string" ||
        typeof item.saved_at !== "string" ||
        !item.strategy
      ) {
        return [];
      }
      return [
        {
          id: item.id,
          name: item.name,
          saved_at: item.saved_at,
          strategy: cloneStrategyConfig(item.strategy as StrategyConfig)
        }
      ];
    });
    return [...builtins, ...customItems];
  } catch {
    return builtins;
  }
}

export function persistSavedStrategies(items: SavedStrategyPreset[]): void {
  if (typeof window === "undefined") {
    return;
  }
  const customItems = items.filter((item) => !isBuiltInStrategyPreset(item.id));
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(customItems));
}

export function isBuiltInStrategyPreset(presetId: string): boolean {
  return presetId.startsWith(BUILTIN_ID_PREFIX);
}

export function createSavedStrategyPreset(strategy: StrategyConfig, existing: SavedStrategyPreset[]): SavedStrategyPreset {
  const nextName = uniqueSavedStrategyName(strategy.name, existing.map((item) => item.name));
  return {
    id: `saved-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: nextName,
    saved_at: new Date().toISOString(),
    strategy: cloneStrategyConfig({
      ...strategy,
      name: nextName
    })
  };
}
