import type { StrategyConfig } from "./types";

export const conditionCategories = [
  "Market Heat",
  "Market Cap",
  "Capital Flow",
  "Trend",
  "Volume",
  "Price Movement",
  "Pattern"
] as const;

export const conditionLibrary = [
  { id: "market_rising_ratio_at_least", label: "Market rising ratio", category: "Market Heat" },
  { id: "market_cap_between", label: "Float market cap range", category: "Market Cap" },
  { id: "capital_flow_n_day_sum_at_least", label: "N-day main net inflow", category: "Capital Flow" },
  { id: "close_above_ma", label: "Close above moving average", category: "Trend" },
  { id: "turnover_between", label: "Turnover range", category: "Volume" }
];

export const defaultStrategy: StrategyConfig = {
  name: "Market heat + small cap inflow",
  market_filters: [
    {
      id: "market",
      condition_id: "market_rising_ratio_at_least",
      enabled: true,
      params: { min_ratio: 0.5 },
      data_lag_days: 0
    }
  ],
  entry_groups: [
    {
      id: "entry",
      operator: "and",
      conditions: [
        {
          id: "cap",
          condition_id: "market_cap_between",
          enabled: true,
          params: { min: 1000000000, max: 30000000000 },
          data_lag_days: 0
        },
        {
          id: "flow",
          condition_id: "capital_flow_n_day_sum_at_least",
          enabled: true,
          params: { window: 3, min: 3000000 },
          data_lag_days: 0
        }
      ]
    }
  ],
  exit_rules: [
    {
      id: "exit-ma",
      condition_id: "close_below_ma",
      enabled: true,
      params: { window: 3 },
      data_lag_days: 0
    }
  ],
  score_threshold: null
};
