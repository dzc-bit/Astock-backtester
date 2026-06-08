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
  diagnostics?: Array<Record<string, unknown>>;
  failures?: Array<Record<string, unknown>>;
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

export type MarketIndexQuote = {
  symbol: string;
  name: string;
  last: number;
  previous_close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  source: string;
  updated_at?: string | null;
};

export type MarketBreadth = {
  up: number;
  down: number;
  flat: number;
  total: number;
  source: string;
};

export type SectorMover = {
  name: string;
  change_pct: number;
  leading_symbol?: string | null;
  source: string;
};

export type MarketSessionPhase = "trading" | "pre_open" | "lunch_break" | "post_close" | "non_trading";

export type MarketRefreshMeta = {
  phase: MarketSessionPhase;
  status: "idle" | "refreshing" | "using_last_success" | "unavailable";
  message: string;
  last_success_at?: string | null;
  last_error?: string | null;
  next_refresh_ms: number;
};

export type RealtimeMarketSnapshot = {
  status: "live" | "stale" | "unavailable";
  source: string;
  updated_at: string;
  market_phase?: MarketSessionPhase;
  indexes: MarketIndexQuote[];
  breadth?: MarketBreadth | null;
  strong_sectors: SectorMover[];
  yesterday_strong_sectors?: SectorMover[];
  message: string;
  diagnostics?: string[];
};

export type MarketNewsItem = {
  title: string;
  summary?: string | null;
  source: string;
  published_at?: string | null;
  url?: string | null;
  tags: string[];
  sentiment: "positive" | "neutral" | "negative";
};

export type MarketNewsResponse = {
  updated_at: string;
  source: string;
  items: MarketNewsItem[];
  diagnostics?: string[];
};

export type MarketBriefingLink = {
  title: string;
  url?: string | null;
  published_at?: string | null;
  category?: string | null;
};

export type MarketBriefingTable = {
  title?: string | null;
  columns: string[];
  rows: Array<Record<string, string>>;
};

export type MarketBriefingSection = {
  title: string;
  content?: string | null;
  links: MarketBriefingLink[];
  tables: MarketBriefingTable[];
};

export type MarketBriefingResponse = {
  kind: "fupan" | "zaopan";
  updated_at: string;
  source: string;
  source_url?: string | null;
  summary: string;
  sections: MarketBriefingSection[];
  diagnostics: string[];
};

export type MarketCommentaryPoint = {
  title: string;
  detail: string;
  weight: "high" | "medium" | "low";
};

export type MarketCommentaryResponse = {
  updated_at: string;
  trade_date: string;
  source: string;
  mode?: "intraday" | "lunch_break_review" | "post_close" | "non_trading_review" | "news_fallback" | "local_brief_review";
  stance: "positive" | "neutral" | "defensive";
  summary: string;
  drivers: MarketCommentaryPoint[];
  risks: string[];
  next_watch: string[];
  diagnostics: string[];
};

export type NewsSummaryTheme = {
  title: string;
  summary: string;
  sentiment: "positive" | "neutral" | "negative";
  source_count: number;
  headlines: string[];
};

export type NewsSummaryResponse = {
  updated_at: string;
  source: string;
  item_count: number;
  themes: NewsSummaryTheme[];
  highlights: string[];
  risks: string[];
  diagnostics: string[];
};

export type RiskAlertItem = {
  symbol: string;
  name: string;
  risk_type: string;
  reason: string;
  severity: "high" | "medium" | "low";
  source: string;
  detected_at: string;
};

export type RiskAlertsResponse = {
  updated_at: string;
  source: string;
  items: RiskAlertItem[];
  diagnostics: string[];
};

export type ConditionNode = {
  id: string;
  condition_id: string;
  enabled: boolean;
  params: Record<string, number | string | boolean>;
  weight?: number | null;
  data_lag_days: number;
  expression?: string | null;
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
  stock_pool: "all" | "main_board" | "gem" | "star" | "beijing" | "custom";
  custom_symbols: string[];
  benchmark_symbol: string;
  position_sizing_mode: "fixed_ratio" | "equal_slots";
  position_size_pct: number;
  fixed_holding_days: number;
  take_profit_pct: number | null;
  stop_loss_pct: number | null;
  max_positions: number;
  max_daily_buys: number;
  limit_up_blocks_buy?: boolean;
  limit_down_blocks_sell?: boolean;
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
  average_position_pct: number;
  max_position_pct: number;
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
  planned_amount: number;
  buy_amount: number;
  sell_amount?: number | null;
  target_position_pct: number;
  actual_position_pct: number;
  buy_reason: string[];
  sell_reason: string[];
  blocked_reason: string | null;
  pnl?: number | null;
  pnl_pct?: number | null;
};

export type MatchedStock = {
  symbol: string;
  name?: string | null;
  close?: number | null;
  change?: number | null;
  change_pct?: number | null;
  reasons: string[];
  signal_date?: string | null;
  trade_date?: string | null;
  rank_score?: number | null;
};

export type DailyStrategyMatches = {
  signal_date: string;
  trade_date: string;
  matches: MatchedStock[];
};

export type BacktestResult = {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  trades: Trade[];
  latest_strategy_matches?: DailyStrategyMatches | null;
  matched_stocks?: MatchedStock[];
  preflight_issues: Array<{ code: string; message: string; severity: "warning" | "error"; dataset?: string | null }>;
};

export type BacktestProgressEvent = {
  type?: "progress";
  trade_date?: string;
  scanned_days?: number;
  total_days?: number;
  open_positions?: number;
  closed_trades?: number;
  candidates?: number;
  message: string;
};

export type BacktestStreamHandlers = {
  onPhase?: (phase: string) => void;
  onProgress?: (event: BacktestProgressEvent) => void;
  onTrade?: (trade: Trade) => void;
  onResult?: (result: BacktestResult) => void;
};

export type ConditionValidationResult = {
  ok: boolean;
  normalized_text: string;
  condition: ConditionNode | null;
  errors: Array<{ code: string; message: string }>;
  examples: string[];
};

export type RecommendedStrategy = {
  id: string;
  name: string;
  description: string;
  suitable_market: string;
  risk_note: string;
  example_conditions: string[];
  scenario: string;
  featured: boolean;
  required_datasets: string[];
  capability_note?: string | null;
  strategy: StrategyConfig;
};

export type RecommendedStrategiesResponse = {
  items: RecommendedStrategy[];
};

export type SavedStrategyPreset = {
  id: string;
  name: string;
  saved_at: string;
  strategy: StrategyConfig;
};
