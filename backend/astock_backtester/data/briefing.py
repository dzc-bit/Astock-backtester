from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Literal
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from astock_backtester.models import (
    MarketBriefingLink,
    MarketBriefingResponse,
    MarketBriefingSection,
    MarketBriefingTable,
)


THS_FUPAN_URL = "https://stock.10jqka.com.cn/fupan/"
THS_ZAOPAN_URL = "https://stock.10jqka.com.cn/zaopan/"
THS_REFERER = "https://stock.10jqka.com.cn/"


def _clean_text(value: str | None, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", unescape(value or "")).strip()
    if max_length is not None and len(text) > max_length:
        return f"{text[:max_length].rstrip()}..."
    return text


def _node_text(node: Tag | None, max_length: int | None = None) -> str:
    return _clean_text(node.get_text(" ", strip=True) if node else "", max_length=max_length)


def _section_title(node: Tag, fallback: str) -> str:
    title_node = node.select_one("h1, h2, h3, strong, .title, .hd")
    title = _node_text(title_node)
    return title or fallback


def _table_from_node(table: Tag, title: str | None = None) -> MarketBriefingTable | None:
    rows: list[list[str]] = []
    for tr in table.select("tr"):
        cells = [_node_text(cell, max_length=160) for cell in tr.select("th,td")]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    if not rows:
        return None

    first_row_has_header = bool(table.select_one("th"))
    if first_row_has_header:
        columns = rows[0]
        data_rows = rows[1:]
    else:
        max_width = max(len(row) for row in rows)
        columns = [f"字段{index + 1}" for index in range(max_width)]
        data_rows = rows

    normalized_rows: list[dict[str, str]] = []
    for row in data_rows[:8]:
        normalized_rows.append(
            {
                columns[index] if index < len(columns) else f"字段{index + 1}": value
                for index, value in enumerate(row)
            }
        )
    if not normalized_rows:
        return None
    return MarketBriefingTable(title=title, columns=columns, rows=normalized_rows)


def _links_from_node(node: Tag, base_url: str, limit: int = 8) -> list[MarketBriefingLink]:
    links: list[MarketBriefingLink] = []
    seen: set[str] = set()
    for anchor in node.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        title = _clean_text(str(anchor.get("title") or "") or anchor.get_text(" ", strip=True), max_length=120)
        if not href or not title:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        links.append(MarketBriefingLink(title=title, url=url))
        seen.add(url)
        if len(links) >= limit:
            break
    return links


def _remove_non_textual_nodes(node: Tag) -> Tag:
    clone = BeautifulSoup(str(node), "html.parser")
    root = clone.find()
    if not isinstance(root, Tag):
        return node
    for child in root.select("script,style,table,a,img,svg,canvas"):
        child.decompose()
    return root


@dataclass
class MarketBriefingProvider:
    timeout: float = 8.0
    requester: Callable[..., requests.Response] = requests.get

    def latest_fupan(self) -> MarketBriefingResponse:
        try:
            soup = self._fetch_ths_html(THS_FUPAN_URL)
            return self._parse_fupan(soup)
        except Exception as exc:
            return self._fallback("fupan", THS_FUPAN_URL, f"同花顺复盘读取失败：{exc}")

    def latest_zaopan(self) -> MarketBriefingResponse:
        try:
            soup = self._fetch_ths_html(THS_ZAOPAN_URL)
            return self._parse_zaopan(soup)
        except Exception as exc:
            return self._fallback("zaopan", THS_ZAOPAN_URL, f"同花顺早盘读取失败：{exc}")

    def _fetch_ths_html(self, url: str) -> BeautifulSoup:
        response = self.requester(
            url,
            timeout=self.timeout,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": THS_REFERER,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        response.raise_for_status()
        response.encoding = getattr(response, "apparent_encoding", None) or response.encoding or "gbk"
        text = response.text
        return BeautifulSoup(text, "html.parser")

    def _parse_fupan(self, soup: BeautifulSoup) -> MarketBriefingResponse:
        summary = _node_text(soup.select_one("#fpzj"), max_length=260)
        sections: list[MarketBriefingSection] = []
        headers = soup.select(".fp_item_hd")
        contents = soup.select(".fp_item_cnt")
        for header, content in zip(headers, contents):
            title = _node_text(header.select_one("h1,h2,h3")) or _node_text(header, max_length=40)
            content_without_tables = _remove_non_textual_nodes(content)
            tables = [
                table
                for table in (_table_from_node(node, title=title) for node in content.select("table")[:2])
                if table is not None
            ]
            links = _links_from_node(content, THS_FUPAN_URL)
            body = _node_text(content_without_tables, max_length=360)
            if body or tables or links:
                sections.append(MarketBriefingSection(title=title or "复盘板块", content=body or None, links=links, tables=tables))
        return MarketBriefingResponse(
            kind="fupan",
            updated_at=datetime.now(timezone.utc),
            source="ths-fupan",
            source_url=THS_FUPAN_URL,
            summary=summary or "同花顺复盘已读取，但页面暂未提供摘要。",
            sections=sections[:8],
        )

    def _parse_zaopan(self, soup: BeautifulSoup) -> MarketBriefingResponse:
        summary = _node_text(soup.select_one(".yestoday"), max_length=220)
        sections: list[MarketBriefingSection] = []
        main = soup.select_one(".content-main-fl")
        if main:
            main_text_root = _remove_non_textual_nodes(main)
            tables = [
                table
                for table in (_table_from_node(node, title="早盘表格") for node in main.select("table")[:3])
                if table is not None
            ]
            content = _node_text(main_text_root, max_length=520)
            if content or tables:
                sections.append(
                    MarketBriefingSection(
                        title="早盘要点",
                        content=content or None,
                        links=_links_from_node(main, THS_ZAOPAN_URL),
                        tables=tables,
                    )
                )

        for part in soup.select(".content-main-fr .table-part")[:4]:
            title = _section_title(part, "早盘侧栏")
            tables = [
                table
                for table in (_table_from_node(node, title=title) for node in part.select("table")[:2])
                if table is not None
            ]
            content_root = _remove_non_textual_nodes(part)
            content = _node_text(content_root, max_length=260)
            if content or tables:
                sections.append(
                    MarketBriefingSection(
                        title=title,
                        content=content or None,
                        links=_links_from_node(part, THS_ZAOPAN_URL),
                        tables=tables,
                    )
                )
        fallback_summary = "同花顺早盘已读取，重点关注昨日行情、公司事项、机构观点和停复牌信息。"
        return MarketBriefingResponse(
            kind="zaopan",
            updated_at=datetime.now(timezone.utc),
            source="ths-zaopan",
            source_url=THS_ZAOPAN_URL,
            summary=summary or (sections[0].content[:220] if sections and sections[0].content else fallback_summary),
            sections=sections[:8],
        )

    def _fallback(
        self,
        kind: Literal["fupan", "zaopan"],
        source_url: str,
        diagnostic: str,
    ) -> MarketBriefingResponse:
        label = "复盘" if kind == "fupan" else "早盘"
        return MarketBriefingResponse(
            kind=kind,
            updated_at=datetime.now(timezone.utc),
            source="fallback",
            source_url=source_url,
            summary=f"同花顺{label}暂不可用，已保留{label}评价入口。",
            sections=[],
            diagnostics=[diagnostic],
        )
