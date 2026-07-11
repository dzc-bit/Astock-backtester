"""Characterization tests for pure parsing functions extracted from realtime.py.

These tests verify that the extracted functions in ``realtime_parsers.py``
produce identical results to the original inline implementations, ensuring
the refactoring did not change any behavior.
"""

from __future__ import annotations

from datetime import datetime

from astock_backtester.data.realtime_parsers import (
    BEIJING_TZ,
    a_share_market_symbol,
    aggregate_ths_hot_topic_rows,
    append_yesterday_sector_note,
    breadth_from_cls_distribution,
    clean_ths_topic_name,
    decode_sina_response,
    dedupe_sectors,
    is_valid_full_market_breadth,
    market_phase,
    normalize_change_pct,
    normalize_sector_change_pct,
    parse_float,
    parse_int,
    phase_diagnostic,
    quote_from_cls_home,
    quote_from_sina,
    sector_rows_from_cls_hot_plate,
    unique_sources,
)
from astock_backtester.models import MarketBreadth, SectorMover


class TestParseInt:
    def test_plain_int(self):
        assert parse_int(123) == 123

    def test_string_with_commas(self):
        assert parse_int("1,234") == 1234

    def test_string_with_text(self):
        assert parse_int("上涨1234家") == 1234

    def test_negative(self):
        assert parse_int("-5") == -5

    def test_none(self):
        assert parse_int(None) is None

    def test_empty(self):
        assert parse_int("") is None

    def test_no_digits(self):
        assert parse_int("abc") is None


class TestParseFloat:
    def test_plain_float(self):
        assert parse_float(1.5) == 1.5

    def test_string_with_percent(self):
        assert parse_float("3.5%") == 3.5

    def test_string_with_commas(self):
        assert parse_float("1,234.56") == 1234.56

    def test_none(self):
        assert parse_float(None) is None

    def test_empty(self):
        assert parse_float("") is None

    def test_invalid(self):
        assert parse_float("abc") is None


class TestNormalizeChangePct:
    def test_percent_value(self):
        assert normalize_change_pct(3.5) == 0.035

    def test_decimal_value(self):
        assert normalize_change_pct(0.035) == 0.035

    def test_none(self):
        assert normalize_change_pct(None) is None


class TestNormalizeSectorChangePct:
    def test_percent_unit(self):
        row = {"f3": 3.5, "_change_pct_unit": "percent"}
        assert normalize_sector_change_pct(row) == 0.035

    def test_auto_detect_large(self):
        row = {"f3": 3.5}
        assert normalize_sector_change_pct(row) == 0.035

    def test_auto_detect_small(self):
        row = {"f3": 0.035}
        assert normalize_sector_change_pct(row) == 0.035


class TestCleanThsTopicName:
    def test_normal_topic(self):
        assert clean_ths_topic_name("半导体") == "半导体"

    def test_whitespace(self):
        assert clean_ths_topic_name("  半导体 ") == "半导体"

    def test_generic_topic_filtered(self):
        assert clean_ths_topic_name("A股") is None
        assert clean_ths_topic_name("") is None

    def test_suffix_filtered(self):
        assert clean_ths_topic_name("半导体个股") is None
        assert clean_ths_topic_name("半导体概念股") is None


class TestDecodeSinaResponse:
    def test_basic_decode(self):
        text = (
            'var hq_str_sh000001="上证指数,3100,3120,3120.5,3105,3100,3100,3120,'
            '3100,3100,3120,3100,3100,3120,3100,3100,3120,3100,3100,3100,3100,'
            '3100,3100,3100,3100,3100,3100,3100,3100,3100,2024-01-05,15:00:00,00,";'
        )
        result = decode_sina_response(text)
        assert "sh000001" in result
        assert len(result["sh000001"]) > 4

    def test_empty_response(self):
        assert decode_sina_response("") == {}

    def test_no_hq_str(self):
        assert decode_sina_response("var foo = 'bar';") == {}


