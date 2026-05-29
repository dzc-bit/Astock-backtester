import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importDailyBars, loadDataServiceHealth } from "./api";

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

  it("still times out short health checks after 12 seconds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init?: RequestInit) => {
        const requestSignal = init?.signal as AbortSignal | undefined;
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

    await expect(settled).resolves.toEqual({
      ok: false,
      error: expect.objectContaining({
        message: "本地数据服务请求超时，请稍后重试或重新连接本地服务。"
      })
    });
  });
});
