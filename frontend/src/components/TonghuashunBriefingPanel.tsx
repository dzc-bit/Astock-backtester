import { ExternalLink, FileText, Sunrise, X } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import type { MarketBriefingResponse, MarketBriefingTable } from "../types";

type Props = {
  fupan: MarketBriefingResponse | null;
  zaopan: MarketBriefingResponse | null;
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

function pickSection(briefing: MarketBriefingResponse | null, pattern: RegExp): string | null {
  if (!briefing || briefing.sections.length === 0) {
    return null;
  }
  const preferred = briefing.sections.find((section) => pattern.test(section.title));
  return (preferred ?? briefing.sections[0]).content ?? null;
}

function splitParagraphs(content: string | null | undefined): string[] {
  return (content ?? "")
    .split(/\n{2,}|\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isFullTextSection(title: string): boolean {
  return /^全文[:：]/.test(title.trim());
}

function BriefingCard({
  briefing,
  title,
  kicker,
  icon,
  accentClass,
  emptyText,
  sectionPattern,
  onOpen
}: {
  briefing: MarketBriefingResponse | null;
  title: string;
  kicker: string;
  icon: ReactNode;
  accentClass: string;
  emptyText: string;
  sectionPattern: RegExp;
  onOpen: () => void;
}) {
  const section = pickSection(briefing, sectionPattern);
  return (
    <article className={`ths-briefing-card ${accentClass}`}>
      <div className="ths-briefing-icon" aria-hidden="true">
        {icon}
      </div>
      <div className="ths-briefing-copy">
        <div className="ths-briefing-head">
          <div>
            <span>{kicker}</span>
            <h3>{title}</h3>
          </div>
          <div className="ths-briefing-actions">
            {briefing ? (
              <>
                <button className="secondary-button compact" type="button" onClick={onOpen} aria-label={`查看${title}全文`}>
                  查看全文
                </button>
                <a href={briefing.source_url} target="_blank" rel="noreferrer" aria-label={`打开${title}原文`}>
                  <ExternalLink size={15} aria-hidden="true" />
                </a>
              </>
            ) : null}
          </div>
        </div>
        {briefing ? (
          <>
            <div className="ths-briefing-meta">
              <span>{briefing.source}</span>
              <span>{formatTime(briefing.updated_at)}</span>
            </div>
            <strong>{briefing.summary}</strong>
            {section ? <p>{section}</p> : null}
            {briefing.diagnostics.length > 0 ? <small>{briefing.diagnostics[0]}</small> : null}
          </>
        ) : (
          <p className="ths-briefing-empty">{emptyText}</p>
        )}
      </div>
    </article>
  );
}

function BriefingTable({ table }: { table: MarketBriefingTable }) {
  const columns =
    table.columns.length > 0
      ? table.columns
      : Array.from(new Set(table.rows.flatMap((row) => Object.keys(row))));
  if (columns.length === 0 || table.rows.length === 0) {
    return null;
  }
  return (
    <div className="ths-briefing-table-wrap">
      {table.title ? <strong>{table.title}</strong> : null}
      <table className="ths-briefing-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={`${table.title ?? "table"}-${rowIndex}`}>
              {columns.map((column) => (
                <td key={column}>{row[column] ?? "--"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BriefingDialog({
  briefing,
  title,
  kicker,
  onClose
}: {
  briefing: MarketBriefingResponse;
  title: string;
  kicker: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop">
      <section className="ths-briefing-modal" role="dialog" aria-modal="true" aria-label={`${title}全文`}>
        <div className="modal-head">
          <div>
            <span className="section-kicker">{kicker}</span>
            <h2>{title}全文</h2>
          </div>
          <button className="icon-button" type="button" aria-label={`关闭${title}全文`} onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="ths-briefing-modal-meta">
          <span>来源 {briefing.source}</span>
          <span>更新 {formatTime(briefing.updated_at)}</span>
          <a href={briefing.source_url} target="_blank" rel="noreferrer">
            打开同花顺原文
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        </div>
        <div className="ths-briefing-modal-body">
          <article className="ths-briefing-full-summary">
            <span>重点摘要</span>
            <p>{briefing.summary}</p>
          </article>
          {briefing.sections.length === 0 ? (
            <div className="empty-state">
              <strong>暂无更多正文</strong>
              <span>当前接口只返回了摘要，稍后可刷新或打开同花顺原文查看。</span>
            </div>
          ) : (
            <section className="ths-briefing-reader" aria-label="阅读全文">
              <div className="ths-briefing-reader-head">
                <span>阅读全文</span>
                <small>已按段落整理，向下滚动可读完整尾部。</small>
              </div>
              {briefing.sections.map((section, sectionIndex) => {
                const paragraphs = splitParagraphs(section.content);
                return (
                  <article
                    className={`ths-briefing-section${isFullTextSection(section.title) ? " full-text-section" : ""}`}
                    key={`${section.title}-${sectionIndex}`}
                  >
                    {isFullTextSection(section.title) ? (
                      <span className="ths-briefing-section-badge">抓取到的原文详情</span>
                    ) : null}
                    <h3>{section.title}</h3>
                    {paragraphs.length > 0 ? (
                      <div className="ths-briefing-paragraphs">
                        {paragraphs.map((paragraph, paragraphIndex) => (
                          <p key={`${section.title}-${paragraphIndex}`}>{paragraph}</p>
                        ))}
                      </div>
                    ) : null}
                    {section.links.length > 0 ? (
                      <div className="ths-briefing-link-list">
                        {section.links.map((link, linkIndex) => (
                          <a href={link.url ?? briefing.source_url} target="_blank" rel="noreferrer" key={`${link.title}-${linkIndex}`}>
                            {link.title}
                            <ExternalLink size={13} aria-hidden="true" />
                          </a>
                        ))}
                      </div>
                    ) : null}
                    {section.tables.map((table, tableIndex) => (
                      <BriefingTable table={table} key={`${table.title ?? section.title}-${tableIndex}`} />
                    ))}
                  </article>
                );
              })}
            </section>
          )}
          {briefing.diagnostics.length > 0 ? (
            <ul className="risk-diagnostics" aria-label="同花顺总评诊断">
              {briefing.diagnostics.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export function TonghuashunBriefingPanel({ fupan, zaopan }: Props) {
  const [openKind, setOpenKind] = useState<MarketBriefingResponse["kind"] | null>(null);
  const activeBriefing = openKind === "fupan" ? fupan : openKind === "zaopan" ? zaopan : null;
  const activeTitle = openKind === "fupan" ? "同花顺复盘总评" : "同花顺早盘总评";
  const activeKicker = openKind === "fupan" ? "收盘复盘" : "盘前观察";

  return (
    <>
      <section className="ths-briefing-panel" aria-label="同花顺复盘与早盘总评">
        <BriefingCard
          briefing={fupan}
          title="同花顺复盘总评"
          kicker="收盘复盘"
          icon={<FileText size={20} />}
          accentClass="fupan"
          emptyText="复盘总评暂未返回，行情框仍保留本地收盘评价。"
          sectionPattern={/指数|概念|个股|解盘/}
          onOpen={() => setOpenKind("fupan")}
        />
        <BriefingCard
          briefing={zaopan}
          title="同花顺早盘总评"
          kicker="盘前观察"
          icon={<Sunrise size={20} />}
          accentClass="zaopan"
          emptyText="早盘总评暂未返回，资讯框仍会显示常规市场新闻。"
          sectionPattern={/早盘|公司|机构|停复牌/}
          onOpen={() => setOpenKind("zaopan")}
        />
      </section>
      {activeBriefing ? (
        <BriefingDialog briefing={activeBriefing} title={activeTitle} kicker={activeKicker} onClose={() => setOpenKind(null)} />
      ) : null}
    </>
  );
}
