import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SavedStrategyStore } from "./savedStrategyStore";
import {
  cloneStrategyConfig,
  loadSavedStrategies,
  loadSavedStrategiesFromStore
} from "./savedStrategies";
import { defaultStrategy } from "./strategyDefaults";
import type { SavedStrategyPreset, StrategyConfig } from "./types";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function builtins(): SavedStrategyPreset[] {
  return [
    { id: "builtin-default", name: "基础均衡策略", saved_at: "builtin", strategy: cloneStrategyConfig(defaultStrategy) }
  ];
}

function customPreset(id: string, name: string): SavedStrategyPreset {
  return { id, name, saved_at: "2026-07-11T00:00:00Z", strategy: cloneStrategyConfig(defaultStrategy) };
}

function savableStrategy(name: string): StrategyConfig {
  return cloneStrategyConfig({ ...defaultStrategy, name });
}

function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function mutators(persister: (items: SavedStrategyPreset[]) => Promise<void>) {
  return [
    async (preset: SavedStrategyPreset, current: SavedStrategyPreset[]) => {
      const next = [preset, ...current.filter((item) => item.id !== preset.id)];
      await persister(next);
      return next;
    },
    async (presetId: string, current: SavedStrategyPreset[]) => {
      const next = current.filter((item) => item.id !== presetId);
      await persister(next);
      return next;
    }
  ] as const;
}

// ---------------------------------------------------------------------------
// Group A: lifecycle + concurrency invariants with injected loader/persister.
// ---------------------------------------------------------------------------

