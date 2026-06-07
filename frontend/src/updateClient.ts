import { getVersion } from "@tauri-apps/api/app";
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";
import type { DownloadEvent } from "@tauri-apps/plugin-updater";

declare global {
  const __APP_VERSION__: string;

  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export type InstallEvent =
  | { event: "Started"; data: { contentLength?: number } }
  | { event: "Progress"; data: { chunkLength: number } }
  | { event: "Finished" };

export interface AvailableUpdate {
  version: string;
  date?: string;
  body?: string;
  downloadAndInstall(onEvent?: (event: InstallEvent) => void): Promise<void>;
}

export interface UpdateApi {
  isRuntime(): boolean;
  getVersion(): Promise<string>;
  check(): Promise<AvailableUpdate | null>;
  relaunch(): Promise<void>;
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

function messageFrom(caught: unknown): string {
  if (caught instanceof Error) {
    return caught.message;
  }
  return String(caught ?? "");
}

export function translateUpdateError(caught: unknown): string {
  const message = messageFrom(caught).toLowerCase();

  if (/(signature|pubkey|public key|verify|verification|ed25519)/i.test(message)) {
    return "更新文件校验失败，请确认安装包来源可信后重试。";
  }
  if (/(network|fetch|dns|timeout|timed out|connection|offline|resolve|host)/i.test(message)) {
    return "网络连接异常，暂时无法检查更新。";
  }
  if (/(endpoint|url|404|not found|manifest|latest\.json)/i.test(message)) {
    return "更新服务地址暂不可用，请稍后重试。";
  }
  if (/(install|permission|extract|rename|replace|write)/i.test(message)) {
    return "安装更新失败，请关闭占用程序后重试。";
  }
  return "检查更新失败，请稍后重试。";
}

function mapInstallEvent(event: DownloadEvent): InstallEvent {
  return event;
}

export function createTauriUpdateApi(): UpdateApi {
  return {
    isRuntime: isTauriRuntime,
    async getVersion() {
      if (!isTauriRuntime()) {
        return __APP_VERSION__;
      }
      return getVersion();
    },
    async check() {
      if (!isTauriRuntime()) {
        return null;
      }

      const update = await check({ timeout: 30000 });
      if (!update) {
        return null;
      }

      return {
        version: update.version,
        date: update.date,
        body: update.body,
        downloadAndInstall(onEvent) {
          return update.downloadAndInstall(
            onEvent ? (event) => onEvent(mapInstallEvent(event)) : undefined
          );
        }
      };
    },
    async relaunch() {
      if (isTauriRuntime()) {
        await relaunch();
      }
    }
  };
}
