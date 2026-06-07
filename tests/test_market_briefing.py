from __future__ import annotations

from astock_backtester.data.briefing import MarketBriefingProvider, THS_FUPAN_URL, THS_REFERER


class FakeHtmlResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("gbk", errors="ignore")
        self.encoding = "gbk"
        self.apparent_encoding = "gbk"

    def raise_for_status(self) -> None:
        return


def test_market_briefing_provider_keeps_full_ths_fupan_summary_and_section_body():
    summary_sentinel = "复盘摘要尾部哨兵"
    body_sentinel = "复盘正文尾部哨兵"
    long_summary = ("复盘长摘要" * 70) + summary_sentinel
    long_body = ("复盘长章节正文" * 70) + body_sentinel
    html = f"""
    <html><body>
      <div id="fpzj">{long_summary}</div>
      <div class="fp_item_hd"><h2>长章节</h2></div>
      <div class="fp_item_cnt"><p>{long_body}</p></div>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1>A股收评：科技股回调</h1>
      <article><p>A股三大指数集体下跌后，科技股尾盘仍有分化。</p></article>
    </body></html>
    """

    def requester(url: str, **kwargs):
        if url.endswith("test.shtml"):
            return FakeHtmlResponse(detail_html)
        return FakeHtmlResponse(html)

    provider = MarketBriefingProvider(requester=requester)

    response = provider.latest_fupan()

    assert response.summary == long_summary
    assert summary_sentinel in response.summary
    assert not response.summary.endswith("...")
    assert response.sections[0].content == long_body
    assert body_sentinel in (response.sections[0].content or "")
    assert not (response.sections[0].content or "").endswith("...")


def test_market_briefing_provider_keeps_full_ths_zaopan_summary_main_and_sidebar_body():
    summary_sentinel = "早盘摘要尾部哨兵"
    main_sentinel = "早盘主栏尾部哨兵"
    sidebar_sentinel = "早盘侧栏尾部哨兵"
    long_summary = ("早盘长摘要" * 60) + summary_sentinel
    long_main_body = ("早盘主栏正文" * 90) + main_sentinel
    long_sidebar_body = ("早盘侧栏正文" * 60) + sidebar_sentinel
    html = f"""
    <html><body>
      <div class="yestoday">{long_summary}</div>
      <div class="content-main-fl"><p>{long_main_body}</p></div>
      <div class="content-main-fr">
        <div class="table-part">
          <h2>侧栏观点</h2>
          <p>{long_sidebar_body}</p>
        </div>
      </div>
    </body></html>
    """

    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))

    response = provider.latest_zaopan()

    assert response.summary == long_summary
    assert summary_sentinel in response.summary
    assert not response.summary.endswith("...")
    assert response.sections[0].content == long_main_body
    assert main_sentinel in (response.sections[0].content or "")
    assert not (response.sections[0].content or "").endswith("...")
    assert response.sections[1].content == long_sidebar_body
    assert sidebar_sentinel in (response.sections[1].content or "")
    assert not (response.sections[1].content or "").endswith("...")


def test_market_briefing_provider_keeps_full_ths_zaopan_summary_when_derived_from_main_body():
    main_sentinel = "早盘派生摘要尾部哨兵"
    long_main_body = ("早盘无摘要主栏正文" * 80) + main_sentinel
    html = f"""
    <html><body>
      <div class="content-main-fl"><p>{long_main_body}</p></div>
    </body></html>
    """

    detail_html = """
    <html><body>
      <h1>A股收评：科技股回调</h1>
      <article><p>A股三大指数集体下跌后，科技股尾盘仍有分化。</p></article>
    </body></html>
    """

    def requester(url: str, **kwargs):
        if url.endswith("test.shtml"):
            return FakeHtmlResponse(detail_html)
        return FakeHtmlResponse(html)

    provider = MarketBriefingProvider(requester=requester)

    response = provider.latest_zaopan()

    assert response.summary == long_main_body
    assert main_sentinel in response.summary
    assert not response.summary.endswith("...")


