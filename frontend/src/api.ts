import { invoke } from "@tauri-apps/api/core";
import type {
  BacktestResult,
  BacktestStreamHandlers,
  BacktestSettingsConfig,
  DataServiceHealth,
  DataServiceStatus,
  DailyBarsCoverageResponse,
  FetchResult,
  ImportResult,
  ConditionValidationResult,
  ClsFinanceResponse,
  MarketBriefingResponse,
  MarketNewsResponse,
  NewsSummaryResponse,
  RealtimeMarketSnapshot,
  RecommendedStrategiesResponse,
  RiskAlertsResponse,
  StockSymbolValidationResult,
  StrategyConfig,
  SyncJobStatus
} from "./types";
import { isTauriRuntime } from "./tauriRuntime";

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
      blocked_reason: null,
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  latest_strategy_matches: {
    signal_date: "2024-01-04",
    trade_date: "2024-01-04",
    matches: [
      {
        symbol: "AAA",
        name: "示例股份",
        close: 12,
        change_pct: 0.021,
        reasons: ["float market cap 8800000000 in [1000000000, 30000000000]", "3d main net inflow 6000000 >= 3000000"],
        signal_date: "2024-01-04",
        trade_date: "2024-01-04",
        rank_score: 1.4
      }
    ]
  },
  preflight_issues: []
};

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

const DEFAULT_SERVICE_TIMEOUT_MS = 12_000;
const LONG_RUNNING_SERVICE_TIMEOUT_MS = 300_000;
const HEALTH_SERVICE_TIMEOUT_MS = 60_000;
const CLS_FINANCE_SERVICE_TIMEOUT_MS = 30_000;

type ServiceFetchOptions = {
  timeoutMs?: number;
};