describe("SavedStrategyStore lifecycle", () => {
  it("waits for the in-flight initial load before saving (save-before-load race)", async () => {
    const load = deferred<SavedStrategyPreset[]>();
    const loader = vi.fn(() => load.promise);
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));

    store.start();
    expect(store.getState().status).toBe("loading");

    const savePromise = store.save(savableStrategy("我的策略"));
    // The save must NOT persist while the initial load is still pending.
    await flush();
    expect(persister).not.toHaveBeenCalled();

    load.resolve([...builtins(), customPreset("saved-existing", "既有策略")]);
    const result = await savePromise;

    expect(result.ok).toBe(true);
    expect(loader).toHaveBeenCalledTimes(1); // save reused the single initial load
    expect(persister).toHaveBeenCalledTimes(1);
    const persisted = persister.mock.calls[0][0];
    // The persisted set includes the existing custom preset — no data loss.
    expect(persisted.some((item: SavedStrategyPreset) => item.id === "saved-existing")).toBe(true);
    expect(store.getState().status).toBe("ready");
  });

  it("never persists after the initial load fails", async () => {
    const loader = vi.fn(async () => {
      throw new Error("disk unavailable");
    });
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));

    store.start();
    const result = await store.save(savableStrategy("我的策略"));

    expect(result.ok).toBe(false);
    expect(persister).not.toHaveBeenCalled();
    expect(store.getState().status).toBe("failed");
  });

  it("never persists after a failed reload (second load failure)", async () => {
    const loader = vi
      .fn()
      .mockResolvedValueOnce([...builtins(), customPreset("c1", "c1")])
      .mockRejectedValueOnce(new Error("reload failed"));
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));

    await store.start();
    expect(store.getState().status).toBe("ready");

    await store.reload();
    expect(store.getState().status).toBe("failed");

    const result = await store.save(savableStrategy("我的策略"));
    expect(result.ok).toBe(false);
    expect(persister).not.toHaveBeenCalled();
  });

  it("drops a stale load response that resolves after a save completed", async () => {
    const first = deferred<SavedStrategyPreset[]>();
    const stale = deferred<SavedStrategyPreset[]>();
    const loader = vi
      .fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => stale.promise);
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));

    const startPromise = store.start();
    first.resolve([...builtins(), customPreset("c1", "c1")]);
    await startPromise;

    // A background refresh is now in flight (returns the OLD snapshot without
    // the strategy we are about to save).
    const refreshPromise = store.refresh();

    const saveResult = await store.save(savableStrategy("新策略"));
    expect(saveResult.ok).toBe(true);
    expect(store.getState().strategies.some((item) => item.name === "新策略")).toBe(true);

    // The stale refresh resolves last with data that predates the save.
    stale.resolve([...builtins(), customPreset("c1", "c1")]);
    await refreshPromise;

    // The stale response must NOT have clobbered the saved strategy.
    expect(store.getState().strategies.some((item) => item.name === "新策略")).toBe(true);
  });

  it("serializes double-click saves without losing an update", async () => {
    const loader = vi.fn(async () => builtins());
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const [a, b] = await Promise.all([
      store.save(savableStrategy("重复策略")),
      store.save(savableStrategy("重复策略"))
    ]);

    expect(a.ok).toBe(true);
    expect(b.ok).toBe(true);
    expect(persister).toHaveBeenCalledTimes(2);
    // Second save observed the first one's result → unique auto-renamed name.
    const names = store.getState().strategies.map((item) => item.name);
    expect(names.filter((name) => name.startsWith("重复策略"))).toHaveLength(2);
    expect(new Set(names).size).toBe(names.length); // no duplicate names
  });

  it("serializes two concurrent deletes", async () => {
    const initial = [...builtins(), customPreset("c1", "c1"), customPreset("c2", "c2")];
    const loader = vi.fn(async () => initial.map((item) => ({ ...item })));
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const [a, b] = await Promise.all([store.remove("c1"), store.remove("c2")]);

    expect(a.ok).toBe(true);
    expect(b.ok).toBe(true);
    const ids = store.getState().strategies.map((item) => item.id);
    expect(ids).not.toContain("c1");
    expect(ids).not.toContain("c2");
    // The last persisted snapshot must contain neither removed entry.
    const lastPersist = persister.mock.calls[persister.mock.calls.length - 1][0];
    const lastIds = lastPersist.map((item: SavedStrategyPreset) => item.id);
    expect(lastIds).not.toContain("c1");
    expect(lastIds).not.toContain("c2");
  });

  it("serializes an interleaved save and delete", async () => {
    const initial = [...builtins(), customPreset("c1", "c1")];
    const loader = vi.fn(async () => initial.map((item) => ({ ...item })));
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const [saveRes, removeRes] = await Promise.all([
      store.save(savableStrategy("并发新策略")),
      store.remove("c1")
    ]);

    expect(saveRes.ok).toBe(true);
    expect(removeRes.ok).toBe(true);
    const ids = store.getState().strategies.map((item) => item.id);
    expect(ids).not.toContain("c1");
    expect(store.getState().strategies.some((item) => item.name === "并发新策略")).toBe(true);
  });

  it("persists two consecutive writes in order", async () => {
    const loader = vi.fn(async () => builtins());
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    await store.save(savableStrategy("策略一"));
    await store.save(savableStrategy("策略二"));

    expect(persister).toHaveBeenCalledTimes(2);
    const secondPersist = persister.mock.calls[1][0].map((item: SavedStrategyPreset) => item.name);
    expect(secondPersist).toContain("策略一");
    expect(secondPersist).toContain("策略二");
  });

  it("marks isMutating while a mutation is in flight", async () => {
    const persist = deferred<void>();
    const loader = vi.fn(async () => builtins());
    const persister = vi.fn(() => persist.promise);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const savePromise = store.save(savableStrategy("阻塞策略"));
    await flush();
    expect(store.getState().isMutating).toBe(true);

    persist.resolve();
    await savePromise;
    expect(store.getState().isMutating).toBe(false);
  });

  it("refuses to delete a built-in preset without persisting", async () => {
    const loader = vi.fn(async () => builtins());
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const result = await store.remove("builtin-default");
    expect(result.ok).toBe(false);
    expect(persister).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Group B: Tauri invoke boundary (not localStorage).
// ---------------------------------------------------------------------------

const invokeMock = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

describe("SavedStrategyStore over the Tauri invoke boundary", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
  });

  afterEach(() => {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, "__TAURI_INTERNALS__");
  });

  it("upserts one custom strategy atomically through invoke", async () => {
    invokeMock.mockImplementation(async (cmd: string, payload?: { preset?: SavedStrategyPreset }) => {
      if (cmd === "load_saved_strategies") {
        return [];
      }
      if (cmd === "upsert_saved_strategy") {
        return [payload?.preset];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);
    await store.start();

    const result = await store.save(savableStrategy("落盘策略"));
    expect(result.ok).toBe(true);

    const upsertCall = invokeMock.mock.calls.find((call) => call[0] === "upsert_saved_strategy");
    expect(upsertCall).toBeDefined();
    expect(upsertCall![1].preset.id.startsWith("builtin-")).toBe(false);
    expect(upsertCall![1].preset.name).toBe("落盘策略");
    expect(invokeMock.mock.calls.map((call) => call[0])).toEqual([
      "load_saved_strategies",
      "upsert_saved_strategy"
    ]);
  });

  it("fails the load (and blocks persist) when invoke returns malformed entries", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "load_saved_strategies") {
        return [{ id: "broken" /* missing name/saved_at/strategy */ }];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);

    await store.start();
    expect(store.getState().status).toBe("failed");

    const result = await store.save(savableStrategy("落盘策略"));
    expect(result.ok).toBe(false);
    expect(invokeMock.mock.calls.map((call) => call[0])).toEqual(["load_saved_strategies"]);
  });
});

// ---------------------------------------------------------------------------
// Group C: Round-4 strategy validation and reload hardening.
// ---------------------------------------------------------------------------