def test_market_briefing_provider_prewarms_and_retries_when_ths_returns_empty_body():
    valid_html = """
    <html><body>
      <div id="fpzj">重试后拿到复盘摘要</div>
      <div class="fp_item_hd"><h2>重试章节</h2></div>
      <div class="fp_item_cnt"><p>重试后拿到复盘正文</p></div>
    </body></html>
    """
    calls: list[tuple[str, dict]] = []

    def requester(url: str, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return FakeHtmlResponse("")
        if url == THS_REFERER:
            return FakeHtmlResponse("<html><body>同花顺入口预热</body></html>")
        return FakeHtmlResponse(valid_html)

    provider = MarketBriefingProvider(requester=requester)

    response = provider.latest_fupan()

    assert response.source == "ths-fupan"
    assert response.summary == "重试后拿到复盘摘要"
    assert [url for url, _ in calls] == [THS_FUPAN_URL, THS_REFERER, THS_FUPAN_URL]
    request_headers = calls[0][1]["headers"]
    assert request_headers["Referer"] == THS_REFERER
    assert "Windows NT" in request_headers["User-Agent"]
    assert "zh-CN" in request_headers["Accept-Language"]


def test_market_briefing_provider_parses_ths_fupan_sections_tables_and_links():
    html = """
    <html><body data-case="fupan-table-link-expansion">
      <div id="fpzj">A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。</div>
      <div class="fp_item_hd"><em>01</em><h2>指数/概念分析</h2></div>
      <div class="fp_item_cnt">
        <p>ERP概念 +4.78%，财税数字化 +4.46%。</p>
        <table>
          <tr><th>个股</th><th>涨幅</th></tr>
          <tr><td>软通动力</td><td>20.00%</td></tr>
        </table>
      </div>
      <div class="fp_item_hd"><em>02</em><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt">
        <ul><li><a href="http://stock.10jqka.com.cn/test.shtml" title="A股收评：科技股回调">A股收评</a></li></ul>
      </div>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1>A股收评：科技股回调</h1>
      <article><p>A股三大指数集体下跌后，科技股尾盘仍有分化。</p></article>
    </body></html>
    """

    def requester(url: str, **kwargs):
        if url.endswith("test.shtml"):
            return FakeHtmlResponse(detail_html)
        return FakeHtmlResponse(html)

    provider = MarketBriefingProvider(requester=requester)

    response = provider.latest_fupan()

    assert response.kind == "fupan"
    assert response.source == "ths-fupan"
    assert response.summary == "A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。"
    assert [section.title for section in response.sections] == ["指数/概念分析", "同花顺解盘", "全文：A股收评：科技股回调"]
    assert response.sections[0].tables[0].columns == ["个股", "涨幅"]
    assert response.sections[0].tables[0].rows == [{"个股": "软通动力", "涨幅": "20.00%"}]
    assert response.sections[1].links[0].title == "A股收评：科技股回调"
    assert "A股三大指数集体下跌" in (response.sections[2].content or "")


def test_market_briefing_provider_expands_article_links_into_full_text_sections():
    index_html = """
    <html><body>
      <div id="fpzj">A股复盘摘要</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt">
        <ul>
          <li><a href="http://stock.10jqka.com.cn/20260605/c677247169.shtml" title="A股收评：机器人走强">A股收评</a></li>
          <li><a href="http://q.10jqka.com.cn/gn/detail/code/309000/">减速器</a></li>
        </ul>
      </div>
    </body></html>
    """
    detail_html = """
    <html><body>
      <h1>A股收评：机器人走强</h1>
      <article>
        <p>今日机器人板块午后持续冲高，减速器方向多只个股涨停。</p>
        <p>尾盘资金仍围绕题材龙头博弈，明日重点观察成交额能否继续放大。</p>
      </article>
    </body></html>
    """
    calls: list[str] = []

    def requester(url: str, **kwargs):
        calls.append(url)
        if url.endswith("c677247169.shtml"):
            return FakeHtmlResponse(detail_html)
        return FakeHtmlResponse(index_html)

    response = MarketBriefingProvider(requester=requester).latest_fupan()

    assert calls == [THS_FUPAN_URL, "http://stock.10jqka.com.cn/20260605/c677247169.shtml"]
    assert [section.title for section in response.sections] == ["同花顺解盘", "全文：A股收评：机器人走强"]
    assert "今日机器人板块午后持续冲高" in (response.sections[1].content or "")
    assert "明日重点观察成交额能否继续放大" in (response.sections[1].content or "")
    assert response.sections[1].links[0].url == "http://stock.10jqka.com.cn/20260605/c677247169.shtml"


def test_market_briefing_provider_reports_article_expansion_failures_in_diagnostics():
    index_html = """
    <html><body>
      <div id="fpzj">A股复盘摘要</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt">
        <a href="http://stock.10jqka.com.cn/20260605/c677247169.shtml" title="A股收评：机器人走强">A股收评</a>
      </div>
    </body></html>
    """

    def requester(url: str, **kwargs):
        if url.endswith("c677247169.shtml"):
            raise RuntimeError("anti crawler")
        return FakeHtmlResponse(index_html)

    response = MarketBriefingProvider(requester=requester).latest_fupan()

    assert [section.title for section in response.sections] == ["同花顺解盘"]
    assert response.diagnostics == ["同花顺文章详情抓取失败：A股收评：机器人走强 - anti crawler"]


def test_market_briefing_provider_parses_ths_zaopan_summary_and_tables():
    html = """
    <html><body>
      <div class="yestoday">昨日收盘指数 上证指数：4068.57 -0.734%</div>
      <div class="content-main-fl">
        <p>【昨日国内行情回顾】A股三大指数集体下跌，白酒、煤炭涨幅居前。</p>
        <table>
          <tr><th>公司名称</th><th>事项</th></tr>
          <tr><td>利通电子</td><td>股票交易严重异常波动</td></tr>
        </table>
      </div>
      <div class="content-main-fr">
        <div class="table-part">
          <h2>今日停复牌</h2>
          <table>
            <tr><th>简称</th><th>事项</th></tr>
            <tr><td>*ST天择</td><td>停牌</td></tr>
          </table>
        </div>
      </div>
    </body></html>
    """

    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))

    response = provider.latest_zaopan()

    assert response.kind == "zaopan"
    assert response.source == "ths-zaopan"
    assert response.summary.startswith("昨日收盘指数")
    assert [section.title for section in response.sections] == ["早盘要点", "今日停复牌"]
    assert response.sections[0].tables[0].rows[0]["公司名称"] == "利通电子"
    assert response.sections[1].tables[0].rows[0]["简称"] == "*ST天择"