async function serviceFetch<T>(
  baseUrl: string,
  path: string,
  payload?: Record<string, unknown>,
  options: ServiceFetchOptions = {}
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_SERVICE_TIMEOUT_MS;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: payload ? "POST" : "GET",
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: controller.signal
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("本地数据服务请求超时，请稍后重试或重新连接本地服务。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
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
  return serviceFetch<DataServiceHealth>(baseUrl, "/health", undefined, { timeoutMs: HEALTH_SERVICE_TIMEOUT_MS });
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

type RealtimeSnapshotStreamEvent =
  | Partial<RealtimeMarketSnapshot> & {
      type: "indexes";
      indexes: RealtimeMarketSnapshot["indexes"];
      updated_at?: string;
    }
  | Partial<RealtimeMarketSnapshot> & {
      type: "breadth";
      breadth?: RealtimeMarketSnapshot["breadth"];
      updated_at?: string;
    }
  | Partial<RealtimeMarketSnapshot> & {
      type: "sectors";
      strong_sectors?: RealtimeMarketSnapshot["strong_sectors"];
      yesterday_strong_sectors?: RealtimeMarketSnapshot["yesterday_strong_sectors"];
      updated_at?: string;
    }
  | { type: "result"; snapshot: RealtimeMarketSnapshot }
  | { type: "error"; message?: string };

type RealtimeSnapshotStreamHandlers = {
  onSnapshot?: (snapshot: RealtimeMarketSnapshot) => void;
};

function partialRealtimeSnapshot(
  current: RealtimeMarketSnapshot | null,
  event: Exclude<RealtimeSnapshotStreamEvent, { type: "result" | "error" }>
): RealtimeMarketSnapshot {
  const now = event.updated_at ?? current?.updated_at ?? new Date().toISOString();
  const next: RealtimeMarketSnapshot = {
    status: current?.status ?? "stale",
    source: current?.source ?? "stream-partial",
    updated_at: now,
    market_phase: event.market_phase ?? current?.market_phase ?? "trading",
    indexes: current?.indexes ?? [],
    breadth: current?.breadth ?? null,
    strong_sectors: current?.strong_sectors ?? [],
    yesterday_strong_sectors: current?.yesterday_strong_sectors ?? [],
    message: current?.message ?? "实时行情分块加载中",
    diagnostics: event.diagnostics ?? current?.diagnostics ?? []
  };
  if (event.type === "indexes") {
    next.indexes = event.indexes;
    next.source = event.indexes[0]?.source ?? next.source;
    next.message = "实时指数已返回，继续加载红绿家数和板块";
  } else if (event.type === "breadth") {
    next.breadth = event.breadth ?? null;
    next.source = event.breadth?.source ?? next.source;
    next.message = "实时红绿家数已返回，继续加载板块";
  } else if (event.type === "sectors") {
    next.strong_sectors = event.strong_sectors ?? [];
    next.yesterday_strong_sectors = event.yesterday_strong_sectors ?? next.yesterday_strong_sectors;
    next.source = next.strong_sectors[0]?.source ?? next.source;
    next.message = "实时板块已返回，正在完成行情快照";
  }
  return next;
}

export async function loadRealtimeMarketSnapshotStream(
  baseUrl: string,
  handlers: RealtimeSnapshotStreamHandlers = {}
): Promise<RealtimeMarketSnapshot> {
  if (!isTauriRuntime()) {
    const snapshot = await loadRealtimeMarketSnapshot(baseUrl);
    handlers.onSnapshot?.(snapshot);
    return snapshot;
  }

  const response = await fetch(`${baseUrl}/realtime/market-snapshot/stream`, {
    headers: { Accept: "application/x-ndjson" }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`HTTP ${response.status}: ${text || "local data service request failed"}`);
  }
  if (!response.body) {
    throw new Error("Realtime market stream is not available in this browser.");
  }

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";
  let current: RealtimeMarketSnapshot | null = null;
  let finalResult: RealtimeMarketSnapshot | null = null;
  let streamError: string | null = null;

  const handleLine = (line: string) => {
    if (!line.trim()) {
      return;
    }
    const event = JSON.parse(line) as RealtimeSnapshotStreamEvent;
    if (event.type === "error") {
      streamError = event.message ?? "Realtime market stream failed.";
      return;
    }
    if (event.type === "result") {
      finalResult = event.snapshot;
      current = event.snapshot;
      handlers.onSnapshot?.(event.snapshot);
      return;
    }
    current = partialRealtimeSnapshot(current, event);
    handlers.onSnapshot?.(current);
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
    throw new Error(streamError ?? "Realtime market stream ended before a final result was produced.");
  }
  return finalResult;
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

export async function loadMarketBriefing(baseUrl: string, kind: "fupan" | "zaopan"): Promise<MarketBriefingResponse> {
  if (!isTauriRuntime()) {
    const now = new Date("2026-06-01T15:30:00+08:00").toISOString();
    return {
      kind,
      updated_at: now,
      source: "browser-preview",
      source_url: kind === "fupan" ? "https://stock.10jqka.com.cn/fupan/" : "https://stock.10jqka.com.cn/zaopan/",
      summary:
        kind === "fupan"
          ? "A股三大指数集体调整，煤炭、养鸡、AI应用等方向活跃，科技成长方向分化加剧。"
          : "早盘关注昨日行情回顾、公司事项、机构观点与停复牌信息，先看主线承接再决定仓位。",
      sections: [
        {
          title: kind === "fupan" ? "指数/概念分析" : "早盘要点",
          content:
            kind === "fupan"
              ? "强势题材集中在煤炭、养鸡和 AI 应用，若次日量能无法延续，应降低追高权重。"
              : "公司事项和机构观点提供盘前线索，但仍需用开盘后的红绿家数与板块强度确认。",
          links: [],
          tables: [
            {
              title: "示例表格",
              columns: ["方向", "观察点"],
              rows: [{ "方向": "AI应用", "观察点": "看成交额与龙头承接" }]
            }
          ]
        }
      ],
      diagnostics: []
    };
  }
  return serviceFetch<MarketBriefingResponse>(baseUrl, `/market/${kind}`);
}

export async function loadClsFinance(baseUrl: string): Promise<ClsFinanceResponse> {
  if (!isTauriRuntime()) {
    return {
      updated_at: new Date("2026-06-09T15:05:00+08:00").toISOString(),
      source: "browser-preview",
      source_url: "https://www.cls.cn/finance",
      preclose_px: 3959.337,
      tline: [
        { date: 20260609, minute: 930, last_px: 3977.539, change: 0.0047 },
        { date: 20260609, minute: 1030, last_px: 3966.391, change: -0.0028 },
        { date: 20260609, minute: 1330, last_px: 3998.12, change: 0.0098 },
        { date: 20260609, minute: 1500, last_px: 4015.5, change: 0.0142 }
      ],
      anchors: [
        {
          code: "cls80025",
          name: "PCB",
          article_id: 2394344,
          c_time: "2026-06-09 09:31:30",
          direction: "up",
          url: "https://www.cls.cn/plate?code=cls80025"
        },
        {
          code: "cls80081",
          name: "油气设服",
          article_id: 2394352,
          c_time: "2026-06-09 09:39:24",
          direction: "down",
          url: "https://www.cls.cn/plate?code=cls80081"
        }
      ],
      emotion: {
        market_degree: 56,
        shsz_balance: "2.64万亿",
        shsz_balance_change: "-1524亿",
        up_limit: 130,
        open_limit: 25,
        performance: "1.74%",
        breadth: {
          up: 3322,
          down: 2049,
          flat: 156,
          total: 5527,
          source: "browser-preview",
          distribution: { suspend: 12 }
        }
      },
      up_pool: [
        {
          symbol: "601869",
          name: "长飞光纤",
          change_pct: 0.1,
          last: 484.33,
          time: "2026-06-09 13:34:47",
          reason: "光纤|全球光纤光缆行业领先企业。",
          limit_up_days: 1,
          plates: [{ code: "cls81670", name: "光纤光缆", change_pct: 0.0393 }]
        }
      ],
      diagnostics: []
    };
  }
  return serviceFetch<ClsFinanceResponse>(baseUrl, "/market/finance", undefined, {
    timeoutMs: CLS_FINANCE_SERVICE_TIMEOUT_MS
  });
}

export async function loadNewsSummary(baseUrl: string): Promise<NewsSummaryResponse> {
  if (!isTauriRuntime()) {
    return {
      updated_at: new Date("2026-06-01T15:00:00+08:00").toISOString(),
      source: "browser-preview",
      item_count: 18,
      themes: [
        {
          title: "AI 应用与算力",
          summary: "政策、订单和产品发布共同催化，盘中热度延续。",
          sentiment: "positive",
          source_count: 8,
          headlines: ["应用端公司成交活跃", "算力链仍有资金关注"]
        },
        {
          title: "新能源设备",
          summary: "部分细分方向有修复，但持续性仍要看订单和价格信号。",
          sentiment: "neutral",
          source_count: 5,
          headlines: ["设备端反弹更明显", "龙头估值修复带动板块"]
        }
      ],
      highlights: ["AI 应用与算力消息热度靠前", "新能源设备出现局部修复"],
      risks: ["高位股波动加大", "行业价格压力仍在"],
      diagnostics: []
    };
  }
  return serviceFetch<NewsSummaryResponse>(baseUrl, "/market/news-summary");
}

export async function loadRiskAlerts(baseUrl: string): Promise<RiskAlertsResponse> {
  if (!isTauriRuntime()) {
    return {
      updated_at: new Date("2026-05-27T10:30:00+08:00").toISOString(),
      source: "browser-preview",
      diagnostics: [],
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
    if (mode === "exit" && text.trim() === "近5日涨幅小于3%") {
      return {
        ok: true,
        normalized_text: text.trim(),
        condition: {
          id: "expr-past-return-at-most",
          condition_id: "past_return_at_most",
          enabled: true,
          params: { window: 5, max: 0.03 },
          data_lag_days: 0,
          expression: text.trim()
        },
        errors: [],
        examples: ["近5日涨幅小于3%", "MACD死叉", "近3日主力净流出"]
      };
    }
    if (mode === "exit" && text.trim() === "MACD死叉") {
      return {
        ok: true,
        normalized_text: text.trim(),
        condition: {
          id: "expr-macd-dead-cross",
          condition_id: "macd_dead_cross",
          enabled: true,
          params: {},
          data_lag_days: 0,
          expression: text.trim()
        },
        errors: [],
        examples: ["近5日涨幅小于3%", "MACD死叉", "近3日主力净流出"]
      };
    }
    if (mode === "exit" && ["资金流出", "近3日主力净流出"].includes(text.trim())) {
      const rolling = text.trim() === "近3日主力净流出";
      return {
        ok: true,
        normalized_text: text.trim(),
        condition: {
          id: rolling ? "expr-capital-flow-out-3d" : "expr-capital-flow-out-today",
          condition_id: rolling ? "capital_flow_n_day_sum_at_most" : "capital_flow_today_at_most",
          enabled: true,
          params: rolling ? { window: 3, max: 0 } : { max: 0 },
          data_lag_days: 0,
          expression: text.trim()
        },
        errors: [],
        examples: ["近5日涨幅小于3%", "MACD死叉", "近3日主力净流出"]
      };
    }
    return {
      ok: false,
      normalized_text: text.trim(),
      condition: null,
      errors: [{ code: "unrecognized_condition", message: mode === "exit" ? "无法识别离场条件，请参考样例改写。" : "无法识别条件，请参考样例改写。" }],
      examples: mode === "exit" ? ["收盘价跌破3日均线", "近5日涨幅小于3%", "MACD死叉", "近3日主力净流出"] : ["收盘价站上20日均线", "量比2日介于1.2到2.5"]
    };
  }
  return serviceFetch<ConditionValidationResult>(baseUrl, "/strategy/conditions/validate", { text, mode });
}

export async function validateStockSymbols(baseUrl: string, symbols: string[]): Promise<StockSymbolValidationResult> {
  const normalizedSymbols = symbols.map((symbol) => symbol.trim()).filter(Boolean);
  if (!isTauriRuntime()) {
    const known = new Set(["600519", "000001"]);
    const valid = normalizedSymbols.filter((symbol) => known.has(symbol));
    return {
      ok: valid.length === normalizedSymbols.length,
      valid_symbols: valid,
      invalid_symbols: normalizedSymbols.filter((symbol) => !known.has(symbol)),
      normalized_symbols: normalizedSymbols,
      source: "browser-preview"
    };
  }
  return serviceFetch<StockSymbolValidationResult>(baseUrl, "/symbols/validate", { symbols: normalizedSymbols });
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
  return serviceFetch<FetchResult>(
    baseUrl,
    "/fetch/daily-bars",
    {
      symbols,
      start_date: startDate,
      end_date: endDate
    },
    { timeoutMs: LONG_RUNNING_SERVICE_TIMEOUT_MS }
  );
}

export async function fetchCapitalFlow(
  baseUrl: string,
  symbols: string[],
  startDate: string,
  endDate: string
): Promise<FetchResult> {
  if (!isTauriRuntime()) {
    if (symbols.length === 0) {
      return {
        status: "ok",
        imported_rows: 0,
        requested_symbols: [],
        fetched_symbols: [],
        missing_symbols: [],
        coverage: [
          { dataset: "daily_bars", symbols: 2, start_date: startDate, end_date: endDate, missing_rows: 0 },
          { dataset: "capital_flow", symbols: 2, start_date: startDate, end_date: endDate, missing_rows: 0 },
          { dataset: "market_cap", symbols: 2, start_date: startDate, end_date: endDate, missing_rows: 0 }
        ],
        logs: [{ level: "info", message: "Capital-flow backfill started for all preview symbols" }],
        diagnostics: [{ code: "capital_flow_backfill_job_started", requested_symbols: 2, source: "capital_flow_crawler" }],
        failures: [],
        job: {
          job_id: "preview-capital-flow",
          mode: "capital_flow_backfill",
          status: "completed",
          total_symbols: 2,
          completed_symbols: 2,
          failed_symbols: 0,
          imported_rows: 2,
          current_symbol: null,
          start_date: startDate,
          end_date: endDate,
          errors: []
        }
      };
    }
    return {
      status: "ok",
      imported_rows: symbols.length,
      requested_symbols: symbols,
      fetched_symbols: symbols,
      missing_symbols: [],
      coverage: [
        { dataset: "daily_bars", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 },
        { dataset: "capital_flow", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 },
        { dataset: "market_cap", symbols: symbols.length, start_date: startDate, end_date: endDate, missing_rows: 0 }
      ],
      logs: [{ level: "info", message: `Capital-flow crawler merged ${symbols.length} rows as primary main_net_inflow source` }],
      diagnostics: [{ code: "capital_flow_crawler_merge", merged_rows: symbols.length, source: "capital_flow_crawler" }],
      failures: []
    };
  }
  return serviceFetch<FetchResult>(
    baseUrl,
    "/fetch/capital-flow",
    {
      symbols,
      start_date: startDate,
      end_date: endDate
    },
    { timeoutMs: LONG_RUNNING_SERVICE_TIMEOUT_MS }
  );
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
  return serviceFetch<ImportResult>(baseUrl, "/import/daily-bars", { source, path }, { timeoutMs: LONG_RUNNING_SERVICE_TIMEOUT_MS });
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
  return serviceFetch<{ job: SyncJobStatus }>(
    baseUrl,
    "/sync/full-market",
    {
      symbols,
      start_date: startDate,
      end_date: endDate
    },
    { timeoutMs: LONG_RUNNING_SERVICE_TIMEOUT_MS }
  );
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

export async function cancelSyncJob(baseUrl: string, jobId: string): Promise<{ job: SyncJobStatus }> {
  if (!isTauriRuntime()) {
    return {
      job: {
        job_id: jobId,
        mode: "capital_flow_backfill",
        status: "cancelled",
        total_symbols: 2,
        completed_symbols: 1,
        failed_symbols: 0,
        processed_symbols: 1,
        skipped_symbols: 0,
        imported_rows: 1,
        returned_rows: 1,
        current_symbol: null,
        start_date: "2026-06-01",
        end_date: "2026-06-05",
        errors: []
      }
    };
  }
  return serviceFetch<{ job: SyncJobStatus }>(baseUrl, `/sync/jobs/${jobId}/cancel`, {});
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
      | { type: "trade_blocked"; trade: BacktestResult["trades"][number] }
      | { type: "result"; result: BacktestResult }
      | { type: "error"; message?: string };
    if (event.type === "phase") {
      handlers.onPhase?.(event.phase);
    } else if (event.type === "progress") {
      handlers.onProgress?.(event);
    } else if (event.type === "trade_opened" || event.type === "trade_closed" || event.type === "trade_blocked") {
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
