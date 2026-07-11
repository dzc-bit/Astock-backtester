import type { SavedStrategyPreset, StrategyConfig } from "./types";
import {
  createSavedStrategyPreset,
  deleteSavedStrategyFromStore,
  isBuiltInStrategyPreset,
  loadSavedStrategiesFromStore,
  upsertSavedStrategyToStore
} from "./savedStrategies";

export type StrategyLoadStatus = "loading" | "ready" | "failed";

export interface StrategyStoreState {
  status: StrategyLoadStatus;
  strategies: SavedStrategyPreset[];
  isMutating: boolean;
  error: string | null;
}

export interface MutationResult {
  ok: boolean;
  error?: string;
  savedName?: string;
  removedName?: string;
}

export type StrategyLoader = () => Promise<SavedStrategyPreset[]>;
export type StrategyUpserter = (
  preset: SavedStrategyPreset,
  current: SavedStrategyPreset[]
) => Promise<SavedStrategyPreset[]>;
export type StrategyDeleter = (
  presetId: string,
  current: SavedStrategyPreset[]
) => Promise<SavedStrategyPreset[]>;

function errorDetail(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Framework-agnostic controller for the saved-strategy persistence lifecycle.
 *
 * It solves the data-loss races that the previous inline React logic had:
 *
 * 1. Explicit load state machine (`loading` / `ready` / `failed`). Mutations are
 *    only allowed once the store is `ready`; a failed or still-loading store can
 *    never persist and thus can never overwrite on-disk data with a partial
 *    (builtins-only) snapshot.
 * 2. A single initial load is reused by every mutation via {@link ensureLoaded};
 *    mutations never kick off their own competing load.
 * 3. Monotonic load ids guarantee no out-of-order overwrite: a stale load result
 *    that resolves after a newer load — or after a mutation completed — is
 *    dropped instead of clobbering authoritative state.
 * 4. All mutations are serialized through a single promise chain, so double-click
 *    saves, concurrent deletes, and save/delete interleavings cannot lose an
 *    update; each mutation observes the result of the previous one.
 */
export class SavedStrategyStore {
  private status: StrategyLoadStatus = "loading";
  private strategies: SavedStrategyPreset[];
  private error: string | null = null;
  private pendingMutations = 0;

  private initialLoad: Promise<void> | null = null;
  private mutationTail: Promise<unknown> = Promise.resolve();
  // Monotonic counter incremented for every load issued and for every applied
  // mutation. Only the result of the load whose id equals `authoritativeLoadId`
  // may be applied, so stale (late) load responses are dropped.
  private loadCounter = 0;
  private authoritativeLoadId = 0;

  private readonly listeners = new Set<() => void>();
  private cachedState: StrategyStoreState | null = null;

  constructor(
    initial: SavedStrategyPreset[],
    private readonly loader: StrategyLoader = loadSavedStrategiesFromStore,
    private readonly upserter: StrategyUpserter = upsertSavedStrategyToStore,
    private readonly deleter: StrategyDeleter = deleteSavedStrategyFromStore
  ) {
    this.strategies = initial;
  }

  getState(): StrategyStoreState {
    if (!this.cachedState) {
      this.cachedState = {
        status: this.status,
        strategies: this.strategies,
        isMutating: this.pendingMutations > 0,
        error: this.error
      };
    }
    return this.cachedState;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private emit(): void {
    this.cachedState = null;
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** Kick off the single initial load. Idempotent — repeated calls reuse it. */
  start(): Promise<void> {
    if (!this.initialLoad) {
      this.initialLoad = this.issueLoad({ blocking: true });
    }
    return this.initialLoad;
  }

  /**
   * Retry the authoritative load (e.g. after an initial failure). The returned
   * promise becomes the one {@link ensureLoaded} awaits, so a subsequent failed
   * reload still blocks mutations from persisting.
   *
   * Round-4: reload is protected by a monotonic id so that a stale reload that
   * resolves after a mutation completed cannot clobber freshly persisted state.
   * A mutation in-flight when reload is called will see the reload as the
   * authoritative load; the reload's completion unblocks the mutation queue.
   * On reload failure the status is explicitly `failed` — never `loading`.
   */
  reload(): Promise<void> {
    this.initialLoad = this.issueLoad({ blocking: true });
    return this.initialLoad;
  }

  /**
   * Best-effort background refresh that never blocks pending mutations. Its
   * result is applied only if it is still the authoritative load when it
   * resolves; a mutation completing in the meantime supersedes it.
   */
  refresh(): Promise<void> {
    return this.issueLoad({ blocking: false });
  }

  private issueLoad({ blocking }: { blocking: boolean }): Promise<void> {
    this.loadCounter += 1;
    const id = this.loadCounter;
    this.authoritativeLoadId = id;
    if (blocking) {
      this.status = "loading";
      this.error = null;
      this.emit();
    }
    return this.loader()
      .then((items) => {
        if (id === this.authoritativeLoadId) {
          this.strategies = items;
          this.status = "ready";
          this.error = null;
          this.emit();
        }
      })
      .catch((err) => {
        if (id === this.authoritativeLoadId) {
          this.status = "failed";
          this.error = errorDetail(err);
          this.emit();
        }
      });
  }

  private async ensureLoaded(): Promise<void> {
    if (!this.initialLoad) {
      this.start();
    }
    try {
      await this.initialLoad;
    } catch {
      // Failure state is recorded inside issueLoad; callers inspect status.
    }
  }

  private bumpAfterMutation(): void {
    // Invalidate any in-flight load so its late result cannot overwrite the
    // freshly persisted state.
    this.loadCounter += 1;
    this.authoritativeLoadId = this.loadCounter;
    this.status = "ready";
    this.error = null;
  }

  private enqueue<T>(op: () => Promise<T>): Promise<T> {
    this.pendingMutations += 1;
    this.emit();
    const run = this.mutationTail.then(op, op);
    this.mutationTail = run.then(
      () => undefined,
      () => undefined
    );
    return run.finally(() => {
      this.pendingMutations -= 1;
      this.emit();
    });
  }

  /** Persist a new preset built from `strategy`. Serialized against all other mutations. */
  save(strategy: StrategyConfig): Promise<MutationResult> {
    return this.enqueue(() => this.performSave(strategy));
  }

  private async performSave(strategy: StrategyConfig): Promise<MutationResult> {
    await this.ensureLoaded();
    if (this.status !== "ready") {
      return {
        ok: false,
        error: this.error ?? "已保存策略尚未加载完成，暂不能保存，以免覆盖磁盘数据。"
      };
    }
    try {
      const preset = createSavedStrategyPreset(strategy, this.strategies);
      this.strategies = await this.upserter(preset, this.strategies);
      this.bumpAfterMutation();
      this.emit();
      return { ok: true, savedName: preset.name };
    } catch (err) {
      return { ok: false, error: errorDetail(err) };
    }
  }

  /** Remove a saved preset by id. Built-ins are refused. Serialized against all other mutations. */
  remove(presetId: string): Promise<MutationResult> {
    if (isBuiltInStrategyPreset(presetId)) {
      return Promise.resolve({ ok: false, error: "内置基础策略会一直保留，不能删除。" });
    }
    return this.enqueue(() => this.performRemove(presetId));
  }

  private async performRemove(presetId: string): Promise<MutationResult> {
    await this.ensureLoaded();
    if (this.status !== "ready") {
      return {
        ok: false,
        error: this.error ?? "已保存策略尚未加载完成，暂不能删除，以免覆盖磁盘数据。"
      };
    }
    try {
      const target = this.strategies.find((item) => item.id === presetId);
      this.strategies = await this.deleter(presetId, this.strategies);
      this.bumpAfterMutation();
      this.emit();
      return { ok: true, removedName: target?.name };
    } catch (err) {
      return { ok: false, error: errorDetail(err) };
    }
  }
}
