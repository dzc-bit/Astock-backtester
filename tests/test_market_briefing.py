from __future__ import annotations

from astock_backtester.data.briefing import MarketBriefingProvider


class FakeHtmlResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("gbk", errors="ignore")
        self.encoding = "gbk"
        self.apparent_encoding = "gbk"

    def raise_for_status(self) -> None:
        return


def test_market_briefing_provider_parses_ths_fupan_sections_tables_and_links():
    html = """
    <html><body>
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

    provider = MarketBriefingProvider(requester=lambda *args, **kwargs: FakeHtmlResponse(html))

    response = provider.latest_fupan()

    assert response.kind == "fupan"
    assert response.source == "ths-fupan"
    assert response.summary == "A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。"
    assert [section.title for section in response.sections] == ["指数/概念分析", "同花顺解盘"]
    assert response.sections[0].tables[0].columns == ["个股", "涨幅"]
    assert response.sections[0].tables[0].rows == [{"个股": "软通动力", "涨幅": "20.00%"}]
    assert response.sections[1].links[0].title == "A股收评：科技股回调"


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


def test_market_briefing_provider_returns_diagnostics_when_ths_unavailable():
    def requester(*args, **kwargs):
        raise RuntimeError("network closed")

    response = MarketBriefingProvider(requester=requester).latest_fupan()

    assert response.kind == "fupan"
    assert response.source == "fallback"
    assert response.summary == "同花顺复盘暂不可用，已保留复盘评价入口。"
    assert response.sections == []
    assert response.diagnostics == ["同花顺复盘读取失败：network closed"]
