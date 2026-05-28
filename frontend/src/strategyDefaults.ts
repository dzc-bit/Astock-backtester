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
  {
    id: "market_rising_ratio_at_least",
    label: "市场上涨家数占比",
    category: "市场热度",
    params: [{ key: "min_ratio", label: "上涨占比阈值", type: "percent", options: [0.45, 0.5, 0.55, 0.6, 0.65] }]
  },
  {
    id: "market_cap_between",
    label: "流通市值区间",
    category: "市值",
    params: [
      { key: "min", label: "流通市值下限", type: "currency", options: [1_000_000_000, 3_000_000_000, 5_000_000_000, 10_000_000_000] },
      { key: "max", label: "流通市值上限", type: "currency", options: [20_000_000_000, 30_000_000_000, 50_000_000_000, 100_000_000_000] }
    ]
  },
  {
    id: "capital_flow_n_day_sum_at_least",
    label: "近N日主力净流入",
    category: "资金流向",
    params: [
      { key: "window", label: "统计窗口", type: "days", options: [1, 3, 5, 10] },
      { key: "min", label: "净流入下限", type: "currency", options: [1_000_000, 3_000_000, 5_000_000, 10_000_000] }
    ]
  },
  {
    id: "macd_histogram_at_least",
    label: "MACD柱线下限",
    category: "趋势",
    params: [{ key: "min", label: "MACD下限", type: "number", options: [-0.02, 0, 0.02, 0.05] }]
  },
  {
    id: "close_above_ma",
    label: "收盘价站上均线",
    category: "趋势",
    params: [{ key: "window", label: "窗口", type: "days", options: [3, 5, 10, 20, 60] }]
  },
  {
    id: "volume_ratio_between",
    label: "量比区间",
    category: "量价",
    params: [
      { key: "window", label: "统计窗口", type: "days", options: [2, 3, 5, 10] },
      { key: "min", label: "量比下限", type: "number", options: [1, 1.2, 1.5, 2] },
      { key: "max", label: "量比上限", type: "number", options: [2, 2.5, 3, 5] }
    ]
  },
  {
    id: "turnover_between",
    label: "换手率区间",
    category: "量价",
    params: [
      { key: "min", label: "换手率下限", type: "percent", options: [0.01, 0.02, 0.03, 0.05] },
      { key: "max", label: "换手率上限", type: "percent", options: [0.08, 0.1, 0.15, 0.2] }
    ]
  },
  {
    id: "past_return_between",
    label: "前期涨幅区间",
    category: "前期涨幅",
    params: [
      { key: "window", label: "统计窗口", type: "days", options: [2, 3, 5, 10, 20] },
      { key: "min", label: "涨幅下限", type: "percent", options: [-0.05, 0, 0.03, 0.05] },
      { key: "max", label: "涨幅上限", type: "percent", options: [0.08, 0.12, 0.2, 0.35] }
    ]
  },
  {
    id: "past_return_at_most",
    label: "前期涨幅上限",
    category: "前期涨幅",
    params: [
      { key: "window", label: "统计窗口", type: "days", options: [2, 3, 5, 10, 20] },
      { key: "max", label: "涨幅上限", type: "percent", options: [0.08, 0.12, 0.2, 0.35] }
    ]
  },
  {
    id: "breakout_above_n_day_high",
    label: "突破前高形态",
    category: "形态",
    params: [{ key: "window", label: "前高窗口", type: "days", options: [10, 20, 40, 60] }]
  }
];

export const defaultStrategy: StrategyConfig = {
  name: "市场热度 + 市值量价筛选",
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
  stock_pool: "all",
  custom_symbols: [],
  benchmark_symbol: "000300.SH",
  position_sizing_mode: "fixed_ratio",
  position_size_pct: 0.5,
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
