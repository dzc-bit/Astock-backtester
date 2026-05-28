from __future__ import annotations

import time

from astock_backtester.data.risk import RiskAlertProvider
from astock_backtester.data.warehouse import Warehouse


class FakeResponse:
    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return {"data": {"diff": [{"f12": "000001", "f14": "*ST示例"}]}}


class FakeTextResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.content = text.encode("gbk", errors="ignore")
        self.encoding = "gbk"

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return {}


def test_risk_provider_uses_short_external_timeout(tmp_path):
    seen_timeout = None

    def requester(*args, **kwargs):
        nonlocal seen_timeout
        seen_timeout = kwargs.get("timeout")
        return FakeResponse()

    provider = RiskAlertProvider(Warehouse(tmp_path), requester=requester, include_packaged_watchlist=False)
    response = provider.current_alerts()

    assert seen_timeout is not None
    assert seen_timeout <= 2
    assert response.items[0].symbol == "000001"


def test_risk_provider_uses_adata_all_codes_for_full_market_st_alerts(tmp_path):
    def requester(*args, **kwargs):
        raise RuntimeError("external source unavailable")

    def adata_loader():
        import pandas as pd

        return pd.DataFrame(
            [
                {"stock_code": "000004", "short_name": "*ST国华"},
                {"stock_code": "600001", "short_name": "退市示例"},
                {"stock_code": "300001", "short_name": "普通股票"},
            ]
        )

    provider = RiskAlertProvider(
        Warehouse(tmp_path),
        requester=requester,
        adata_loader=adata_loader,
        include_packaged_watchlist=False,
    )

    response = provider.current_alerts()

    assert response.source == "adata"
    assert [item.symbol for item in response.items] == ["000004", "600001"]
    assert response.items[0].name == "*ST国华"
    assert response.items[1].risk_type == "退市风险"


def test_risk_provider_returns_full_market_risk_list_without_truncation(tmp_path):
    def requester(*args, **kwargs):
        raise RuntimeError("external source unavailable")

    def adata_loader():
        import pandas as pd

        return pd.DataFrame(
            [
                {"stock_code": f"{index:06d}", "short_name": f"*ST风险{index}"}
                for index in range(1, 121)
            ]
        )

    provider = RiskAlertProvider(
        Warehouse(tmp_path),
        requester=requester,
        adata_loader=adata_loader,
        include_packaged_watchlist=False,
    )

    response = provider.current_alerts()

    assert len(response.items) == 120
    assert response.items[0].symbol == "000001"
    assert response.items[-1].symbol == "000120"


def test_risk_provider_does_not_block_on_slow_adata_when_eastmoney_returns(tmp_path):
    def requester(*args, **kwargs):
        return FakeResponse()

    def slow_adata_loader():
        time.sleep(2)
        raise TimeoutError("adata timeout")

    provider = RiskAlertProvider(
        Warehouse(tmp_path),
        timeout=0.1,
        requester=requester,
        adata_loader=slow_adata_loader,
        include_packaged_watchlist=False,
    )

    started_at = time.perf_counter()
    response = provider.current_alerts()

    assert time.perf_counter() - started_at < 1.0
    assert [item.symbol for item in response.items] == ["000001"]


def test_risk_provider_uses_sina_names_for_local_full_market_symbols(tmp_path):
    warehouse = Warehouse(tmp_path)
    (tmp_path / "symbols.full.csv").write_text("symbol\n000001\n000004\n600001\n", encoding="utf-8")

    def requester(url, *args, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeTextResponse(
                'var hq_str_s_sz000001="平安银行,10.76,-0.03,-0.28,839727,90571";\n'
                'var hq_str_s_sz000004="*ST国华,0.00,0.00,0.00,0,0";\n'
                'var hq_str_s_sh600001="退市示例,0.00,0.00,0.00,0,0";\n'
            )
        raise RuntimeError("external source unavailable")

    provider = RiskAlertProvider(
        warehouse,
        timeout=0.1,
        requester=requester,
        adata_loader=lambda: (_ for _ in ()).throw(RuntimeError("adata unavailable")),
        include_packaged_watchlist=False,
    )

    response = provider.current_alerts()

    assert response.source == "sina"
    assert [item.symbol for item in response.items] == ["000004", "600001"]
    assert response.items[0].name == "*ST国华"
    assert response.items[1].risk_type == "退市风险"


def test_risk_provider_prefers_local_potential_risk_watchlist_with_detailed_reasons(tmp_path):
    warehouse = Warehouse(tmp_path)
    (tmp_path / "potential_risk_watchlist.csv").write_text(
        "name,symbol,risk_type,detail\n"
        "黑芝麻,000716,ST预警,信息披露违规\n"
        "康芝药业,300086,ST预警,年报审计风险\n",
        encoding="utf-8",
    )

    def requester(url, *args, **kwargs):
        if "hq.sinajs.cn" in url:
            return FakeTextResponse('var hq_str_s_sz000716="黑芝麻,5.00,0.01,0.20,100,500";\n')
        raise RuntimeError("external source unavailable")

    provider = RiskAlertProvider(
        warehouse,
        timeout=0.1,
        requester=requester,
        adata_loader=lambda: (_ for _ in ()).throw(RuntimeError("adata unavailable")),
    )

    response = provider.current_alerts()

    assert response.source == "local-watchlist"
    assert [item.symbol for item in response.items] == ["000716", "300086"]
    assert response.items[0].name == "黑芝麻"
    assert response.items[0].risk_type == "ST预警"
    assert response.items[0].severity == "medium"
    assert "信息披露违规" in response.items[0].reason
    assert "潜在 ST 风险观察名单" in response.items[0].reason
    assert any("实时扫描未发现新增已 ST" in message for message in response.diagnostics)
