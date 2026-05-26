export type DatasetCoverage = {
  dataset: string;
  symbols: number;
  start_date: string | null;
  end_date: string | null;
  missing_rows: number;
};

export type DataServiceStatus = {
  running: boolean;
  port: number;
  base_url: string;
  cache_dir: string;
  message: string;
};

export type DataServiceHealth = {
  ok: boolean;
  cache_path: string;
  port: number | null;
  coverage: DatasetCoverage[];
};

export type DailyBarsCoverageItem = {
  symbol: string;
  start_date: string | null;
  end_date: string | null;
  rows: number;
  missing_trade_dates: string[];
  missing_capital_flow_dates: string[];
  missing_market_cap_dates: string[];
};

export type DailyBarsCoverageResponse = {
  items: DailyBarsCoverageItem[];
};

export type ServiceLogEntry = {
  level: "info" | "warning" | "error";
  message: string;
  timestamp?: string;
};

export type FetchResult = {
  status: "ok" | "partial";
  imported_rows: number;
  requested_symbols: string[];
  fetched_symbols: string[];
  missing_symbols: string[];
  coverage: DatasetCoverage[];
  logs: ServiceLogEntry[];
};

export type ImportResult = {
  status: "ok" | "partial";
  imported_rows: number;
  coverage: DatasetCoverage[];
  logs: ServiceLogEntry[];
};

export type SyncJobStatus = {
  job_id: string;
  mode: "full_market_bootstrap" | "incremental_update" | "retry_failed";
  status: "running" | "completed" | "completed_with_errors" | "failed";
  total_symbols: number;
  completed_symbols: number;
  failed_symbols: number;
  imported_rows: number;
  current_symbol?: string | null;
  start_date: string;
  end_date: string;
  errors: string[];
};

export type ConditionNode = {
  id: string;
  condition_id: string;
  enabled: boolean;
  params: Record<string, number | string | boolean>;
  weight?: number | null;
  data_lag_days: number;
};

export type ConditionGroup = {
  id: string;
  operator: "and" | "or" | "score";
  conditions: ConditionNode[];
};

export type StrategyConfig = {
  name: string;
  market_filters: ConditionNode[];
  entry_groups: ConditionGroup[];
  exit_rules: ConditionNode[];
  score_threshold?: number | null;
};

export type BacktestSettingsConfig = {
  start_date: string;
  end_date: string;
  initial_cash: number;
  benchmark_symbol: string;
  fixed_holding_days: number;
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_positions: number;
  max_daily_buys: number;
  fee_rate: number;
  stamp_tax_rate: number;
  slippage_rate: number;
  min_listing_days: number;
  exclude_st: boolean;
  conservative_execution: boolean;
};

export type BacktestMetrics = {
  total_return_pct: number;
  annualized_return_pct: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  trade_count: number;
  average_trade_return_pct: number;
};

export type EquityPoint = {
  trade_date: string;
  equity: number;
  cash: number;
  market_value: number;
  drawdown_pct: number;
};

export type Trade = {
  symbol: string;
  buy_signal_date: string;
  buy_date: string;
  sell_date?: string | null;
  buy_price: number;
  sell_price?: number | null;
  shares: number;
  buy_reason: string[];
  sell_reason: string[];
  pnl?: number | null;
  pnl_pct?: number | null;
};

export type BacktestResult = {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  trades: Trade[];
  preflight_issues: Array<{ code: string; message: string; severity: "warning" | "error"; dataset?: string | null }>;
};