describe("SavedStrategyStore round-4 validation", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: {} });
  });

  afterEach(() => {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, "__TAURI_INTERNALS__");
  });

  it("rejects strategy null in load payload", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "load_saved_strategies") {
        return [{ id: "bad", name: "坏策略", saved_at: "2026-07-11T00:00:00Z", strategy: null }];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);
    await store.start();
    expect(store.getState().status).toBe("failed");
    expect(store.getState().error).toContain("strategy");
  });

  it("rejects missing market_filters array", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "load_saved_strategies") {
        return [{
          id: "bad", name: "坏策略", saved_at: "2026-07-11T00:00:00Z",
          strategy: { name: "坏策略", entry_groups: [], exit_rules: [] }
        }];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);
    await store.start();
    expect(store.getState().status).toBe("failed");
    expect(store.getState().error).toContain("market_filters");
  });

  it("rejects illegal entry_groups condition", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "load_saved_strategies") {
        return [{
          id: "bad", name: "坏策略", saved_at: "2026-07-11T00:00:00Z",
          strategy: {
            name: "坏策略",
            market_filters: [],
            entry_groups: [null],
            exit_rules: [],
            score_threshold: null
          }
        }];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);
    await store.start();
    expect(store.getState().status).toBe("failed");
  });

  it("rejects incomplete nested condition objects", async () => {
    invokeMock.mockImplementation(async (cmd: string) => {
      if (cmd === "load_saved_strategies") {
        return [{
          id: "bad", name: "坏策略", saved_at: "2026-07-11T00:00:00Z",
          strategy: {
            name: "坏策略",
            market_filters: [{}],
            entry_groups: [{ id: "g", operator: "and", conditions: [{}] }],
            exit_rules: [],
            score_threshold: null
          }
        }];
      }
      return undefined;
    });
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);
    await store.start();
    expect(store.getState().status).toBe("failed");
  });

  it("rejects corrupted localStorage data", () => {
    window.localStorage.setItem("astock-saved-strategies", "not-valid-json{{{");
    const result = loadSavedStrategies();
    // Should return builtins only, not crash
    expect(result.every((item) => item.id.startsWith("builtin-"))).toBe(true);
    window.localStorage.removeItem("astock-saved-strategies");
  });

  it("treats corrupted localStorage as an authoritative load failure", async () => {
    Reflect.deleteProperty(window as unknown as Record<string, unknown>, "__TAURI_INTERNALS__");
    window.localStorage.setItem("astock-saved-strategies", "not-valid-json{{{");
    const store = new SavedStrategyStore(builtins(), loadSavedStrategiesFromStore);

    await store.start();
    const result = await store.save(savableStrategy("不得覆盖"));

    expect(store.getState().status).toBe("failed");
    expect(result.ok).toBe(false);
    expect(window.localStorage.getItem("astock-saved-strategies")).toBe("not-valid-json{{{");
    window.localStorage.removeItem("astock-saved-strategies");
  });

  it("does not remain loading when a mutation supersedes a slow reload", async () => {
    const reload = deferred<SavedStrategyPreset[]>();
    const loader = vi.fn()
      .mockResolvedValueOnce([...builtins(), customPreset("c1", "c1")])
      .mockImplementationOnce(() => reload.promise);
    const persist = deferred<void>();
    const persister = vi.fn(() => persist.promise);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();

    const savePromise = store.save(savableStrategy("并发策略"));
    await flush();
    const reloadPromise = store.reload();
    expect(store.getState().status).toBe("loading");

    persist.resolve();
    expect((await savePromise).ok).toBe(true);
    expect(store.getState().status).toBe("ready");

    reload.resolve([...builtins(), customPreset("c1", "c1")]);
    await reloadPromise;
    expect(store.getState().status).toBe("ready");
    expect(store.getState().strategies.some((item) => item.name === "并发策略")).toBe(true);
  });

  it("reload during mutation leaves status as ready or failed, never loading", async () => {
    const initial = [...builtins(), customPreset("c1", "c1")];
    const loader = vi.fn(async () => initial.map((item) => ({ ...item })));
    const persister = vi.fn(async (_items: SavedStrategyPreset[]) => undefined);
    const store = new SavedStrategyStore(builtins(), loader, ...mutators(persister));
    await store.start();
    expect(store.getState().status).toBe("ready");

    // Start a save that will be blocked by a concurrent reload
    const persistGate = deferred<void>();
    persister.mockImplementationOnce(() => persistGate.promise as Promise<undefined>);

    const savePromise = store.save(savableStrategy("并发策略"));
    await flush();
    expect(store.getState().isMutating).toBe(true);

    // Reload while mutation is in-flight
    const reloadPromise = store.reload();
    await flush();

    // After reload resolves, status must be ready or failed — never loading
    expect(store.getState().status === "ready" || store.getState().status === "failed").toBe(true);

    persistGate.resolve();
    const saveResult = await savePromise;
    // The save may succeed or fail depending on timing, but it must complete
    expect(saveResult.ok !== undefined).toBe(true);
    expect(store.getState().status === "ready" || store.getState().status === "failed").toBe(true);
    expect(store.getState().status).not.toBe("loading");

    await reloadPromise;
  });
});
