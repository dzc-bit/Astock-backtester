from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Callable, Literal
from urllib.parse import urljoin
from urllib.parse import urlparse

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
THS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _clean_text(value: str | None, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", unescape(value or "")).strip()
    if max_length is not None and len(text) > max_length:
        return f"{text[:max_length].rstrip()}..."
    return text


def _node_text(node: Tag | None, max_length: int | None = None) -> str:
    return _clean_text(node.get_text(" ", strip=True) if node else "", max_length=max_length)


_TIMESTAMP_PATTERN = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?")
_NUMERIC_TOKEN_PATTERN = re.compile(r"^[+-]?\d+(?:\.\d+)?%?$")


def _is_percent_text(value: str) -> bool:
    return bool(re.search(r"[+-]?\d+(?:\.\d+)?%", value))


def _is_number_text(value: str) -> bool:
    return bool(re.search(r"[+-]?\d+(?:\.\d+)?", value))


def _neutral_columns(width: int) -> list[str]:
    labels = ["名称", "数值一", "数值二", "数值三", "数值四", "数值五", "数值六", "数值七"]
    return [labels[index] if index < len(labels) else f"数值{index + 1}" for index in range(width)]


def _infer_table_columns(rows: list[list[str]], title: str | None) -> list[str]:
    width = max(len(row) for row in rows)
    first_data_row = next((row for row in rows if row), [])
    title_text = title or ""
    second_is_percent = len(first_data_row) > 1 and _is_percent_text(first_data_row[1])
    third_is_number = len(first_data_row) > 2 and _is_number_text(first_data_row[2])
    stock_like_title = any(keyword in title_text for keyword in ("个股", "股票", "热门个股", "异动个股"))
    rank_like_title = any(keyword in title_text for keyword in ("涨幅榜", "跌幅榜", "排行榜", "榜单"))

    if width >= 3 and second_is_percent and third_is_number:
        base = ["个股", "涨幅", "现价"] if stock_like_title else ["名称", "涨跌幅", "最新价"]
        return base + _neutral_columns(width)[len(base) :]
    if width == 2 and second_is_percent:
        return ["个股", "涨幅"] if stock_like_title else ["名称", "涨跌幅"]
    if rank_like_title and width >= 2:
        base = ["名称", "涨跌幅", "最新价"]
        return base[:width] + _neutral_columns(width)[len(base[:width]) :]
    return _neutral_columns(width)


def _is_noisy_content_line(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return True
    timestamp_count = len(_TIMESTAMP_PATTERN.findall(cleaned))
    without_timestamps = _TIMESTAMP_PATTERN.sub("", cleaned).strip()
    if timestamp_count >= 2 and len(without_timestamps) <= 24:
        return True

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", without_timestamps))
    digit_count = len(re.findall(r"\d", without_timestamps))
    text_length = max(len(re.sub(r"\s+", "", without_timestamps)), 1)
    numeric_tokens = [
        token
        for token in re.split(r"\s+", without_timestamps)
        if token and (_NUMERIC_TOKEN_PATTERN.match(token) or re.search(r"\d", token))
    ]
    if digit_count >= 8 and cjk_count <= 6 and digit_count / text_length >= 0.35:
        return True
    if len(numeric_tokens) >= 4 and cjk_count <= 8 and not re.search(r"[，。；、：]", without_timestamps):
        return True
    return False


def _readable_content_from_node(node: Tag | None) -> str:
    if node is None:
        return ""
    blocks = [_node_text(block) for block in node.select("h1,h2,h3,p,li")]
    if not blocks:
        blocks = [_node_text(node)]
    filtered = [block for block in blocks if block and not _is_noisy_content_line(block)]
    return _clean_text(" ".join(filtered))


def _ths_headers(referer: str = THS_REFERER) -> dict[str, str]:
    return {
        "User-Agent": THS_USER_AGENT,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


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
        columns = _infer_table_columns(rows, title)
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


def _is_ths_article_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.netloc.endswith("stock.10jqka.com.cn") and parsed.path.endswith(".shtml")


def _article_title(soup: BeautifulSoup, fallback: str) -> str:
    title = _node_text(soup.select_one("h1"))
    if title:
        return title
    meta_title = soup.select_one('meta[property="og:title"], meta[name="title"]')
    if meta_title:
        title = _clean_text(str(meta_title.get("content") or ""))
        if title:
            return title
    page_title = _node_text(soup.title)
    return re.sub(r"[_-].*$", "", page_title).strip() or fallback


def _article_body(soup: BeautifulSoup) -> str | None:
    selectors = (
        "article",
        ".main-text",
        ".art_context",
        ".artText",
        ".detail-content",
        ".news-content",
        ".article-content",
        ".post-content",
    )
    container = next((node for selector in selectors for node in soup.select(selector) if isinstance(node, Tag)), None)
    if container is None:
        paragraphs = [_node_text(node) for node in soup.select("p")]
    else:
        for child in container.select("script,style,a,img,svg,canvas,iframe"):
            child.decompose()
        paragraphs = [_node_text(node) for node in container.select("p,li")]
        if not paragraphs:
            paragraphs = [_node_text(container)]
    paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) >= 8 and not _is_noisy_content_line(paragraph)]
    if not paragraphs:
        return None
    return "\n\n".join(paragraphs)


@dataclass
class MarketBriefingProvider:
    timeout: float = 8.0
    requester: Callable[..., requests.Response] = field(default_factory=lambda: requests.Session().get)

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
        response = self._request_ths(url)
        text = self._response_text(response)
        if not _clean_text(text):
            self._prewarm_ths_session()
            response = self._request_ths(url)
            text = self._response_text(response)
        if not _clean_text(text):
            raise ValueError(f"同花顺返回空页面：{url}")
        return BeautifulSoup(text, "html.parser")

    def _request_ths(self, url: str) -> requests.Response:
        return self.requester(url, timeout=self.timeout, headers=_ths_headers())

    def _fetch_article_section(self, link: MarketBriefingLink, referer: str) -> tuple[MarketBriefingSection | None, str | None]:
        if not _is_ths_article_url(link.url):
            return None, None
        try:
            response = self.requester(link.url, timeout=self.timeout, headers=_ths_headers(referer=referer))
            text = self._response_text(response)
            soup = BeautifulSoup(text, "html.parser")
            body = _article_body(soup)
            if not body:
                return None, f"同花顺文章详情未解析到正文：{link.title}"
            title = _article_title(soup, link.title)
            return MarketBriefingSection(
                title=f"全文：{title}",
                content=body,
                links=[link],
                tables=[],
            ), None
        except Exception as exc:
            return None, f"同花顺文章详情抓取失败：{link.title} - {exc}"

    def _expand_article_links(
        self,
        sections: list[MarketBriefingSection],
        referer: str,
        limit: int = 4,
    ) -> tuple[list[MarketBriefingSection], list[str]]:
        expanded = list(sections)
        diagnostics: list[str] = []
        seen_urls: set[str] = set()
        for section in sections:
            for link in section.links:
                if not link.url or link.url in seen_urls:
                    continue
                seen_urls.add(link.url)
                detail, diagnostic = self._fetch_article_section(link, referer)
                if detail is not None:
                    expanded.append(detail)
                if diagnostic is not None:
                    diagnostics.append(diagnostic)
                if len(expanded) >= len(sections) + limit:
                    return expanded, diagnostics
        return expanded, diagnostics

    def _response_text(self, response: requests.Response) -> str:
        response.raise_for_status()
        response.encoding = getattr(response, "apparent_encoding", None) or response.encoding or "gbk"
        return response.text

    def _prewarm_ths_session(self) -> None:
        try:
            response = self.requester(THS_REFERER, timeout=self.timeout, headers=_ths_headers())
            response.raise_for_status()
        except Exception:
            return

    def _parse_fupan(self, soup: BeautifulSoup) -> MarketBriefingResponse:
        summary = _node_text(soup.select_one("#fpzj"))
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
            body = _readable_content_from_node(content_without_tables)
            if body or tables or links:
                sections.append(MarketBriefingSection(title=title or "复盘板块", content=body or None, links=links, tables=tables))
        expanded_sections, diagnostics = self._expand_article_links(sections[:8], THS_FUPAN_URL)
        return MarketBriefingResponse(
            kind="fupan",
            updated_at=datetime.now(timezone.utc),
            source="ths-fupan",
            source_url=THS_FUPAN_URL,
            summary=summary or "同花顺复盘已读取，但页面暂未提供摘要。",
            sections=expanded_sections,
            diagnostics=diagnostics,
        )

    def _parse_zaopan(self, soup: BeautifulSoup) -> MarketBriefingResponse:
        summary = _node_text(soup.select_one(".yestoday"))
        sections: list[MarketBriefingSection] = []
        main = soup.select_one(".content-main-fl")
        if main:
            main_text_root = _remove_non_textual_nodes(main)
            tables = [
                table
                for table in (_table_from_node(node, title="早盘表格") for node in main.select("table")[:3])
                if table is not None
            ]
            content = _readable_content_from_node(main_text_root)
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
            content = _readable_content_from_node(content_root)
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
        expanded_sections, diagnostics = self._expand_article_links(sections[:8], THS_ZAOPAN_URL)
        return MarketBriefingResponse(
            kind="zaopan",
            updated_at=datetime.now(timezone.utc),
            source="ths-zaopan",
            source_url=THS_ZAOPAN_URL,
            summary=summary or (sections[0].content if sections and sections[0].content else fallback_summary),
            sections=expanded_sections,
            diagnostics=diagnostics,
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
