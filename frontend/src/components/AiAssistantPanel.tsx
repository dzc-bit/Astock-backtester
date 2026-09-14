import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { AlertTriangle, Bot, Download, Send, Settings2, Sparkles, Square, X } from "lucide-react";
import {
  loadAiConfig,
  loadAiReportFile,
  loadAiReports,
  loadAiStatus,
  revealAiKey,
  runAiChatStream,
  saveAiConfig
} from "../aiApi";
import { translateAiError } from "../aiTypes";
import type {
  AiChartArtifact,
  AiChatContext,
  AiConfigUpdatePayload,
  AiConfigView,
  AiDisplayTurn,
  AiInsight,
  AiReportMeta,
  AiStatus,
  AiTask,
  AiToolStep
} from "../aiTypes";
import type { StrategyConfig } from "../types";
import { AiEquityChart } from "./AiEquityChart";
import { AiSettingsModal } from "./AiSettingsModal";

type Props = {
  open: boolean;
  baseUrl: string | null;
  insights: AiInsight[];
  task: AiTask | null;
  onTaskConsumed: () => void;
  onClose: () => void;
  onApplyStrategy?: (strategy: StrategyConfig) => void;
  onInsightsShown?: () => void;
};

const QUICK_PROMPTS: Array<{ label: string; message: string }> = [
  { label: "大盘快评", message: "结合当前实时行情和最新新闻，做一次大盘快评。" },
  { label: "今日复盘要点", message: "根据同花顺复盘和早盘内容，总结今日市场主线与风险点。" },
  {
    label: "设计放量突破策略",
    message:
      "帮我设计一个放量突破策略：入场用 近5日涨幅0%到12%、突破20日新高、换手率2%到8%，离场用 跌破10日均线，然后用自定义几只大盘股跑一次最近一年的回测并解读。"
  }
];

