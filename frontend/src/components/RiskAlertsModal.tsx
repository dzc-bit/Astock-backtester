import { AlertTriangle, X } from "lucide-react";
import type { RiskAlertsResponse } from "../types";

type Props = {
  open: boolean;
  alerts: RiskAlertsResponse | null;
  isLoading?: boolean;
  onClose: () => void;
  onRefresh: () => void;
};

const severityLabels = {
  high: "高风险",
  medium: "中风险",
  low: "低风险"
};

function isFailureDiagnostic(message: string): boolean {
  return /(失败|不可用|不存在|Could not open|Invalid data|超时|timeout|error|Exception)/i.test(message);
}

export function RiskAlertsModal({ open, alerts, isLoading = false, onClose, onRefresh }: Props) {
  if (!open) {
    return null;
  }
  const items = alerts?.items ?? [];
  const diagnostics = alerts?.diagnostics ?? [];
  const infoDiagnostics = diagnostics.filter((message) => !isFailureDiagnostic(message));
  const failureDiagnostics = diagnostics.filter(isFailureDiagnostic);
  const successSummary =
    items.length > 0
      ? `已加载本地风险观察名单 ${items.length} 只，实时扫描完成。`
      : "当前数据源没有识别到明确 ST、*ST 或退市风险。";
  return (
    <div className="modal-backdrop">
      <section className="risk-modal" role="dialog" aria-modal="true" aria-label="风险股票清单">
        <div className="modal-head">
          <div>
            <span className="section-kicker">ST / 退市风险</span>
            <h2>风险股票清单</h2>
          </div>
          <button className="icon-button" type="button" aria-label="关闭风险清单" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="risk-modal-toolbar">
          <span className="status-pill compact">
            <AlertTriangle size={15} aria-hidden="true" />
            {items.length} 条风险
          </span>
          <span className="status-pill compact">来源 {alerts?.source ?? "--"}</span>
          <button className="secondary-button" type="button" onClick={onRefresh} disabled={isLoading}>
            {isLoading ? "刷新中" : "刷新风险"}
          </button>
        </div>
        <div className="risk-modal-body">
          {items.length === 0 ? (
            <div className="empty-state">
              <strong>暂无明确风险股票</strong>
              <span>当前数据源没有识别到潜在 ST、*ST 或退市风险。</span>
              {diagnostics.length > 0 ? (
                <ul className="risk-diagnostics secondary" aria-label="风险数据诊断">
                  {diagnostics.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <>
              <div className="risk-modal-summary">
                <strong>{successSummary}</strong>
                {infoDiagnostics.slice(0, 2).map((message) => (
                  <span key={message}>{message}</span>
                ))}
              </div>
              {failureDiagnostics.length > 0 ? (
                <details className="risk-diagnostics-details">
                  <summary>辅助数据源诊断</summary>
                  <ul className="risk-diagnostics secondary" aria-label="风险数据诊断">
                    {failureDiagnostics.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                  </ul>
                </details>
              ) : null}
              <div className="risk-alert-list" aria-label="风险股票滚动列表">
                {items.map((item) => (
                  <article className={`risk-alert ${item.severity}`} key={`${item.symbol}-${item.risk_type}`}>
                    <div className="risk-alert-head">
                      <div className="risk-alert-identity">
                        <strong>{item.name}</strong>
                        <span>{item.symbol}</span>
                      </div>
                      <span className={`risk-severity-badge ${item.severity}`}>{severityLabels[item.severity]}</span>
                    </div>
                    <small className="risk-alert-type">{item.risk_type}</small>
                    <p>{item.reason}</p>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
