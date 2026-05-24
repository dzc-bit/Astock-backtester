import type { BacktestSettingsConfig, StrategyConfig } from "./types";

export const conditionCategories = [
  "市场热度",
  "市值",
  "资金流向",
  "趋势",
  "量价",
  "前期涨幅",
  "形态"
] as const;

export const conditionLibrary = [
  { id: "market_rising_ratio_at_least", label: "市场上涨家数占比", category: "市场热度" },
  { id: "market_cap_between", label: "流通市值区间", category: "市值" },
  { id: "capital_flow_n_day_sum_at_least", label: "近N日主力净流入", category: "资金流向" },
  { id: "macd_histogram_at_least", label: "MACD柱线下限", category: "趋势" },
  { id: "close_above_ma", label: "收盘价站上均线", category: "趋势" },
  { id: "volume_ratio_between", label: "量比区间", category: "量价" },
  { id: "turnover_between", label: "换手率区间", category: "量价" },
  { id: "past_return_between", label: "前期涨幅区间", category: "前期涨幅" },
  { id: "past_return_at_most", label: "前期涨幅上限", category: "前期涨幅" },
  { id: "breakout_above_n_day_high", label: "突破前高形态", category: "形态" }
];

export const defaultStrategy: StrategyConfig = {
  name: "市场热度 + 小市值资金流入",
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
