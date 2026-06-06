import { AlertCircle, Newspaper, Sparkles } from "lucide-react";
import type { NewsSummaryResponse } from "../types";

type Props = {
  summary: NewsSummaryResponse | null;
  isLoading?: boolean;
};

function formatTime(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function NewsSummaryPanel({ summary, isLoading = false }: Props) {
  const themes = summary?.themes ?? [];
  return (
    <section className="surface news-summary-panel" aria-label="新闻汇总">
      <div className="section-title">
        <div>
          <span className="section-kicker">主题归纳</span>
          <h2>新闻汇总</h2>
        </div>
        <span className="status-pill compact news-source-count">
          <Newspaper size={15} aria-hidden="true" />
          {summary ? `${summary.item_count} 条新闻` : isLoading ? "汇总中" : "待连接"}
        </span>
      </div>

      {themes.length === 0 ? (
        <div className="empty-state">
          <strong>{isLoading ? "正在汇总今日新闻" : "暂无新闻汇总"}</strong>
          <span>后端 `/market/news-summary` 返回后，会展示主题、要点、风险和来源条数。</span>
        </div>
      ) : (
        <div className="news-summary-list">
          {themes.map((theme) => (
            <article className={`news-summary-topic ${theme.sentiment}`} key={theme.title}>
              <div className="news-summary-topic-head">
                <div>
                  <span>{theme.source_count} 个来源 / {theme.sentiment}</span>
                  <h3>{theme.title}</h3>
                </div>
                <Sparkles size={18} aria-hidden="true" />
              </div>
              <p>{theme.summary}</p>
              <div className="news-summary-columns">
                <section>
                  <strong>要点</strong>
                  {theme.headlines.length > 0 ? (
                    <ul>
                      {theme.headlines.map((point) => (
                        <li key={point}>{point}</li>
                      ))}
                    </ul>
                  ) : (
                    <span>暂无明确要点。</span>
                  )}
                </section>
                <section>
                  <strong>
                    <AlertCircle size={14} aria-hidden="true" />
                    风险
                  </strong>
                  {summary.risks.length > 0 ? (
                    <ul>
                      {summary.risks.slice(0, 4).map((risk) => (
                        <li key={risk}>{risk}</li>
                      ))}
                    </ul>
                  ) : (
                    <span>暂无集中风险。</span>
                  )}
                </section>
              </div>
            </article>
          ))}
        </div>
      )}

      {summary ? (
        <p className="news-summary-footnote">
          来源 {summary.source} / 更新 {formatTime(summary.updated_at)}
        </p>
      ) : null}
    </section>
  );
}
