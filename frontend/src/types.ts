export type DatasetCoverage = {
  dataset: string;
  symbols: number;
  start_date: string | null;
  end_date: string | null;
  missing_rows: number;
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