def test_market_briefing_provider_labels_stock_gain_price_tables_without_misusing_theme_columns():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：热门个股活跃。</div>
      <div class="fp_item_hd"><h2>热门个股</h2></div>
      <div class="fp_item_cnt">
        <table>
          <tr><td>软通动力</td><td>20.00%</td><td>58.63</td></tr>
          <tr><td>新易盛</td><td>13.24%</td><td>118.20</td></tr>
        </table>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    table = response.sections[0].tables[0]
    assert table.columns == ["个股", "涨幅", "现价"]
    assert table.rows[0] == {"个股": "软通动力", "涨幅": "20.00%", "现价": "58.63"}
    assert "异动原因" not in table.columns
    assert "影响" not in table.columns


def test_market_briefing_provider_preserves_index_page_paragraphs():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：题材轮动。</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt">
        <p>机器人板块午后持续走强。</p>
        <p>明日重点观察成交额能否继续放大。</p>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    assert response.sections[0].content == "机器人板块午后持续走强。\n\n明日重点观察成交额能否继续放大。"


def test_market_briefing_provider_removes_sidebar_title_from_zaopan_content():
    html = """
    <html><body>
      <div class="yestoday">昨日收盘指数 上证指数：4068.57 -0.734%</div>
      <div class="content-main-fr">
        <div class="table-part">
          <h2>机构观点</h2>
          <p>机构认为低空经济仍需观察成交承接。</p>
        </div>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_zaopan()

    assert response.sections[0].title == "机构观点"
    assert response.sections[0].content == "机构认为低空经济仍需观察成交承接。"
    assert not response.sections[0].content.startswith("机构观点")


def test_market_briefing_provider_removes_leading_rank_from_stock_gain_price_table():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：热门个股活跃。</div>
      <div class="fp_item_hd"><h2>热门个股涨幅榜</h2></div>
      <div class="fp_item_cnt">
        <table>
          <tr><td>1</td><td>软通动力</td><td>20.00%</td><td>58.63</td></tr>
          <tr><td>2</td><td>新易盛</td><td>13.24%</td><td>118.20</td></tr>
        </table>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    table = response.sections[0].tables[0]
    assert table.columns == ["个股", "涨幅", "现价"]
    assert table.rows[0] == {"个股": "软通动力", "涨幅": "20.00%", "现价": "58.63"}
    assert "数值一" not in table.columns


def test_market_briefing_provider_removes_leading_rank_from_three_column_stock_gain_table():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：热门个股活跃。</div>
      <div class="fp_item_hd"><h2>热门个股涨幅榜</h2></div>
      <div class="fp_item_cnt">
        <table>
          <tr><td>1</td><td>软通动力</td><td>20.00%</td></tr>
          <tr><td>2</td><td>新易盛</td><td>13.24%</td></tr>
        </table>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    table = response.sections[0].tables[0]
    assert table.columns == ["个股", "涨幅"]
    assert table.rows[0] == {"个股": "软通动力", "涨幅": "20.00%"}


def test_market_briefing_provider_keeps_inline_strong_body_text():
    html = """
    <html><body>
      <div class="yestoday">昨日收盘指数 上证指数：4068.57 -0.734%</div>
      <div class="content-main-fr">
        <div class="table-part">
          <h2>机构观点</h2>
          <p>资金关注<strong>机器人主线</strong>的成交承接。</p>
        </div>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_zaopan()

    assert "机器人主线" in (response.sections[0].content or "")
    assert response.sections[0].content == "资金关注 机器人主线 的成交承接。"


