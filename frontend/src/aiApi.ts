import { BackendError, consumeNdjsonStream } from "./api";
import { isTauriRuntime } from "./tauriRuntime";
import type {
  AiChatEvent,
  AiChatHandlers,
  AiChatRequest,
  AiConfigUpdatePayload,
  AiConfigView,
  AiEventStreamEvent,
  AiStatus
} from "./aiTypes";
import {
  mockAiChatEvents,
  mockAiConfig,
  mockAiEventStream,
  mockAiSaveConfig,
  mockAiStatus
} from "./aiMocks";

const AI_CHAT_STREAM_IDLE_TIMEOUT_MS = 180_000;
const AI_EVENTS_IDLE_TIMEOUT_MS = 40_000;

export async function loadAiStatus(baseUrl: string): Promise<AiStatus> {
  if (!isTauriRuntime()) {
    return mockAiStatus();
  }
  const response = await fetch(`${baseUrl}/ai/status`);
  const json = await response.json();
  if (!response.ok) {
    throw new BackendError(typeof json.code === "string" ? json.code : "request_failed", "AI 状态查询失败");
  }
  return json as AiStatus;
}

export async function loadAiConfig(baseUrl: string): Promise<AiConfigView> {
  if (!isTauriRuntime()) {
    return mockAiConfig();
  }
  const response = await fetch(`${baseUrl}/ai/config`);
  const json = await response.json();
  if (!response.ok) {
    throw new BackendError(typeof json.code === "string" ? json.code : "request_failed", "AI 配置读取失败");
  }
  return json as AiConfigView;
}

export async function saveAiConfig(baseUrl: string, payload: AiConfigUpdatePayload): Promise<AiConfigView> {
  if (!isTauriRuntime()) {
    return mockAiSaveConfig(payload);
  }
  const response = await fetch(`${baseUrl}/ai/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const json = await response.json();
  if (!response.ok) {
    throw new BackendError(typeof json.code === "string" ? json.code : "request_failed", "AI 配置保存失败");
  }
  return json as AiConfigView;
}

export async function revealAiKey(baseUrl: string): Promise<string> {
  if (!isTauriRuntime()) {
    return "sk-demo-key-123456";
  }
  const response = await fetch(`${baseUrl}/ai/config/reveal`);
  const json = await response.json();
  if (!response.ok) {
    throw new BackendError(typeof json.code === "string" ? json.code : "request_failed", "读取 API Key 失败");
  }
  return String(json.api_key ?? "");
}

export async function runAiChatStream(
  baseUrl: string,
  request: AiChatRequest,
  handlers: AiChatHandlers = {},
  options: { signal?: AbortSignal } = {}
): Promise<void> {
  if (!isTauriRuntime()) {
    for (const event of mockAiChatEvents(request)) {
      dispatchChatEvent(event, handlers);
    }
    return;
  }
  await consumeNdjsonStream(
    `${baseUrl}/ai/chat/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(request)
    },
    options,
    AI_CHAT_STREAM_IDLE_TIMEOUT_MS,
    (line) => {
      if (!line.trim()) {
        return;
      }
      dispatchChatEvent(JSON.parse(line) as AiChatEvent, handlers);
    }
  );
}

function dispatchChatEvent(event: AiChatEvent, handlers: AiChatHandlers): void {
  if (event.type === "session") {
    handlers.onSession?.(event);
  } else if (event.type === "phase") {
    handlers.onPhase?.(event.phase);
  } else if (event.type === "token") {
    handlers.onToken?.(event.text);
  } else if (event.type === "tool_call") {
    handlers.onToolCall?.(event);
  } else if (event.type === "tool_result") {
    handlers.onToolResult?.(event);
  } else if (event.type === "result") {
    handlers.onResult?.(event);
  } else if (event.type === "error") {
    throw new BackendError(event.code ?? "request_failed", event.message ?? "AI 请求失败");
  }
}

/**
 * Long-lived AI events stream (insight / data_fresh / heartbeat). Resolves when
 * the stream ends or is aborted; callers typically reconnect with backoff.
 */
export async function openAiEventStream(
  baseUrl: string,
  onEvent: (event: AiEventStreamEvent) => void,
  options: { signal?: AbortSignal } = {}
): Promise<void> {
  if (!isTauriRuntime()) {
    for (const event of mockAiEventStream()) {
      if (options.signal?.aborted) {
        return;
      }
      onEvent(event);
    }
    return;
  }
  await consumeNdjsonStream(
    `${baseUrl}/ai/events/stream`,
    { headers: { Accept: "application/x-ndjson" } },
    options,
    AI_EVENTS_IDLE_TIMEOUT_MS,
    (line) => {
      if (!line.trim()) {
        return;
      }
      onEvent(JSON.parse(line) as AiEventStreamEvent);
    }
  );
}
