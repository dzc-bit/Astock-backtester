import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { loadSavedStrategies } from "./savedStrategies";
import { SavedStrategyStore, type StrategyStoreState } from "./savedStrategyStore";

export interface UseSavedStrategyStore extends StrategyStoreState {
  store: SavedStrategyStore;
}

/**
 * React binding for {@link SavedStrategyStore}. The store instance is created
 * once and its single initial load is started on mount; the component
 * re-renders whenever the store's state changes.
 */
export function useSavedStrategyStore(): UseSavedStrategyStore {
  const storeRef = useRef<SavedStrategyStore | null>(null);
  if (!storeRef.current) {
    // Optimistic built-ins keep the UI populated until the authoritative load
    // resolves; they are never persisted on their own.
    storeRef.current = new SavedStrategyStore(loadSavedStrategies());
  }
  const store = storeRef.current;

  const subscription = useMemo(
    () => ({
      subscribe: (listener: () => void) => store.subscribe(listener),
      getSnapshot: () => store.getState()
    }),
    [store]
  );

  const state = useSyncExternalStore(subscription.subscribe, subscription.getSnapshot, subscription.getSnapshot);

  useEffect(() => {
    void store.start();
  }, [store]);

  return { store, ...state };
}
