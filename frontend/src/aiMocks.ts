import type {
  AiChatEvent,
  AiChatRequest,
  AiConfigUpdatePayload,
  AiConfigView,
  AiEventStreamEvent,
  AiStatus
} from "./aiTypes";
import type { StrategyConfig } from "./types";

export function mockAiStatus(): AiStatus {
  return {
    configured: true,
    base_url: "https://mock.local/v1",
    model: "demo-model",
    insights_enabled: true,
    tool_names: ["realtime_market_snapshot", "market_news", "recent_daily_bars", "run_strategy_backtest"],
    knowledge_documents: 3,
    knowledge_chunks: 24,
    knowledge_ready: true
  };
}

export function mockAiConfig(): AiConfigView {
  return {
    base_url: "https://mock.local/v1",
    model: "demo-model",
    embedding_model: "demo-embedding",
    api_key_masked: "sk-****demo",
    temperature: 0.3,
    max_steps: 8,
    insights_enabled: true,
    insight_max_per_hour: 6,
    configured: true
  };
}

export function mockAiSaveConfig(payload: AiConfigUpdatePayload): AiConfigView {
  return {
    ...mockAiConfig(),
    base_url: payload.base_url,
    model: payload.model,
    embedding_model: payload.embedding_model,
    configured: Boolean(payload.base_url && payload.model)
  };
}

const DEMO_STRATEGY: StrategyConfig = {
  name: "AI 生成策略",
  market_filters: [],
  entry_groups: [
    {
      id: "ai-entry-group",
      operator: "and",
      conditions: [
        {
          id: "ai-entry-0",
          condition_id: "close_above_ma",
          enabled: true,
          params: { window: 20 },
          data_lag_days: 0,
          expression: "收盘价站上20日均线"
        }
      ]
    }
  ],
  exit_rules: [
    {
      id: "ai-exit-0",
      condition_id: "macd_dead_cross",
      enabled: true,
      params: {},
      data_lag_days: 0,
      expression: "MACD死叉"
    }
  ],
  score_threshold: null
};

export function mockAiChatEvents(request: AiChatRequest): AiChatEvent[] {
  const reply = request.context?.kind === "backtest_result"
    ? "本次回测总收益 12.4%，最大回撤 5.2%，胜率 58.3%，共 24 笔交易。收益主要由 3 月上旬的量能放大阶段贡献；回撤集中在 4 月中旬的连续止损。建议关注止盈参数的敏感性。以上为 AI 生成内容，仅供辅助观察，不构成投资建议。"
    : "市场当前红盘 3200 / 全市场 5120，上证指数 3100 点（+0.65%）。半导体板块领涨 3.8%。整体情绪偏暖，但宽度尚未过热。以上为 AI 生成内容，仅供辅助观察，不构成投资建议。";
  return [
    { type: "session", session_id: "mock-session", title: "演示会话" },
    { type: "phase", phase: "思考中（第 1/8 步）" },
    { type: "tool_call", id: "t1", name: "realtime_market_snapshot", args: {} },
    { type: "tool_result", id: "t1", name: "realtime_market_snapshot", ok: true, summary: "状态 live / 来源 mock；上证指数 3100 (+0.65%)", duration_ms: 320 },
    { type: "tool_call", id: "t2", name: "recent_daily_bars", args: { symbol: "600519" } },
    { type: "tool_result", id: "t2", name: "recent_daily_bars", ok: true, summary: "600519 贵州茅台 最近 30 个交易日：区间 +5.20%", duration_ms: 210 },
    { type: "phase", phase: "思考中（第 2/8 步）" },
    { type: "token", text: reply.slice(0, 20) },
    { type: "token", text: reply.slice(20) },
    {
      type: "result",
      session_id: "mock-session",
      display: [
        { role: "user", content: request.message },
        {
          role: "assistant",
          content: reply,
          tool_steps: [
            { id: "t1", name: "realtime_market_snapshot", ok: true, summary: "状态 live / 来源 mock", duration_ms: 320 },
            { id: "t2", name: "recent_daily_bars", ok: true, summary: "600519 最近 30 日区间 +5.20%", duration_ms: 210 }
          ]
        }
      ],
      strategy: request.context?.kind === "none" || !request.context ? DEMO_STRATEGY : null
    }
  ];
}

export function mockAiEventStream(): AiEventStreamEvent[] {
  // 仅含 insight：data_fresh 会触发页面模块即时刷新，破坏预览与测试的确定性。
  return [
    {
      type: "insight",
      insight: {
        id: "mock-insight-1",
        created_at: new Date().toISOString(),
        level: "info",
        title: "市场宽度快速回暖",
        digest: "红盘占比从 42% 回升至 62%，半导体板块领涨。AI 快讯，不构成投资建议。",
        source: "ai-insight",
        disclaimer: "AI 生成内容，仅供辅助观察，不构成投资建议"
      }
    }
  ];
}