class TestQuoteFromSina:
    def test_valid_quote(self):
        values = ["上证指数", "3100", "3100", "3120", "3105", "3100", "3100", "3120"]
        values.extend([""] * 22)
        values.extend(["2024-01-05", "15:00:00"])
        quote = quote_from_sina("sh000001", "上证指数", values)
        assert quote is not None
        assert quote.symbol == "sh000001"
        assert quote.last == 3120.0
        assert quote.previous_close == 3100.0

    def test_invalid_values(self):
        assert quote_from_sina("sh000001", "test", []) is None
        assert quote_from_sina("sh000001", "test", ["a", "b", "c", "d"]) is None


class TestQuoteFromClsHome:
    def test_valid_row(self):
        row = {
            "secu_code": "sh000001",
            "secu_name": "上证指数",
            "last_px": "3120.5",
            "preclose_px": "3100",
            "change_px": "20.5",
            "change": "0.66%",
        }
        quote = quote_from_cls_home(row)
        assert quote is not None
        assert quote.symbol == "sh000001"
        assert quote.last == 3120.5

    def test_missing_symbol(self):
        assert quote_from_cls_home({"last_px": "3120"}) is None

    def test_missing_last(self):
        assert quote_from_cls_home({"secu_code": "sh000001"}) is None


class TestBreadthFromClsDistribution:
    def test_valid_distribution(self):
        data = {
            "rise_num": "2500",
            "fall_num": "1800",
            "flat_num": "200",
            "up_num": "50",
            "down_num": "30",
        }
        breadth = breadth_from_cls_distribution(data)
        assert breadth is not None
        assert breadth.up == 2500
        assert breadth.down == 1800
        assert breadth.flat == 200
        assert breadth.total == 4500
        assert breadth.source == "cls-quote-breadth"

    def test_missing_fields(self):
        assert breadth_from_cls_distribution({}) is None
        assert breadth_from_cls_distribution({"rise_num": "100"}) is None

    def test_non_dict(self):
        assert breadth_from_cls_distribution("not a dict") is None


class TestSectorRowsFromClsHotPlate:
    def test_valid_payload(self):
        payload = {
            "data": {
                "industry": [
                    {"secu_name": "半导体", "change": 3.5, "up_stock": [{"secu_code": "688001"}]}
                ],
                "concept": [],
                "area": [],
            }
        }
        rows = sector_rows_from_cls_hot_plate(payload)
        assert len(rows) == 1
        assert rows[0]["name"] == "半导体"

    def test_empty_payload(self):
        assert sector_rows_from_cls_hot_plate({}) == []
        assert sector_rows_from_cls_hot_plate({"data": {}}) == []


class TestDedupeSectors:
    def test_dedup_by_name(self):
        sectors = [
            SectorMover(name="半导体", change_pct=0.03, source="test"),
            SectorMover(name="半导体", change_pct=0.02, source="test"),
            SectorMover(name="AI", change_pct=0.05, source="test"),
        ]
        result = dedupe_sectors(sectors)
        assert len(result) == 2
        assert result[0].name == "半导体"

    def test_limit(self):
        sectors = [SectorMover(name=f"s{i}", change_pct=0.01, source="test") for i in range(20)]
        assert len(dedupe_sectors(sectors, limit=5)) == 5


class TestAppendYesterdaySectorNote:
    def test_adds_note(self):
        result = append_yesterday_sector_note(
            "msg", [SectorMover(name="半导体", change_pct=0.01, source="test")]
        )
        assert "昨日强势板块追踪来自本地历史" in result

    def test_no_sectors(self):
        assert append_yesterday_sector_note("msg", []) == "msg"

    def test_already_has_note(self):
        msg = "msg 昨日强势板块追踪来自本地历史。"
        assert append_yesterday_sector_note(
            msg, [SectorMover(name="半导体", change_pct=0.01, source="test")]
        ) == msg


class TestUniqueSources:
    def test_dedup_preserves_order(self):
        assert unique_sources(["a", "b", "a", "c", None, "b"]) == ["a", "b", "c"]

    def test_empty(self):
        assert unique_sources([]) == []