def test_market_briefing_provider_filters_all_numeric_tables():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：指数小幅反弹。</div>
      <div class="fp_item_hd"><h2>神秘数字</h2></div>
      <div class="fp_item_cnt">
        <table>
          <tr><td>1293.69</td><td>+14.46</td><td>+1.13%</td><td>363.54亿</td></tr>
          <tr><td>2026-06-05 15:00:00</td><td>2026-06-05 15:00:00</td><td>1</td><td>2</td></tr>
        </table>
        <p>机器人板块午后持续走强，资金围绕题材龙头博弈。</p>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    assert response.sections[0].tables == []
    assert response.sections[0].content == "机器人板块午后持续走强，资金围绕题材龙头博弈。"


def test_market_briefing_provider_filters_numeric_soup_and_repeated_timestamps_from_section_content():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：指数小幅反弹。</div>
      <div class="fp_item_hd"><h2>指数表现</h2></div>
      <div class="fp_item_cnt">
        <p>权重 1293.69 +14.46 +1.13% 363.54亿 2026-06-05 15:00:00 2026-06-05 15:00:00 2026-06-05 15:00:00</p>
        <p>2026-06-05 15:00:00 2026-06-05 15:00:00 2026-06-05 15:00:00</p>
        <p>机器人板块午后持续走强，资金围绕题材龙头博弈。</p>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    assert response.sections[0].content == "机器人板块午后持续走强，资金围绕题材龙头博弈。"


def test_market_briefing_provider_filters_cn_label_numeric_soup_and_percent_symbols():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：指数小幅反弹。</div>
      <div class="fp_item_hd"><h2>指数表现</h2></div>
      <div class="fp_item_cnt">
        <p>同比指数盈利 2700 0 股票数（只） 同比指数盈利% 计算方式 1293.69 +14.46 +1.13% 363.54亿</p>
        <p>%</p>
        <p>% %</p>
        <p>机器人板块午后持续走强，资金围绕题材龙头博弈。</p>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    assert response.sections[0].content == "机器人板块午后持续走强，资金围绕题材龙头博弈。"
    assert "同比指数盈利" not in (response.sections[0].content or "")
    assert "% %" not in (response.sections[0].content or "")


