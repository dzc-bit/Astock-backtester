# Capital Flow Crawler Integration Report

Date: 2026-06-08

## Scope

This report covers the standalone Eastmoney capital-flow crawler added in
`backend/astock_backtester/data/capital_flow_crawler.py`.

The crawler is included in the 1.1.1 backend as a low-level provider/crawler boundary. It only reads Eastmoney public XHR and returns structured Python data plus per-symbol `failures` and `diagnostics`. The crawler itself does not write `LocalCache` or `Warehouse`.

In 1.1.1 the higher-level data service now owns the write boundary:

- `POST /fetch/daily-bars` fetches daily bars through the normal provider chain, then uses the capital-flow crawler as the primary `main_net_inflow` source before writing the merged frame.
- `POST /fetch/capital-flow` reads existing local daily bars and backfills only missing `main_net_inflow` values.
- Failed symbols are returned through `DataOperationResult.failures` and `DataOperationResult.diagnostics`, and the data center surfaces those structured failures without embedding upstream URLs or crawler parsing rules in React.

## Files

- `backend/astock_backtester/data/capital_flow_crawler.py`
- `backend/astock_backtester/data/operations.py`
- `backend/astock_backtester/service.py`
- `backend/astock_backtester/models.py`
- `frontend/src/api.ts`
- `frontend/src/components/DataCenter.tsx`
- `tests/test_capital_flow_crawler.py`
- `tests/test_data_operations.py`
- `tests/test_data_service_http.py`

The crawler remains independent from realtime market snapshot, commentary, news, briefing, user-mode candidates, and risk modules.

## Eastmoney Endpoint

Endpoint:

```text
https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get
```

Crawler request params:

```text
secid={market}.{code}
fields1=f1,f2,f3,f7
fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63
klt=101
lmt={limit}
```

Request behavior:

- Fixed timeout is passed by the caller.
- The crawler tries two public header variants: `data.eastmoney.com/zjlx/detail.html` first, then `quote.eastmoney.com`.
- If both variants fail, the raised error keeps both source diagnostics.
- It does not use login, cookies, proxy pools, CAPTCHA bypass, or paid scraping.

Market mapping:

- Shanghai A/B style codes starting with `6` or `9`: `market=1`
- Shenzhen, ChiNext, Beijing-style fallback: `market=0`

Accepted symbol forms:

- `600519`
- `SH600519`
- `600519.SH`
- `sz000001`

## Parsed Row Shape

`CapitalFlowCrawler.fetch_fund_flow(symbol, start_date, end_date, limit=None, timeout=15)` returns:

```python
[
    {
        "symbol": "600519",
        "trade_date": "2026-06-05",
        "main_net_inflow": -113929472.0,
        "small_net_inflow": -379347.0,
        "medium_net_inflow": 114308816.0,
        "large_net_inflow": -331703296.0,
        "super_large_net_inflow": 217773824.0,
        "main_net_inflow_pct": -2.86,
        "small_net_inflow_pct": -0.01,
        "medium_net_inflow_pct": 2.87,
        "large_net_inflow_pct": -8.33,
        "super_large_net_inflow_pct": 5.47,
        "close": 1272.86,
        "change_pct": 0.38,
    }
]
```

The key field required by current backtest conditions is:

```text
main_net_inflow
```

The current warehouse/cache daily-bar schema already uses this same name, so later backend integration can merge on:

```text
symbol + trade_date
```

## Batch API

`CapitalFlowCrawler.fetch_many_fund_flows(symbols, start_date, end_date, limit=None, timeout=15)` returns:

```python
{
    "rows": [...],
    "failures": [
        {
            "symbol": "000001",
            "code": "network_error",
            "error": "Failed to fetch Eastmoney capital flow for 000001: ..."
        }
    ],
    "diagnostics": [...]
}
```

This shape is consumed by higher-level service code:

- Do not fail the whole batch when one symbol fails.
- Persist successful rows only after `fetch_daily_bars_into_cache(...)` or `fetch_capital_flow_into_cache(...)` decides the write boundary.
- Surface `failures` and `diagnostics` as service logs and data-center status.

## Verification Commands

Local parser and batch behavior:

```powershell
python -m pytest tests/test_capital_flow_crawler.py -q
```

Result:

```text
8 passed in 0.59s
```

Python compile check:

```powershell
python -m py_compile backend/astock_backtester/data/capital_flow_crawler.py tests/test_capital_flow_crawler.py
```

Result: exit code `0`.

Compatibility check with the existing HTTP adapter tests:

```powershell
python -m pytest tests/test_capital_flow_crawler.py tests/test_astock_adapter.py -q
```

Latest result:

```text
17 passed in 4.15s
```

`ruff` was not available in this local Python environment:

```text
No module named ruff
```

## Live Eastmoney Test Results

### Single Symbol

Command summary:

```powershell
$env:PYTHONPATH='backend'
python - <<script using CapitalFlowCrawler().fetch_fund_flow('600519', '2026-06-01', '2026-06-05', limit=5)
```

Result from this machine:

```text
ok=True, rows=5
first trade_date=2026-06-01
last trade_date=2026-06-05
```

The returned sample included valid numeric `main_net_inflow`, order-flow bucket fields, close, and change percent.

### Immediate Batch Test

Symbols:

```text
600519, 000001, 300750, 688981, 601318, 002594, 830799, 920799
```

Result:

```text
total=8, ok=0, failed=8
```

All failures were remote disconnects:

```text
RemoteDisconnected('Remote end closed connection without response')
```

### Repeated Single-Symbol Retry

Four retries of `600519` with 3-second spacing:

```text
attempts=4, ok=0, failed=4
```

All failures were the same remote disconnect.

### Curl/Header Variants

Tested with:

- `Referer: https://data.eastmoney.com/zjlx/detail.html`
- `Referer: https://quote.eastmoney.com/`
- no explicit referer

All curl variants failed with server-side abrupt close:

```text
curl: (56) schannel: server closed abruptly (missing close_notify)
```

### Batch API Retest

Symbols:

```text
600519, 000001, 300750, 688981
```

Result through `fetch_many_fund_flows`:

```text
rows=0, failures=4
```

All failures were remote disconnects.

## Current Conclusion

The crawler can parse and batch-process Eastmoney capital-flow payloads. It is now used in 1.1.1 as the backend capital-flow provider for data-center backfills, while still staying out of direct warehouse writes. The local tests cover:

- request construction
- `secid` mapping
- date filtering
- raw `klines` field mapping
- malformed rows
- blank numeric values
- network failure diagnostics
- header-variant retry after remote disconnect
- partial success in batch mode
- empty payload / empty kline failure semantics
- malformed numeric diagnostics without dropping otherwise usable rows
- date coverage shortfall diagnostics
- service-level merge into `main_net_inflow`
- independent `/fetch/capital-flow` backfill for existing daily bars
- in-process recent successful row reuse after disconnect, marked with `recent_success_cache_used` while retaining the original failure

Live access from the current machine is not stable enough for reliable batch crawling. A single request succeeded once, then immediate batch and retry tests were blocked by server-side disconnects. The evidence points to Eastmoney network-side throttling or anti-crawl behavior for this environment, not to parser failure.

## Backend Integration Boundary

Implemented flow:

1. Keep `CapitalFlowCrawler` as the low-level interface adapter.
2. Use `fetch_many_fund_flows(symbols, start_date, end_date, timeout=15)` from the HTTP service layer.
3. Convert returned `rows` to a DataFrame and merge only `main_net_inflow` into existing daily bars by `symbol + trade_date`.
4. Let `fetch_daily_bars_into_cache(...)` merge crawler values as the primary capital-flow source for newly fetched daily bars.
5. Let `fetch_capital_flow_into_cache(...)` backfill only missing `main_net_inflow` in existing daily bars.
6. Write to `LocalCache` / `Warehouse` only in those higher-level services, not inside the crawler.
7. Report `failures` through `DataOperationResult.failures`, service logs, and data-center diagnostics.

Suggested write fields for current strategy compatibility:

```text
symbol
trade_date
main_net_inflow
```

Optional diagnostic/enrichment fields:

```text
main_net_inflow_pct
small_net_inflow
small_net_inflow_pct
medium_net_inflow
medium_net_inflow_pct
large_net_inflow
large_net_inflow_pct
super_large_net_inflow
super_large_net_inflow_pct
close
change_pct
```

## Frontend Alignment

The data center does not show a simple binary success/failure for this source. It calls a structured backend endpoint and keeps all upstream source details in the backend:

- `fetchCapitalFlow(...)` calls `POST /fetch/capital-flow`.
- `FetchResult` carries optional `diagnostics` and `failures`.
- `DataCenter` displays failed symbols and diagnostic codes in the operation status.
- React does not contain upstream URLs, crawler logic, or Eastmoney field-cleaning rules.

Useful structured fields:

```ts
type CapitalFlowBackfillSummary = {
  requested_symbols: number;
  succeeded_symbols: number;
  failed_symbols: number;
  imported_rows: number;
  start_date: string;
  end_date: string;
  diagnostics: string[];
};
```

For the current environment, the UI should expect `blocked_by_source` or `partial` when Eastmoney disconnects after one or several requests.

## Risk Notes

- Do not run aggressive full-market crawling through this endpoint without throttling.
- Do not write failed/missing rows as zero; keep missing values missing.
- Do not let a failed symbol abort the whole backfill.
- Do not hide `RemoteDisconnected` from the user; it is the important operational signal.
- If mainland IP or upstream risk control blocks requests, keep fixed timeouts, limited public header variants, fast failure, in-process recent successful row reuse, and clear diagnostics. Do not add login, cookie pools, proxy pools, CAPTCHA bypass, or paid scraping.