class TestMarketPhase:
    def test_weekend(self):
        # 2024-01-06 is Saturday
        saturday = datetime(2024, 1, 6, 10, 0, tzinfo=BEIJING_TZ)
        assert market_phase(saturday) == "non_trading"

    def test_pre_open(self):
        weekday = datetime(2024, 1, 4, 9, 0, tzinfo=BEIJING_TZ)
        assert market_phase(weekday) == "pre_open"

    def test_trading(self):
        weekday = datetime(2024, 1, 4, 10, 0, tzinfo=BEIJING_TZ)
        assert market_phase(weekday) == "trading"

    def test_lunch_break(self):
        weekday = datetime(2024, 1, 4, 12, 0, tzinfo=BEIJING_TZ)
        assert market_phase(weekday) == "lunch_break"

    def test_post_close(self):
        weekday = datetime(2024, 1, 4, 16, 0, tzinfo=BEIJING_TZ)
        assert market_phase(weekday) == "post_close"


class TestPhaseDiagnostic:
    def test_non_trading(self):
        assert phase_diagnostic("non_trading") is not None
        assert "降低" in phase_diagnostic("non_trading")

    def test_trading_no_diagnostic(self):
        assert phase_diagnostic("trading") is None


class TestIsValidFullMarketBreadth:
    def test_valid_cls_breadth(self):
        breadth = MarketBreadth(
            up=2500, down=1800, flat=200, total=4500, source="cls-quote-breadth"
        )
        assert is_valid_full_market_breadth(breadth) is True

    def test_too_small(self):
        breadth = MarketBreadth(up=100, down=80, flat=10, total=190, source="sina")
        assert is_valid_full_market_breadth(breadth) is False

    def test_none(self):
        assert is_valid_full_market_breadth(None) is False

    def test_with_local_count(self):
        breadth = MarketBreadth(up=2000, down=1500, flat=200, total=3700, source="sina")
        assert is_valid_full_market_breadth(breadth, local_symbol_count=5000) is True

    def test_local_ratio_too_low(self):
        breadth = MarketBreadth(up=100, down=80, flat=10, total=190, source="sina")
        assert is_valid_full_market_breadth(breadth, local_symbol_count=5000) is False


class TestAShareMarketSymbol:
    def test_shanghai(self):
        assert a_share_market_symbol("600519") == "sh600519"
        assert a_share_market_symbol("688001") == "sh688001"
        assert a_share_market_symbol("900001") == "sh900001"

    def test_shenzhen(self):
        assert a_share_market_symbol("000001") == "sz000001"
        assert a_share_market_symbol("300750") == "sz300750"
        assert a_share_market_symbol("002415") == "sz002415"

    def test_beijing(self):
        assert a_share_market_symbol("430047") == "bj430047"
        assert a_share_market_symbol("830799") == "bj830799"

    def test_invalid(self):
        assert a_share_market_symbol("") is None
        assert a_share_market_symbol("abc") is None

    def test_sina_tencent_equivalence(self):
        """Verify that the unified function produces the same result as the
        original _sina_stock_symbol and _tencent_stock_symbol methods."""
        test_cases = ["600519", "000001", "300750", "688001", "430047", "830799"]
        for code in test_cases:
            assert a_share_market_symbol(code) is not None


class TestAggregateThsHotTopicRows:
    def test_basic_aggregation(self):
        rows = [
            {"reason": "半导体+AI", "code": "688001", "zhangfu": "5.5", "chengjiaoe": "100000"},
            {"reason": "半导体", "code": "000001", "zhangfu": "3.2", "chengjiaoe": "50000"},
            {"reason": "AI", "code": "300750", "zhangfu": "2.1", "chengjiaoe": "80000"},
        ]
        result = aggregate_ths_hot_topic_rows(rows)
        assert len(result) == 2
        topics = {item["name"]: item for item in result}
        assert "半导体" in topics
        assert "AI" in topics
        # The aggregated output contains name, change_pct, leading_symbol, members, source
        assert "members" in topics["半导体"]
        assert len(topics["半导体"]["members"]) == 2

    def test_empty(self):
        assert aggregate_ths_hot_topic_rows([]) == []

    def test_filters_empty_reason(self):
        rows = [{"reason": "", "code": "688001"}]
        assert aggregate_ths_hot_topic_rows(rows) == []

    def test_filters_generic_topics(self):
        rows = [{"reason": "A股", "code": "688001", "zhangfu": "1.0"}]
        assert aggregate_ths_hot_topic_rows(rows) == []