def test_market_briefing_provider_filters_div_numeric_soup_and_keeps_readable_sentences():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：指数小幅反弹。</div>
      <div class="fp_item_hd"><h2>行业表现</h2></div>
      <div class="fp_item_cnt">
        <div>
          半导体 1293.69 +14.46 +1.13% 363.54亿 2026-06-05 15:00:00
          机器人 1102.18 +22.40 +2.07% 251.11亿 2026-06-05 15:00:00
          % %
        </div>
        <div>机器人板块午后持续走强，资金围绕题材龙头博弈。</div>
        <span>算力方向尾盘承接改善，仍需观察成交额能否延续。</span>
      </div>
    </body></html>
    """

    response = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html)).latest_fupan()

    content = response.sections[0].content or ""
    assert "1293.69" not in content
    assert "2026-06-05" not in content
    assert "% %" not in content
    assert "机器人板块午后持续走强，资金围绕题材龙头博弈。" in content
    assert "算力方向尾盘承接改善，仍需观察成交额能否延续。" in content


def test_market_briefing_provider_uses_market_fallback_when_ths_page_has_no_sections():
    html = "<html><body><div id='fpzj'></div></body></html>"

    def fallback_provider():
        return [
            {
                "title": "公开行情回顾",
                "content": "上证指数小幅回升，机器人与算力方向保持活跃。",
                "links": [{"title": "东方财富行情", "url": "https://quote.eastmoney.com/center/gridlist.html"}],
                "tables": [
                    {
                        "title": "参考指数",
                        "columns": ["名称", "最新值", "涨跌额", "涨跌幅"],
                        "rows": [{"名称": "上证指数", "最新值": "3120.00", "涨跌额": "12.50", "涨跌幅": "0.40%"}],
                    }
                ],
            }
        ]

    response = MarketBriefingProvider(
        requester=lambda *args, **kwargs: FakeHtmlResponse(html),
        fallback_provider=fallback_provider,
    ).latest_fupan()

    assert response.source == "ths-fupan+market-fallback"
    assert response.summary == "上证指数小幅回升，机器人与算力方向保持活跃。"
    assert response.sections[0].title == "公开行情回顾"
    assert response.sections[0].tables[0].columns == ["名称", "最新值", "涨跌额", "涨跌幅"]
    assert any("同花顺复盘页未解析到有效章节" in item for item in response.diagnostics)


def test_market_briefing_provider_does_not_mix_user_mode_candidates_from_legacy_latest_bars_hook():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：机器人和算力活跃。</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt"><p>机器人板块午后持续走强，算力方向有承接。</p></div>
    </body></html>
    """
    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))
    provider.latest_bars_provider = lambda: [{"symbol": "300001", "name": "机器人A", "close": 10.8}]

    response = provider.latest_fupan()

    assert [section.title for section in response.sections] == ["同花顺解盘"]
    assert response.sections[0].content == "机器人板块午后持续走强，算力方向有承接。"
    assert "当日 user 模式匹配个股" not in str(response.model_dump(mode="json"))


def test_market_briefing_provider_does_not_mix_user_mode_candidates_from_legacy_realtime_hook():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：机器人和算力活跃。</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt"><p>机器人板块午后持续走强，算力方向有承接。</p></div>
    </body></html>
    """

    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))
    provider.realtime_spot_provider = lambda: [
        {"代码": "300001", "名称": "机器人A", "现价": "10.88", "涨跌额": "0.88", "涨跌幅": "8.80%"},
        {"代码": "600002", "名称": "低量B", "现价": "20.10", "涨跌额": "0.10", "涨跌幅": "0.50%"},
    ]

    response = provider.latest_fupan()

    assert [section.title for section in response.sections] == ["同花顺解盘"]
    assert "当日 user 模式匹配个股" not in str(response.model_dump(mode="json"))


def test_market_briefing_provider_does_not_mix_akshare_realtime_spot_candidates_from_legacy_hook():
    html = """
    <html><body>
      <div id="fpzj">复盘摘要：机器人和算力活跃。</div>
      <div class="fp_item_hd"><h2>同花顺解盘</h2></div>
      <div class="fp_item_cnt"><p>机器人板块午后持续走强，算力方向有承接。</p></div>
    </body></html>
    """

    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))
    provider.realtime_spot_provider = lambda: [
        {"代码": "300001", "名称": "机器人A", "最新价": 10.88, "涨跌幅": 8.8, "换手率": 4.2, "量比": 1.8, "流通市值": 85.0},
        {"代码": "600002", "名称": "低涨幅B", "最新价": 20.10, "涨跌幅": 0.5, "换手率": 2.0, "量比": 1.4, "流通市值": 120.0},
    ]

    response = provider.latest_fupan()

    assert [section.title for section in response.sections] == ["同花顺解盘"]
    assert "当日 user 模式匹配个股" not in str(response.model_dump(mode="json"))


def test_market_briefing_provider_returns_diagnostics_when_ths_unavailable():
    def requester(*args, **kwargs):
        raise RuntimeError("network closed")

    response = MarketBriefingProvider(requester=requester).latest_fupan()

    assert response.kind == "fupan"
    assert response.source == "fallback"
    assert response.summary == "同花顺复盘暂不可用，已保留复盘评价入口。"
    assert response.sections == []
    assert response.diagnostics == ["同花顺复盘读取失败：network closed"]
