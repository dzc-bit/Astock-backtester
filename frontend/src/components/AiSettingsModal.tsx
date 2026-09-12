import { useEffect, useState } from "react";
import { Eye, EyeOff, Settings, X } from "lucide-react";
import { AI_API_STYLE_LABELS } from "../aiTypes";
import type { AiApiStyle, AiConfigUpdatePayload, AiConfigView } from "../aiTypes";

type Props = {
  open: boolean;
  config: AiConfigView | null;
  isSaving?: boolean;
  errorMessage?: string | null;
  onClose: () => void;
  onSave: (payload: AiConfigUpdatePayload) => void;
  onRevealKey?: () => Promise<string>;
};

export function AiSettingsModal({ open, config, isSaving = false, errorMessage, onClose, onSave, onRevealKey }: Props) {
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [keyVisible, setKeyVisible] = useState(false);
  const [apiStyle, setApiStyle] = useState<AiApiStyle>("chat-completions");
  const [temperature, setTemperature] = useState(0.3);
  const [maxSteps, setMaxSteps] = useState(8);
  const [insightsEnabled, setInsightsEnabled] = useState(true);
  const [insightMaxPerHour, setInsightMaxPerHour] = useState(6);

  useEffect(() => {
    if (!open || !config) {
      return;
    }
    setBaseUrl(config.base_url);
    setModel(config.model);
    setEmbeddingModel(config.embedding_model);
    setApiKey("");
    setKeyVisible(false);
    setApiStyle(config.api_style);
    setTemperature(config.temperature);
    setMaxSteps(config.max_steps);
    setInsightsEnabled(config.insights_enabled);
    setInsightMaxPerHour(config.insight_max_per_hour);
  }, [open, config]);

  const toggleKeyVisible = async () => {
    if (keyVisible) {
      setKeyVisible(false);
      return;
    }
    if (onRevealKey) {
      try {
        setApiKey(await onRevealKey());
      } catch {
        // 显示失败时退回普通输入
      }
    }
    setKeyVisible(true);
  };

  if (!open) {
    return null;
  }

  const submit = () => {
    onSave({
      base_url: baseUrl.trim(),
      model: model.trim(),
      embedding_model: embeddingModel.trim(),
      api_key: apiKey.trim(),
      api_style: apiStyle,
      temperature: Number.isFinite(temperature) ? temperature : 0.3,
      max_steps: Number.isFinite(maxSteps) ? maxSteps : 8,
      insights_enabled: insightsEnabled,
      insight_max_per_hour: Number.isFinite(insightMaxPerHour) ? insightMaxPerHour : 6
    });
  };

  return (
    <div className="modal-backdrop">
      <section className="ai-settings-modal" role="dialog" aria-modal="true" aria-label="AI 服务设置">
        <div className="modal-head">
          <div>
            <span className="section-kicker">OpenAI 兼容接口</span>
            <h2>AI 服务设置</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭 AI 设置" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="ai-settings-body">
          <label className="ai-field">
            <span>Base URL</span>
            <input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.deepseek.com/v1"
              autoComplete="off"
            />
          </label>
          <label className="ai-field">
            <span>模型名称</span>
            <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="deepseek-chat" autoComplete="off" />
          </label>
          <label className="ai-field">
            <span>API 协议格式</span>
            <select value={apiStyle} onChange={(event) => setApiStyle(event.target.value as AiApiStyle)}>
              {(Object.keys(AI_API_STYLE_LABELS) as AiApiStyle[]).map((style) => (
                <option key={style} value={style}>
                  {AI_API_STYLE_LABELS[style]}
                </option>
              ))}
            </select>
          </label>
          <div className="ai-field">
            <span className="ai-field-label-row">
              API Key {config?.api_key_masked ? `（已配置 ${config.api_key_masked}，留空保持不变）` : ""}
              {onRevealKey ? (
                <button
                  className="ai-reveal-button"
                  type="button"
                  aria-label={keyVisible ? "隐藏 API Key" : "显示 API Key"}
                  onClick={() => void toggleKeyVisible()}
                >
                  {keyVisible ? <EyeOff size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
                  {keyVisible ? "隐藏" : "显示"}
                </button>
              ) : null}
            </span>
            <input
              type={keyVisible ? "text" : "password"}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={config?.api_key_masked ? "留空保持现有 Key" : "sk-..."}
              autoComplete="new-password"
            />
          </div>
          <label className="ai-field">
            <span>Embedding 模型（可选，用于知识库检索）</span>
            <input
              value={embeddingModel}
              onChange={(event) => setEmbeddingModel(event.target.value)}
              placeholder="BAAI/bge-m3"
              autoComplete="off"
            />
          </label>
          <div className="ai-field-row">
            <label className="ai-field">
              <span>单次问题最大工具步数</span>
              <input
                type="number"
                min={1}
                max={16}
                value={maxSteps}
                onChange={(event) => setMaxSteps(Number(event.target.value))}
              />
            </label>
            <label className="ai-field">
              <span>每小时 AI 快讯上限</span>
              <input
                type="number"
                min={0}
                max={60}
                value={insightMaxPerHour}
                onChange={(event) => setInsightMaxPerHour(Number(event.target.value))}
              />
            </label>
          </div>
          <label className="ai-checkbox">
            <input type="checkbox" checked={insightsEnabled} onChange={(event) => setInsightsEnabled(event.target.checked)} />
            <span>启用 AI 快讯推送（规则触发 + 节流，内容标注为 AI 生成）</span>
          </label>
          <p className="ai-settings-note">配置保存在本地用户数据目录（运行产物/AI配置），不会进入 Git 仓库。</p>
          {errorMessage ? <div className="error-banner" role="alert">{errorMessage}</div> : null}
        </div>
        <div className="ai-settings-actions">
          <button className="secondary-button" type="button" onClick={onClose}>
            取消
          </button>
          <button className="primary-button" type="button" onClick={submit} disabled={isSaving}>
            <Settings size={15} aria-hidden="true" />
            {isSaving ? "保存中" : "保存配置"}
          </button>
        </div>
      </section>
    </div>
  );
}
