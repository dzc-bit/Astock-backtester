import type { BacktestSettingsConfig, StrategyConfig } from "./types";

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
  { id: "macd_histogram_at_least", label: "MACD histogram floor", category: "Trend" },
  { id: "close_above_ma", label: "Close above moving average", category: "Trend" },
  { id: "volume_ratio_between", label: "Volume ratio range", category: "Volume" },
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
        },
        {
          id: "volume-ratio",
          condition_id: "volume_ratio_between",
          enabled: true,
          params: { window: 2, min: 1, max: 2.5 },
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

export const defaultSettings: BacktestSettingsConfig = {
  start_date: "2024-01-02",
  end_date: "2024-01-08",
  initial_cash: 100000,
  benchmark_symbol: "000300.SH",
  fixed_holding_days: 3,
  take_profit_pct: 0.08,
  stop_loss_pct: -0.05,
  max_positions: 2,
  max_daily_buys: 1,
  fee_rate: 0.0003,
  stamp_tax_rate: 0.0005,
  slippage_rate: 0.0005,
  min_listing_days: 60,
  exclude_st: true,
  conservative_execution: true
};
