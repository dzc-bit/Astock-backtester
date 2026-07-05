import { afterEach, expect, it, vi } from "vitest";
import { ensureDataService } from "./api";

const invokeMock = vi.hoisted(() => vi.fn());

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock
}));

afterEach(() => {
  invokeMock.mockReset();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  Reflect.deleteProperty(globalThis, "isTauri");
});

it("uses the desktop service command when Tauri v2 exposes global isTauri", async () => {
  Object.defineProperty(globalThis, "isTauri", {
    configurable: true,
    value: true
  });
  invokeMock.mockResolvedValueOnce({
    running: true,
    port: 17068,
    base_url: "http://127.0.0.1:17068",
    cache_dir: "D:\\New project 6\\运行产物\\本地数据仓",
    message: "local data service started"
  });

  const status = await ensureDataService(".astock-cache");

  expect(status.base_url).toBe("http://127.0.0.1:17068");
  expect(invokeMock).toHaveBeenCalledWith("ensure_data_service", {
    cacheDir: ".astock-cache"
  });
});
