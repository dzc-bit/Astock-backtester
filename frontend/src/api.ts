import { invoke } from "@tauri-apps/api/core";
import type {
  BacktestResult,
  BacktestStreamHandlers,
  BacktestSettingsConfig,
  DataServiceHealth,
  DataServiceStatus,
  DatasetCoverage,
  DailyBarsCoverageResponse,
  FetchResult,
  ImportResult,
  ConditionValidationResult,
  MarketNewsResponse,
  RealtimeMarketSnapshot,
  RecommendedStrategiesResponse,
  RiskAlertsResponse,
  StrategyConfig,
  SyncJobStatus
} from "./types";

type BackendResponse<T> = ({ ok: true } & T) | { ok: false; error: { code: string; message: string } };

const demoResult: BacktestResult = {
  metrics: {
    total_return_pct: 0.032,
    annualized_return_pct: 0.032,
    max_drawdown_pct: -0.018,
    win_rate_pct: 0.6,
    trade_count: 1,
    average_trade_return_pct: 0.011,
    average_position_pct: 0.48,
    max_position_pct: 0.48
  },
  equity_curve: [
    { trade_date: "2024-01-02", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
    { trade_date: "2024-01-05", equity: 102300, cash: 51000, market_value: 51300, drawdown_pct: 0 },
    { trade_date: "2024-01-08", equity: 103200, cash: 103200, market_value: 0, drawdown_pct: 0 }
  ],
  trades: [
    {
      symbol: "AAA",
      buy_signal_date: "2024-01-04",
      buy_date: "2024-01-05",
      sell_date: "2024-01-08",
      buy_price: 12,
      sell_price: 10.2,
      shares: 4000,
      planned_amount: 50000,
      buy_amount: 48000,
      sell_amount: 40800,
      target_position_pct: 0.5,
      actual_position_pct: 0.48,
      buy_reason: ["float market cap 8800000000 in [1000000000, 30000000000]", "3d main net inflow 6000000 >= 3000000"],
      sell_reason: ["fixed holding days reached"],
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  preflight_issues: []
};

function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

async function callBackend<T>(payload: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) {
    if (payload.command === "coverage") {
      return {
        coverage: [
          { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
          { dataset: "capital_flow", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
        ]
      } as T;
    }
    return { result: demoResult } as T;
  }
  const response = await invoke<BackendResponse<T>>("backend_command", { payload });
  if (!response.ok) {
    throw new Error(response.error.message);
  }
  return response;
}

async function serviceFetch<T>(baseUrl: string, path: string, payload?: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: payload ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : undefined
  });
  const json = await response.json();
  if (!response.ok) {
    const code = json.code ? `${json.code} - ` : "";
    throw new Error(`HTTP ${response.status}: ${code}${json.message ?? "local data service request failed"}`);
  }
  return json as T;
}

export async function ensureDataService(cacheDir: string): Promise<DataServiceStatus> {
  if (!isTauriRuntime()) {
    return {
      running: true,
      port: 9010,
      base_url: "http://127.0.0.1:9010",
      cache_dir: cacheDir,
      message: "browser preview uses mock local service"
    };
  }
  return invoke<DataServiceStatus>("ensure_data_service", { cacheDir });
}

export async function loadCoverage(cacheDir: string): Promise<DatasetCoverage[]> {
  const response = await callBackend<{ coverage: DatasetCoverage[] }>({ command: "coverage", cache_dir: cacheDir });
  return response.coverage;
}

export async function loadDataServiceHealth(baseUrl: string): Promise<DataServiceHealth> {
  if (!isTauriRuntime()) {
    return {
      ok: true,
      cache_path: ".astock-cache",
      port: 9010,
      coverage: [
        { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
        { dataset: "capital_flow", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
        { dataset: "market_cap", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
      ]
    };
  }
  return serviceFetch<DataServiceHealth>(baseUrl, "/health");
}

export async function loadDataServiceLogs(baseUrl: string): Promise<{ items: Array<{ level: "info" | "warning" | "error"; message: string; timestamp?: string }> }> {
  if (!isTauriRuntime()) {
    return { items: [{ level: "info", message: "browser preview uses mock local service" }] };
  }
  return serviceFetch(baseUrl, "/logs/recent");
}

export async function loadRealtimeMarketSnapshot(baseUrl: string): Promise<RealtimeMarketSnapshot> {
  if (!isTauriRuntime()) {
    return {
      status: "live",
      source: "browser-preview",
      updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString(),
      indexes: [
        {
          symbol: "sh000001",
          name: "上证指数",
          last: 3120.5,
          previous_close: 3100,
          change: 20.5,
          change_pct: 0.0066,
          source: "browser-preview",
          updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString()
        },
        {
          symbol: "sz399001",
          name: "深证成指",
          last: 9800.2,
          previous_close: 9700,
          change: 100.2,
          change_pct: 0.0103,
          source: "browser-preview",
          updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString()
        }
      ],
      breadth: { up: 3200, down: 1700, flat: 200, total: 5100, source: "browser-preview" },
      strong_sectors: [
        { name: "半导体", change_pct: 0.036, leading_symbol: "688001", source: "browser-preview" },
        { name: "电力设备", change_pct: 0.024, leading_symbol: "300750", source: "browser-preview" }
      ],
      yesterday_strong_sectors: [
        { name: "半导体", change_pct: 0.031, leading_symbol: "688001", source: "browser-preview" },
        { name: "机器人", change_pct: 0.022, leading_symbol: "300024", source: "browser-preview" }
      ],
      message: "浏览器预览实时行情"
    };
  }
  return serviceFetch<RealtimeMarketSnapshot>(baseUrl, "/realtime/market-snapshot");
}

export async function loadMarketNews(baseUrl: string): Promise<MarketNewsResponse> {
  if (!isTauriRuntime()) {
    return {
      updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString(),
      source: "browser-preview",
      diagnostics: [],
      items: [
        {
          title: "政策利好推动科技板块走强",
          summary: "半导体、AI 应用方向盘中活跃。",
          source: "东方财富",
          published_at: new Date("2026-05-27T10:20:00+08:00").toISOString(),
          url: "https://example.test/news",
          tags: ["科技", "政策"],
          sentiment: "positive"
        }
      ]
    };
  }
  return serviceFetch<MarketNewsResponse>(baseUrl, "/market/news");
}

export async function loadRiskAlerts(baseUrl: string): Promise<RiskAlertsResponse> {
  if (!isTauriRuntime()) {
    return {
      updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString(),
      source: "browser-preview",
      items: [
        {
          symbol: "000001",
          name: "*ST示例",
          risk_type: "ST风险",
          reason: "股票名称包含 *ST，存在退市风险警示。",
          severity: "high",
          source: "browser-preview",
          detected_at: new Date("2026-05-27T10:30:00+08:00").toISOString()
        }
      ]
    };
  }
  return serviceFetch<RiskAlertsResponse>(baseUrl, "/risk/alerts");
}

export async function validateConditionExpression(
  baseUrl: string,
  text: string,
  mode: "entry" | "exit" = "entry"
): Promise<ConditionValidationResult> {
  if (!isTauriRuntime()) {
    if (text.trim() === "收盘价站上20日均线") {
      return {
        ok: true,
        normalized_text: text.trim(),
        condition: {
          id: "expr-close-above-ma",
          condition_id: "close_above_ma",
          enabled: true,
          params: { window: 20 },
          data_lag_days: 0,
          expression: text.trim()
        },
        errors: [],
        examples: ["收盘价站上20日均线", "量比2日介于1.2到2.5"]
      };
    }
    if (mode === "exit" && ["突破20日最低", "跌破20日低点"].includes(text.trim())) {
      return {
        ok: true,
        normalized_text: text.trim(),
        condition: {
          id: "expr-breakdown-below-low",
          condition_id: "breakdown_below_n_day_low",
          enabled: true,
          params: { window: 20 },
          data_lag_days: 0,
          expression: text.trim()
        },
        errors: [],
        examples: ["收盘价跌破3日均线", "跌破20日低点", "突破20日最低"]
      };
    }
    return {
      ok: false,
      normalized_text: text.trim(),
      condition: null,
      errors: [{ code: "unrecognized_condition", message: mode === "exit" ? "无法识别离场条件，请参考样例改写。" : "无法识别条件，请参考样例改写。" }],
      examples: mode === "exit" ? ["收盘价跌破3日均线", "跌破20日低点"] : ["收盘价站上20日均线", "量比2日介于1.2到2.5"]
    };
  }
  return serviceFetch<ConditionValidationResult>(baseUrl, "/strategy/conditions/validate", { text, mode });
}

export async function loadRecommendedStrategies(baseUrl: string): Promise<RecommendedStrategiesResponse> {
  if (!isTauriRuntime()) {
    return {
      items: [
        {
          id: "volume-breakout",
          name: "放量突破",
          description: "价格突破前高并伴随量能放大。",
          suitable_market: "指数温和上行、题材活跃时使用。",
          risk_note: "避免连续大涨后追高。",
          example_conditions: ["突破20日新高", "量比2日介于1.2到2.5"],
          scenario: "温和上行",
          featured: true,
          required_datasets: ["daily_bars", "market_cap"],
          capability_note: "浏览器预览使用模拟可用数据。",
          strategy: {
            name: "放量突破",
            market_filters: [],
            entry_groups: [
              {
                id: "entry",
                operator: "and",
                conditions: [
                  {
                    id: "preset-breakout",
                    condition_id: "breakout_above_n_day_high",
                    enabled: true,
                    params: { window: 20 },
                    data_lag_days: 0,
                    expression: "突破20日新高"
                  }
                ]
              }
            ],
            exit_rules: [],
            score_threshold: null
          }
        },
        {
          id: "steady-cap-volume",
          name: "市值量价均衡",
          description: "过滤超大市值和极端成交，寻找流动性适中的趋势机会。",
          suitable_market: "震荡偏强或结构性行情中使用。",
          risk_note: "更适合在市场有承接、但不是全面高潮时使用。",
          example_conditions: ["流通市值10亿到300亿", "换手率2%到8%", "量比2日介于1.2到2.5"],
          scenario: "震荡轮动",
          featured: true,
          required_datasets: ["daily_bars", "market_cap"],
          capability_note: "浏览器预览使用模拟可用数据。",
          strategy: {
            name: "市值量价均衡",
            market_filters: [],
            entry_groups: [
              {
                id: "entry",
                operator: "and",
                conditions: [
                  {
                    id: "preview-cap",
                    condition_id: "market_cap_between",
                    enabled: true,
                    params: { min: 1000000000, max: 30000000000 },
                    data_lag_days: 0,
                    expression: "流通市值10亿到300亿"
                  },
                  {
                    id: "preview-turnover",
                    condition_id: "turnover_between",
                    enabled: true,
                    params: { min: 0.02, max: 0.08 },
                    data_lag_days: 0,
                    expression: "换手率2%到8%"
                  },
                  {
                    id: "preview-volume",
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
                id: "preview-exit-ma",
                condition_id: "close_below_ma",
                enabled: true,
                params: { window: 3 },
                data_lag_days: 0,
                expression: "收盘价跌破3日均线"
              }
            ],
            score_threshold: null
          }
        }
      ]
    };
  }
  return serviceFetch<RecommendedStrategiesResponse>(baseUrl, "/strategy/recommended");
}

export async function loadDailyBarsCoverage(
  baseUrl: string,
  symbols: string[],
  startDate: string,
  endDate: string
): Promise<DailyBarsCoverageResponse> {
  if (!isTauriRuntime()) {
    return {
      items: symbols.map((symbol) => ({
        symbol,
        start_date: startDate,
        end_date: endDate,
        rows: 5,
        missing_trade_dates: [],
        missing_capital_flow_dates: [],
        missing_market_cap_dates: []
      }))
    };
  }
  return serviceFetch<DailyBarsCoverageResponse>(baseUrl, "/coverage/daily-bars", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}

export async function fetchDailyBars(
  baseUrl: string,
  symbols: string[],
  startDate: string,
  endDate: string
): Promise<FetchResult> {
  if (!isTauriRuntime()) {
    return {
      status: "ok",
      imported_rows: symbols.length * 5,
      requested_symbols: symbols,
      fetched_symbols: symbols,
      missing_symbols: [],
      coverage: [
        { dataset: "daily_bars", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 },
        { dataset: "capital_flow", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 },
        { dataset: "market_cap", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 }
      ],
      logs: [{ level: "info", message: `Fetched ${symbols.length * 5} daily bar rows` }]
    };
  }
  return serviceFetch<FetchResult>(baseUrl, "/fetch/daily-bars", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}

export async function importDailyBars(baseUrl: string, source: "sample" | "file", path?: string): Promise<ImportResult> {
  if (!isTauriRuntime()) {
    return {
      status: "ok",
      imported_rows: 10,
      coverage: [
        { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
        { dataset: "capital_flow", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
        { dataset: "market_cap", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
      ],
      logs: [{ level: "info", message: `Imported daily bars from ${source}${path ? `: ${path}` : ""}` }]
    };
  }
  return serviceFetch<ImportResult>(baseUrl, "/import/daily-bars", { source, path });
}

export async function startFullMarketSync(
  baseUrl: string,
  startDate: string,
  endDate: string,
  symbols?: string[]
): Promise<{ job: SyncJobStatus }> {
  if (!isTauriRuntime()) {
    const totalSymbols = symbols?.length ?? 2;
    return {
      job: {
        job_id: "preview",
        mode: "full_market_bootstrap",
        status: "completed",
        total_symbols: totalSymbols,
        completed_symbols: totalSymbols,
        failed_symbols: 0,
        imported_rows: totalSymbols * 10,
        current_symbol: null,
        start_date: startDate,
        end_date: endDate,
        errors: []
      }
    };
  }
  return serviceFetch<{ job: SyncJobStatus }>(baseUrl, "/sync/full-market", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}

export async function loadSyncJob(baseUrl: string, jobId: string): Promise<{ job: SyncJobStatus }> {
  if (!isTauriRuntime()) {
    return {
      job: {
        job_id: jobId,
        mode: "full_market_bootstrap",
        status: "completed",
        total_symbols: 2,
        completed_symbols: 2,
        failed_symbols: 0,
        imported_rows: 20,
        current_symbol: null,
        start_date: "2015-01-01",
        end_date: "2026-05-26",
        errors: []
      }
    };
  }
  return serviceFetch<{ job: SyncJobStatus }>(baseUrl, `/sync/jobs/${jobId}`);
}

export async function runBacktestWithDataService(
  baseUrl: string,
  strategy: StrategyConfig,
  settings: BacktestSettingsConfig
): Promise<BacktestResult> {
  if (!isTauriRuntime()) {
    return demoResult;
  }
  const response = await serviceFetch<{ result: BacktestResult }>(baseUrl, "/run/backtest", {
    strategy,
    settings
  });
  return response.result;
}

export async function runBacktestStreamWithDataService(
  baseUrl: string,
  strategy: StrategyConfig,
  settings: BacktestSettingsConfig,
  handlers: BacktestStreamHandlers = {}
): Promise<BacktestResult> {
  if (!isTauriRuntime()) {
    handlers.onPhase?.("校验参数");
    handlers.onPhase?.("读取本地数据");
    handlers.onProgress?.({ message: "扫描 2024-01-05：候选 1 只，持仓 0 只" });
    handlers.onTrade?.(demoResult.trades[0]);
    handlers.onResult?.(demoResult);
    return demoResult;
  }

  const response = await fetch(`${baseUrl}/run/backtest/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy, settings })
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text || "local data service request failed"}`);
  }
  if (!response.body) {
    throw new Error("Backtest stream is not available in this browser.");
  }

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";
  let finalResult: BacktestResult | null = null;

  const handleLine = (line: string) => {
    if (!line.trim()) {
      return;
    }
    const event = JSON.parse(line) as
      | { type: "phase"; phase: string }
      | { type: "progress"; message: string; trade_date?: string; scanned_days?: number; total_days?: number; open_positions?: number; closed_trades?: number; candidates?: number }
      | { type: "trade_opened"; trade: BacktestResult["trades"][number] }
      | { type: "trade_closed"; trade: BacktestResult["trades"][number] }
      | { type: "result"; result: BacktestResult }
      | { type: "error"; message?: string };
    if (event.type === "phase") {
      handlers.onPhase?.(event.phase);
    } else if (event.type === "progress") {
      handlers.onProgress?.(event);
    } else if (event.type === "trade_opened" || event.type === "trade_closed") {
      handlers.onTrade?.(event.trade);
    } else if (event.type === "result") {
      finalResult = event.result;
      handlers.onResult?.(event.result);
    } else if (event.type === "error") {
      throw new Error(event.message ?? "Backtest stream failed.");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      handleLine(line);
    }
  }
  buffer += decoder.decode();
  handleLine(buffer);

  if (!finalResult) {
    throw new Error("Backtest stream ended before a final result was produced.");
  }
  return finalResult;
}

export async function runConfiguredBacktest(strategy: StrategyConfig, settings: BacktestSettingsConfig): Promise<BacktestResult> {
  const response = await callBackend<{ result: BacktestResult }>({
    command: "run_backtest",
    strategy,
    settings,
    cache_dir: ".astock-cache"
  });
  return response.result;
}