export function AiAssistantPanel({
  open,
  baseUrl,
  insights,
  task,
  onTaskConsumed,
  onClose,
  onApplyStrategy,
  onInsightsShown
}: Props) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [turns, setTurns] = useState<AiDisplayTurn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [pendingSteps, setPendingSteps] = useState<AiToolStep[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [config, setConfig] = useState<AiConfigView | null>(null);
  const [configSaving, setConfigSaving] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [lastStrategy, setLastStrategy] = useState<StrategyConfig | null>(null);
  const [lastChart, setLastChart] = useState<AiChartArtifact | null>(null);
  const [reports, setReports] = useState<AiReportMeta[]>([]);
  const [reportBusy, setReportBusy] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const streamingRef = useRef(false);
  const pendingTaskRef = useRef<AiTask | null>(null);
  const streamingTextRef = useRef("");

  useEffect(() => {
    if (!open || !baseUrl) {
      return;
    }
    let cancelled = false;
    loadAiStatus(baseUrl)
      .then((next) => {
        if (!cancelled) {
          setStatus(next);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStatus(null);
        }
      });
    loadAiReports(baseUrl)
      .then((next) => {
        if (!cancelled) {
          setReports(next.items ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setReports([]);
        }
      });
    onInsightsShown?.();
    return () => {
      cancelled = true;
    };
  }, [open, baseUrl, onInsightsShown]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [turns, streamingText, pendingSteps, phase, open]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!open || !task) {
      return;
    }
    onTaskConsumed();
    if (streamingRef.current) {
      // 流式回答期间到达的场景任务先排队，当前轮结束后自动发送，避免静默丢弃。
      pendingTaskRef.current = task;
      return;
    }
    void sendMessage(task.message, task.context ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, task]);

  const sendMessage = async (message: string, context: AiChatContext | null = null) => {
    const trimmed = message.trim();
    if (!trimmed || !baseUrl || streamingRef.current) {
      return;
    }
    streamingRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    setTurns((prev) => [...prev, { role: "user", content: trimmed }]);
    setStreaming(true);
    setStreamingText("");
    streamingTextRef.current = "";
    setPendingSteps([]);
    setPhase("准备请求");
    setError(null);
    try {
      await runAiChatStream(
        baseUrl,
        { message: trimmed, session_id: sessionId, context },
        {
          onSession: (event) => setSessionId(event.session_id),
          onPhase: setPhase,
          onToken: (text) => {
            streamingTextRef.current += text;
            setStreamingText((prev) => prev + text);
          },
          onToolCall: (event) =>
            setPendingSteps((prev) => [...prev, { id: event.id, name: event.name }]),
          onToolResult: (event) =>
            setPendingSteps((prev) =>
              prev.map((step) =>
                step.id === event.id
                  ? { ...step, ok: event.ok, summary: event.summary, duration_ms: event.duration_ms }
                  : step
              )
            ),
          onResult: (event) => {
            setTurns(event.display ?? []);
            setSessionId(event.session_id);
            setLastChart(event.chart ?? null);
            if (event.strategy) {
              // 策略工件保持 sticky：后续普通问答不会把已生成策略“冲掉”。
              setLastStrategy(event.strategy);
            }
          }
        },
        { signal: controller.signal }
      );
    } catch (caught) {
      if (!controller.signal.aborted) {
        if (streamingTextRef.current) {
          const partial = streamingTextRef.current;
          setTurns((prev) => [...prev, { role: "assistant", content: `${partial}\n\n（回答中断，可重试。）` }]);
        }
        setError(translateAiError(caught));
      }
    } finally {
      // 只有当前请求仍持有 abort 句柄时才清理 UI 状态，避免“停止后立刻重发”的竞态。
      if (abortRef.current === controller) {
        abortRef.current = null;
        streamingRef.current = false;
        setStreaming(false);
        setPhase(null);
        setStreamingText("");
        streamingTextRef.current = "";
        setPendingSteps([]);
      }
      const queued = pendingTaskRef.current;
      pendingTaskRef.current = null;
      if (queued) {
        void sendMessage(queued.message, queued.context ?? null);
      }
    }
  };

  const stopStreaming = () => {
    abortRef.current?.abort();
  };

  const downloadReport = async (report: AiReportMeta) => {
    if (!baseUrl) {
      return;
    }
    setReportBusy(report.name);
    try {
      const content = await loadAiReportFile(baseUrl, report.name);
      const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = report.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      // 下载失败保持安静：列表仍在，可重试。
    } finally {
      setReportBusy(null);
    }
  };

  const openSettings = async () => {
    setSettingsOpen(true);
    setConfigError(null);
    if (!baseUrl) {
      return;
    }
    try {
      setConfig(await loadAiConfig(baseUrl));
    } catch (caught) {
      setConfigError(translateAiError(caught));
    }
  };

  const saveConfig = async (payload: AiConfigUpdatePayload) => {
    if (!baseUrl) {
      return;
    }
    setConfigSaving(true);
    setConfigError(null);
    try {
      const saved = await saveAiConfig(baseUrl, payload);
      setConfig(saved);
      setSettingsOpen(false);
      const nextStatus = await loadAiStatus(baseUrl);
      setStatus(nextStatus);
    } catch (caught) {
      setConfigError(translateAiError(caught));
    } finally {
      setConfigSaving(false);
    }
  };

  if (!open) {
    return null;
  }

  const unconfigured = status != null && !status.configured;

  return (
    <aside className="ai-drawer" role="dialog" aria-modal="false" aria-label="AI 投研助手">
      <header className="ai-drawer-head">
        <div className="ai-drawer-title">
          <Sparkles size={18} aria-hidden="true" />
          <div>
            <strong>AI 投研助手</strong>
            <small>
              {status
                ? status.configured
                  ? `${status.model} · ${status.tool_names.length} 个工具${status.memory_count ? ` · 记忆 ${status.memory_count} 条` : ""}`
                  : "未配置模型"
                : baseUrl
                  ? "连接中…"
                  : "等待本地服务连接"}
            </small>
          </div>
        </div>
        <div className="ai-drawer-actions">
          <button className="icon-button" type="button" aria-label="AI 服务设置" onClick={() => void openSettings()}>
            <Settings2 size={17} aria-hidden="true" />
          </button>
          <button className="icon-button" type="button" aria-label="关闭 AI 助手" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </header>

      {unconfigured ? (
        <div className="ai-unconfigured">
          <AlertTriangle size={18} aria-hidden="true" />
          <div>
            <strong>AI 服务尚未配置</strong>
            <span>填写 OpenAI 兼容接口的 Base URL、API Key 与模型名后即可开始使用。</span>
            <button className="secondary-button" type="button" onClick={() => void openSettings()}>
              前往设置
            </button>
          </div>
        </div>
      ) : null}

      {insights.length > 0 ? (
        <details className="ai-insights">
          <summary>AI 快讯（{insights.length}）</summary>
          <ul>
            {insights.map((insight) => (
              <li key={insight.id} className={`ai-insight ${insight.level}`}>
                <strong>{insight.title}</strong>
                <span>{insight.digest}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {reports.length > 0 ? (
        <details className="ai-insights" open>
          <summary>定时报告（{reports.length}）</summary>
          <ul>
            {reports.slice(0, 8).map((report) => (
              <li key={report.name} className="ai-insight ai-report-item">
                <strong>{report.name.replace(/\.md$/, "")}</strong>
                <button
                  className="ai-reveal-button"
                  type="button"
                  disabled={reportBusy === report.name}
                  onClick={() => void downloadReport(report)}
                >
                  <Download size={13} aria-hidden="true" />
                  {reportBusy === report.name ? "下载中" : "下载"}
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <div className="ai-messages" ref={scrollRef}>
        {turns.length === 0 && !streaming ? (
          <div className="ai-empty">
            <Bot size={26} aria-hidden="true" />
            <strong>问行情、评个股、写策略、解读回测</strong>
            <span>所有数字都来自本地工具查询，不构成投资建议。</span>
            <div className="ai-chips">
              {QUICK_PROMPTS.map((prompt) => (
                <button key={prompt.label} type="button" className="ai-chip" onClick={() => void sendMessage(prompt.message)}>
                  {prompt.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {turns.map((turn, index) => (
          <article key={`${turn.role}-${index}`} className={`ai-msg ${turn.role}`}>
            {turn.role === "assistant" && turn.tool_steps && turn.tool_steps.length > 0 ? (
              <details className="ai-steps">
                <summary>
                  已调用 {turn.tool_steps.length} 个工具
                  {turn.tool_steps.some((step) => step.ok === false) ? "（含失败）" : ""}
                </summary>
                <ul>
                  {turn.tool_steps.map((step) => (
                    <li key={step.id} className={step.ok === false ? "failed" : undefined}>
                      <span className="ai-step-name">{step.name}</span>
                      <span className="ai-step-summary">{step.summary}</span>
                      {step.duration_ms != null ? <small>{step.duration_ms}ms</small> : null}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            {turn.role === "assistant" && lastChart && index === turns.length - 1 ? (
              <AiEquityChart title={lastChart.title} points={lastChart.points} />
            ) : null}
            {turn.role === "assistant" && lastStrategy && index === turns.length - 1 && onApplyStrategy ? (
              <button
                type="button"
                className="secondary-button ai-apply-strategy"
                onClick={() => {
                  onApplyStrategy(lastStrategy);
                  onClose();
                }}
              >
                应用到策略工作台
              </button>
            ) : null}
            <div className="ai-markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                {turn.content}
              </ReactMarkdown>
            </div>
          </article>
        ))}

        {streaming ? (
          <article className="ai-msg assistant streaming" aria-busy="true">
            {phase ? <div className="ai-phase">{phase}</div> : null}
            {pendingSteps.length > 0 ? (
              <ul className="ai-steps-live">
                {pendingSteps.map((step) => (
                  <li key={step.id} className={step.ok === false ? "failed" : step.ok === true ? "done" : undefined}>
                    <span className="ai-step-name">{step.name}</span>
                    {step.summary ? <span className="ai-step-summary">{step.summary}</span> : <span className="ai-step-summary">执行中…</span>}
                  </li>
                ))}
              </ul>
            ) : null}
            {streamingText ? (
              <div className="ai-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                  {streamingText}
                </ReactMarkdown>
              </div>
            ) : null}
          </article>
        ) : null}

        {error ? <div className="error-banner" role="alert">{error}</div> : null}
      </div>

      <footer className="ai-composer">
        <div className="ai-composer-row">
          <textarea
            value={input}
            rows={2}
            placeholder="例如：帮我看看 600519，结合技术面、资金面和估值给个诊断。"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void sendMessage(input);
              }
            }}
          />
          {streaming ? (
            <button className="secondary-button" type="button" aria-label="停止生成" onClick={stopStreaming}>
              <Square size={15} aria-hidden="true" />
              停止
            </button>
          ) : (
            <button
              className="primary-button"
              type="button"
              aria-label="发送"
              disabled={!input.trim() || !baseUrl || unconfigured}
              onClick={() => void sendMessage(input)}
            >
              <Send size={15} aria-hidden="true" />
              发送
            </button>
          )}
        </div>
        <small className="ai-disclaimer">AI 生成内容仅供辅助观察，不构成投资建议；数据均来自本地服务与公开数据源。</small>
      </footer>

      <AiSettingsModal
        open={settingsOpen}
        config={config}
        isSaving={configSaving}
        errorMessage={configError}
        onClose={() => setSettingsOpen(false)}
        onSave={(payload) => void saveConfig(payload)}
        onRevealKey={baseUrl ? () => revealAiKey(baseUrl) : undefined}
      />
    </aside>
  );
}
