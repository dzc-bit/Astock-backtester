import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importDailyBars, loadClsFinance, loadDataServiceHealth, startFullMarketSync } from "./api";

describe("service fetch timeouts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {}
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("keeps long-running import requests alive past the default short timeout", async () => {
    let resolveFetch: ((response: Response) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        requestSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>((resolve, reject) => {
          resolveFetch = resolve;
          requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      })
    );

    const request = importDailyBars("http://127.0.0.1:9010", "sample");
    const settled = request.then(
      (value) => ({ ok: true as const, value }),
      (error) => ({ ok: false as const, error })
    );

    await vi.advanceTimersByTimeAsync(12000);
    expect(requestSignal?.aborted).toBe(false);

    resolveFetch?.(
      new Response(JSON.stringify({ status: "ok", imported_rows: 2, coverage: [], logs: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(settled).resolves.toEqual({
      ok: true,
      value: expect.objectContaining({
        status: "ok",
        imported_rows: 2
      })
    });
  });

  it("keeps warehouse health checks alive past the default short timeout", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        requestSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>((_resolve, reject) => {
          requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      })
    );

    const settled = loadDataServiceHealth("http://127.0.0.1:9010").then(
      (value) => ({ ok: true as const, value }),
      (error) => ({ ok: false as const, error })
    );

    await vi.advanceTimersByTimeAsync(12000);
    expect(requestSignal?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(48000);

    await expect(settled).resolves.toEqual({
      ok: false,
      error: expect.objectContaining({
        message: "本地数据服务请求超时，请稍后重试或重新连接本地服务。"
      })
    });
  });

  it("keeps CLS finance requests alive while backend reads the market board", async () => {
    let resolveFetch: ((response: Response) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        requestSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>((resolve, reject) => {
          resolveFetch = resolve;
          requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      })
    );

    const settled = loadClsFinance("http://127.0.0.1:9010").then(
      (value) => ({ ok: true as const, value }),
      (error) => ({ ok: false as const, error })
    );

    await vi.advanceTimersByTimeAsync(12000);
    expect(requestSignal?.aborted).toBe(false);

    resolveFetch?.(
      new Response(
        JSON.stringify({
          updated_at: "2026-06-09T03:46:34Z",
          source: "cls-finance",
          source_url: "https://www.cls.cn/finance",
          preclose_px: 3959.337,
          tline: [{ date: 20260609, minute: 1500, last_px: 4015.5, change: 0.0142 }],
          anchors: [
            {
              code: "cls80025",
              name: "PCB",
              article_id: 2394344,
              c_time: "2026-06-09 09:31:30",
              direction: "up",
              url: "https://www.cls.cn/plate?code=cls80025"
            }
          ],
          emotion: { market_degree: 56, up_limit: 130, open_limit: 25 },
          up_pool: [{ symbol: "601869", name: "长飞光纤", change_pct: 0.1, plates: [] }],
          diagnostics: []
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    await expect(settled).resolves.toEqual({
      ok: true,
      value: expect.objectContaining({
        source: "cls-finance",
        source_url: "https://www.cls.cn/finance",
        anchors: expect.arrayContaining([expect.objectContaining({ name: "PCB" })]),
        up_pool: expect.arrayContaining([expect.objectContaining({ symbol: "601869" })])
      })
    });
  });

  it("keeps full-market sync start requests alive while the backend prepares symbols", async () => {
    let resolveFetch: ((response: Response) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        requestSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>((resolve, reject) => {
          resolveFetch = resolve;
          requestSignal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        });
      })
    );

    const settled = startFullMarketSync("http://127.0.0.1:9010", "2026-06-01", "2026-06-05").then(
      (value) => ({ ok: true as const, value }),
      (error) => ({ ok: false as const, error })
    );

    await vi.advanceTimersByTimeAsync(12000);
    expect(requestSignal?.aborted).toBe(false);

    resolveFetch?.(
      new Response(
        JSON.stringify({
          job: {
            job_id: "job-1",
            mode: "full_market_bootstrap",
            status: "running",
            total_symbols: 5445,
            completed_symbols: 0,
            failed_symbols: 0,
            imported_rows: 0,
            start_date: "2026-06-01",
            end_date: "2026-06-05",
            errors: []
          }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    await expect(settled).resolves.toEqual({
      ok: true,
      value: expect.objectContaining({
        job: expect.objectContaining({ job_id: "job-1", status: "running" })
      })
    });
  });
});
