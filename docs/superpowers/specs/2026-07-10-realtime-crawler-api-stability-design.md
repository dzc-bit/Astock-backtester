# Realtime Crawler and API Stability Design

## Goal

Improve the reliability of realtime market and sector acquisition without changing the existing source semantics, and make long-running NDJSON APIs terminate predictably when a source, connection, or client stalls.

## Scope

- Keep the current source priority: CLS, Tonghuashun, Sina, Tencent, AKShare, controlled Eastmoney fallback.
- Add a bounded alternate HTTP transport for public pages that commonly reject or disconnect ordinary `requests` traffic.
- Apply the same bounded transport and a 12-second total budget to the Eastmoney columns, rolling-page, and 7x24 market-news feeds, with source failures exposed through response diagnostics.
- Stop launching additional sources after a request budget expires.
- Preserve structured diagnostics for primary failures, alternate transport use, incomplete payloads, and fallbacks.
- Add client cancellation and idle timeouts to realtime and backtest NDJSON streams.
- Treat client disconnects as normal stream termination on the service.
- Align the Python sidecar version with desktop version `1.3.3`.
- Lazy-load the result chart so Recharts is not part of the initial application chunk.

## Crawler Architecture

The existing provider methods remain responsible for source-specific parsing and validation. A small transport helper will wrap public HTTP GET calls. It first uses the injected requester, retries one transient failure while budget remains, and, only when the production default requester is in use, falls back to `curl_cffi` with a browser TLS fingerprint. Test requesters never trigger real network fallbacks.

Realtime breadth and sector orchestration receives a request-scoped deadline and cancellation event. Each source checks the remaining budget before starting. When the outer time budget expires it sets the event, so a slow source may finish its own bounded call but cannot continue launching the rest of the chain or publish late request state as current data.

Cached results remain explicitly stale or retained fallbacks. They are never included in the current request's live completeness decision.

## Stream Architecture

The frontend will use one NDJSON reader helper with:

- an internal `AbortController`;
- optional caller cancellation;
- an idle timer reset whenever bytes arrive;
- reader cancellation and clear timeout errors;
- deterministic cleanup of timers and abort listeners.

Realtime streams use a short idle timeout. Backtests use a longer idle timeout because computation can legitimately take longer between events. Callers can override these values for tests or future UI controls.

The Python HTTP service will stop producing events after `BrokenPipeError`, `ConnectionResetError`, or `ConnectionAbortedError`. It will not attempt to write an NDJSON error or a second JSON response after the client has gone away.

## Performance and Versioning

`ResultsOverview` will be loaded through `React.lazy` and `Suspense`. The result chart and Recharts dependency therefore move to a separate chunk while the workbench remains usable during loading.

A build test will compare `package.json`, `pyproject.toml`, Tauri config, and Cargo package versions so release bumps cannot omit the sidecar again.

## Verification

- Unit tests prove transient retry, alternate transport gating, deadline cancellation, and diagnostic behavior.
- News tests prove total-budget exhaustion prevents later sources from starting and that alternate transport use remains observable.
- Frontend fake-stream tests prove idle timeout and caller abort behavior.
- Service tests prove disconnects do not produce secondary writes.
- Existing Python, frontend, typecheck, build, and Rust suites remain green.
- Production build output confirms Recharts is separated from the initial chunk.

## Second-Pass Reliability Extension

The news and news-summary endpoints are requested together, so they must not launch duplicate upstream crawls. `MarketNewsProvider` will serialize refreshes, keep a short-lived complete response for request coalescing, and retain the most recent successful response for a bounded stale fallback. A stale fallback keeps its original `updated_at`, adds `recent-success-cache` to the source, and preserves the failures from the current refresh in diagnostics.

The three independent news feeds will run concurrently under the existing 12-second total budget. Results and diagnostics are assembled in the configured source order; unfinished workers are discarded from the current response and cannot publish provider state. This prevents one slow page or API from starving another healthy feed.

Eastmoney rolling-page links will be parsed as HTML elements rather than with attribute-order-dependent regular expressions. News-summary responses will propagate crawler diagnostics instead of hiding upstream failures.

For ordinary JSON APIs, the frontend timeout covers both response headers and response-body decoding. The service treats disconnects during JSON writes like stream disconnects: the request ends without logging an application failure or attempting a second response.

Additional verification proves concurrent source completion, duplicate-request coalescing, recent-success fallback labeling, attribute-order-independent parsing, news-summary diagnostic propagation, stalled JSON-body timeout, and non-stream JSON disconnect handling.

## Live-Source Correction

A 2026-07-10 runtime probe confirmed that `cls.cn/nodeapi/telegraphList` is retired and returns HTTP 404. The signed `updateTelegraphList` candidate also returns 404 from both ordinary requests and browser-fingerprint transport, so the crawler must not spend budget or emit recurring noise against either path. The replacement is Eastmoney's public 7x24 `getFastNewsList` feed, which returned current structured rows in the same probe. No account, cookie pool, proxy, private key, or authentication bypass is used.

Realtime sector workers publish into private request-local lists. Only the coordinator copies those rows after an in-budget future result, eliminating the cancellation-check/write race. Tonghuashun page caches and local-topic skip state are request-local rather than provider fields. Client socket errors are translated to a dedicated disconnect exception only at HTTP write boundaries, so an upstream `ConnectionResetError` remains a structured domain failure.
