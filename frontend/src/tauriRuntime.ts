type TauriRuntimeGlobals = typeof globalThis & {
  __TAURI__?: unknown;
  __TAURI_INTERNALS__?: unknown;
  isTauri?: boolean;
};

export function isTauriRuntime(): boolean {
  const globals = globalThis as TauriRuntimeGlobals;
  return globals.isTauri === true || Boolean(globals.__TAURI_INTERNALS__) || Boolean(globals.__TAURI__);
}
