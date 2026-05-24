# Windows Auto Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows desktop in-app update flow so installed users can check, download, install, and relaunch into newer GitHub Release builds.

**Architecture:** Use Tauri v2's official updater plugin with GitHub Releases as the static update endpoint. Keep update behavior isolated in a small frontend update client and a focused `UpdatePanel` component; Tauri config owns signing, endpoint, artifacts, and plugin permissions.

**Tech Stack:** Tauri 2, `tauri-plugin-updater`, `tauri-plugin-process`, `@tauri-apps/plugin-updater`, `@tauri-apps/plugin-process`, React, TypeScript, Vitest, GitHub Releases, NSIS.

---

## References

- Product spec: `docs/superpowers/specs/2026-05-24-windows-auto-update-design.md`
- Tauri updater docs: https://v2.tauri.app/plugin/updater/
- Tauri process plugin docs: https://v2.tauri.app/plugin/process/
- Updater package versions verified on 2026-05-24: `tauri-plugin-updater` / `@tauri-apps/plugin-updater` `2.10.1`, `tauri-plugin-process` / `@tauri-apps/plugin-process` `2.3.1`.

## Scope Check

This plan covers one subsystem: Windows in-app updates for the existing desktop app. It does not add GitHub Actions release automation, mobile updates, macOS/Linux update targets, or an update server.

Important migration constraint: any already-installed build that does not contain the updater cannot update itself. Users of pre-updater builds must manually install the first updater-enabled NSIS installer once. After that, later signed releases can be installed through the app.

## File Structure

Modify or create these files:

- `package.json`: add updater and process JavaScript guest bindings.
- `package-lock.json`: lock the new JavaScript dependencies.
- `src-tauri/Cargo.toml`: add Rust updater and process plugins.
- `src-tauri/Cargo.lock`: lock the new Rust dependencies after build/check.
- `src-tauri/src/lib.rs`: register the Tauri updater and process plugins.
- `src-tauri/tauri.conf.json`: enable updater artifacts, configure GitHub latest endpoint, configure public key, and set Windows install mode.
- `src-tauri/capabilities/main.json`: grant updater and process plugin permissions to the main window.
- `frontend/src/updateClient.ts`: isolate runtime detection, update checks, install progress, relaunch, and Chinese error translation.
- `frontend/src/components/UpdatePanel.tsx`: show current version, check status, available update details, progress, and install action.
- `frontend/src/components/UpdatePanel.test.tsx`: unit tests for up-to-date, available update, install, and error states.
- `frontend/src/App.tsx`: add `UpdatePanel` to the existing topbar actions.
- `frontend/src/styles.css`: style the update panel without disrupting the existing layout.
- `frontend/src/__tests__/strategyEditor.test.tsx`: add a regression assertion that the Chinese update entry renders.
- `docs/release.md`: document signing keys, versioning, release assets, `latest.json`, and the first manual migration installer.
- `docs/dev.md`: link to release/update instructions and add the update build verification command.

## Task 1: Add Tauri Updater Dependencies And Permissions

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/Cargo.lock`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/tauri.conf.json`
- Create: `src-tauri/capabilities/main.json`

- [ ] **Step 1: Install JavaScript guest bindings**

Run:

```powershell
npm install @tauri-apps/plugin-updater@^2.10.1 @tauri-apps/plugin-process@^2.3.1
```

Expected: `package.json` contains the two new dependencies and `package-lock.json` changes. If the sandbox blocks network access, rerun with escalation.

- [ ] **Step 2: Add Rust plugin dependencies**

Modify `src-tauri/Cargo.toml` so `[dependencies]` contains:

```toml
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tauri = { version = "2", features = [] }
tauri-plugin-process = "2.3.1"
tauri-plugin-updater = "2.10.1"
```

- [ ] **Step 3: Generate updater signing keys outside the repository**

Run from the repository root:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.tauri"
npm run tauri -- signer generate -w "$env:USERPROFILE\.tauri\a-stock-receiver.key"
```

Expected:

- The private key is written under `%USERPROFILE%\.tauri`, outside git.
- The command prints a public key.
- Do not add the private key or password to the repo.
- Keep the public key text for Step 5.

- [ ] **Step 4: Register Tauri plugins**

Replace `src-tauri/src/lib.rs` with:

```rust
mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![commands::backend_command])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 5: Configure updater artifacts and GitHub Release endpoint**

Modify `src-tauri/tauri.conf.json`:

- Keep the existing `productName`, `version`, `identifier`, `build`, `app`, and NSIS target.
- Add `"createUpdaterArtifacts": true` inside `"bundle"`.
- Add `"plugins.updater"` with the public key printed in Step 3.
- Use this endpoint exactly: `https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json`.
- Use Windows install mode `"passive"`.

The relevant final shape must match this structure. The `pubkey` value must be the concrete public key from Step 3, not explanatory text:

```json
{
  "bundle": {
    "active": true,
    "useLocalToolsDir": true,
    "targets": ["nsis"],
    "createUpdaterArtifacts": true,
    "resources": []
  },
  "plugins": {
    "updater": {
      "pubkey": "RWQkJpCwD2xvU8lFf3Hc0sTzY7uNnBvM4aPqE6rL9wI=",
      "endpoints": [
        "https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json"
      ],
      "windows": {
        "installMode": "passive"
      }
    }
  }
}
```

The public key shown above is a structural example. Before committing, replace it with the actual public key generated in Step 3 and confirm `src-tauri/tauri.conf.json` no longer contains `RWQkJpCwD2xvU8lFf3Hc0sTzY7uNnBvM4aPqE6rL9wI=`.

- [ ] **Step 6: Add plugin capability permissions**

Create `src-tauri/capabilities/main.json`:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "main-window-capabilities",
  "description": "Allow the main desktop window to run the backtester, check signed updates, install them, and restart after installation.",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "updater:default",
    "process:default"
  ]
}
```

- [ ] **Step 7: Verify Rust dependencies lock cleanly**

Run:

```powershell
npm run tauri -- build --debug --no-bundle
```

Expected: the Rust build reaches the desktop binary build and updates `src-tauri/Cargo.lock` without unresolved dependency or permission errors. If this workspace hits the known MSVC PDB issue, use the documented `CARGO_PROFILE_DEV_DEBUG=0` command from `docs/dev.md`.

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add package.json package-lock.json src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/lib.rs src-tauri/tauri.conf.json src-tauri/capabilities/main.json
git commit -m "feat: configure signed Windows updater"
```

## Task 2: Add Testable Update Client

**Files:**
- Create: `frontend/src/updateClient.ts`
- Test: `frontend/src/components/UpdatePanel.test.tsx`

- [ ] **Step 1: Write failing update client tests through `UpdatePanel`**

Create `frontend/src/components/UpdatePanel.test.tsx` with:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UpdatePanel } from "./UpdatePanel";
import type { AvailableUpdate, UpdateApi } from "../updateClient";

function createApi(overrides: Partial<UpdateApi>): UpdateApi {
  return {
    isRuntime: () => true,
    getVersion: vi.fn().mockResolvedValue("0.1.0"),
    check: vi.fn().mockResolvedValue(null),
    relaunch: vi.fn().mockResolvedValue(undefined),
    ...overrides
  };
}

describe("UpdatePanel", () => {
  it("shows the current version and an up-to-date message", async () => {
    const api = createApi({});
    const user = userEvent.setup();
    render(<UpdatePanel api={api} />);

    expect(await screen.findByText("当前版本 0.1.0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "检查更新" }));

    expect(await screen.findByText("当前已是最新版本")).toBeInTheDocument();
    expect(api.check).toHaveBeenCalledTimes(1);
  });

  it("shows an available update and installs it with relaunch", async () => {
    const progressEvents: Array<(event: Parameters<AvailableUpdate["downloadAndInstall"]>[0] extends (event: infer E) => void ? E : never) => void> = [];
    const update: AvailableUpdate = {
      version: "0.2.0",
      date: "2026-05-24T08:00:00Z",
      body: "新增应用内更新。",
      downloadAndInstall: vi.fn(async (onProgress) => {
        if (onProgress) {
          progressEvents.push(onProgress);
          onProgress({ event: "Started", data: { contentLength: 200 } });
          onProgress({ event: "Progress", data: { chunkLength: 100 } });
          onProgress({ event: "Finished" });
        }
      })
    };
    const api = createApi({ check: vi.fn().mockResolvedValue(update) });
    const user = userEvent.setup();
    render(<UpdatePanel api={api} />);

    await user.click(await screen.findByRole("button", { name: "检查更新" }));

    expect(await screen.findByText("发现新版本 0.2.0")).toBeInTheDocument();
    expect(screen.getByText("新增应用内更新。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "安装并重启" }));

    expect(await screen.findByText("下载进度 50%")).toBeInTheDocument();
    await waitFor(() => expect(update.downloadAndInstall).toHaveBeenCalledTimes(1));
    expect(api.relaunch).toHaveBeenCalledTimes(1);
    expect(progressEvents).toHaveLength(1);
  });

  it("translates signature errors into a Chinese safety message", async () => {
    const api = createApi({ check: vi.fn().mockRejectedValue(new Error("signature mismatch")) });
    const user = userEvent.setup();
    render(<UpdatePanel api={api} />);

    await user.click(await screen.findByRole("button", { name: "检查更新" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("更新文件校验失败");
    expect(screen.queryByText(/signature mismatch/)).not.toBeInTheDocument();
  });

  it("explains that browser preview cannot install updates", async () => {
    const api = createApi({ isRuntime: () => false });
    render(<UpdatePanel api={api} />);

    expect(await screen.findByText("浏览器预览不可安装更新")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "检查更新" })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm run test:ui -- --run frontend/src/components/UpdatePanel.test.tsx
```

Expected: FAIL because `UpdatePanel` and `updateClient` do not exist yet.

- [ ] **Step 3: Create `frontend/src/updateClient.ts`**

Add:

```ts
import { getVersion } from "@tauri-apps/api/app";
import { relaunch } from "@tauri-apps/plugin-process";
import { check } from "@tauri-apps/plugin-updater";

export type InstallEvent =
  | { event: "Started"; data: { contentLength?: number } }
  | { event: "Progress"; data: { chunkLength: number } }
  | { event: "Finished" };

export interface AvailableUpdate {
  version: string;
  date?: string;
  body?: string;
  downloadAndInstall: (onProgress?: (event: InstallEvent) => void) => Promise<void>;
}

export interface UpdateApi {
  isRuntime: () => boolean;
  getVersion: () => Promise<string>;
  check: () => Promise<AvailableUpdate | null>;
  relaunch: () => Promise<void>;
}

export function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

export function translateUpdateError(caught: unknown): string {
  const message = caught instanceof Error ? caught.message : String(caught);
  const lower = message.toLowerCase();

  if (lower.includes("signature") || lower.includes("pubkey") || lower.includes("verify")) {
    return "更新文件校验失败，已阻止安装。请等待重新发布的安装包。";
  }
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("dns") || lower.includes("timeout")) {
    return "更新服务暂时不可用，请检查网络后稍后重试。";
  }
  if (lower.includes("no updater endpoint") || lower.includes("endpoint")) {
    return "更新配置不可用，请安装最新完整安装包后再试。";
  }
  if (lower.includes("install")) {
    return "更新安装失败，请稍后重试或重新下载安装包。";
  }
  return "检查更新失败，请稍后重试。";
}

export function createTauriUpdateApi(): UpdateApi {
  return {
    isRuntime: isTauriRuntime,
    async getVersion() {
      if (!isTauriRuntime()) {
        return "0.1.0";
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
        date: update.date ? String(update.date) : undefined,
        body: update.body ?? undefined,
        downloadAndInstall: async (onProgress) => {
          await update.downloadAndInstall((event) => {
            onProgress?.(event as InstallEvent);
          });
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
```

- [ ] **Step 4: Run test to verify it still fails for missing component only**

Run:

```powershell
npm run test:ui -- --run frontend/src/components/UpdatePanel.test.tsx
```

Expected: FAIL because `UpdatePanel` is not created yet, with no missing `updateClient` error.

## Task 3: Add Chinese Update Panel UI

**Files:**
- Create: `frontend/src/components/UpdatePanel.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/__tests__/strategyEditor.test.tsx`
- Test: `frontend/src/components/UpdatePanel.test.tsx`

- [ ] **Step 1: Create `UpdatePanel`**

Add `frontend/src/components/UpdatePanel.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Download, RefreshCw, ShieldAlert } from "lucide-react";
import { createTauriUpdateApi, translateUpdateError, type AvailableUpdate, type InstallEvent, type UpdateApi } from "../updateClient";

type UpdatePhase = "idle" | "checking" | "available" | "up-to-date" | "installing" | "installed" | "error";

interface UpdatePanelProps {
  api?: UpdateApi;
}

function formatDate(value: string | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function progressLabel(downloadedBytes: number, totalBytes: number): string {
  if (totalBytes <= 0) {
    return "正在下载更新";
  }
  const percent = Math.min(100, Math.round((downloadedBytes / totalBytes) * 100));
  return `下载进度 ${percent}%`;
}

export function UpdatePanel({ api = createTauriUpdateApi() }: UpdatePanelProps) {
  const [currentVersion, setCurrentVersion] = useState("读取中");
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [message, setMessage] = useState("手动检查 GitHub Release 更新");
  const [update, setUpdate] = useState<AvailableUpdate | null>(null);
  const [downloadedBytes, setDownloadedBytes] = useState(0);
  const [totalBytes, setTotalBytes] = useState(0);

  const runtimeAvailable = api.isRuntime();
  const busy = phase === "checking" || phase === "installing";
  const updateDate = useMemo(() => formatDate(update?.date), [update?.date]);

  useEffect(() => {
    let disposed = false;
    void api.getVersion().then((version) => {
      if (!disposed) {
        setCurrentVersion(version);
      }
    });
    if (!runtimeAvailable) {
      setMessage("浏览器预览不可安装更新");
    }
    return () => {
      disposed = true;
    };
  }, [api, runtimeAvailable]);

  const checkForUpdate = async () => {
    if (!runtimeAvailable) {
      return;
    }
    try {
      setPhase("checking");
      setMessage("正在检查更新");
      setUpdate(null);
      setDownloadedBytes(0);
      setTotalBytes(0);
      const nextUpdate = await api.check();
      if (!nextUpdate) {
        setPhase("up-to-date");
        setMessage("当前已是最新版本");
        return;
      }
      setUpdate(nextUpdate);
      setPhase("available");
      setMessage(`发现新版本 ${nextUpdate.version}`);
    } catch (caught) {
      setPhase("error");
      setMessage(translateUpdateError(caught));
    }
  };

  const installUpdate = async () => {
    if (!update) {
      return;
    }
    try {
      setPhase("installing");
      setDownloadedBytes(0);
      setTotalBytes(0);
      setMessage("正在准备下载更新");
      await update.downloadAndInstall((event: InstallEvent) => {
        if (event.event === "Started") {
          setTotalBytes(event.data.contentLength ?? 0);
          setDownloadedBytes(0);
          setMessage("正在下载更新");
        }
        if (event.event === "Progress") {
          setDownloadedBytes((value) => value + event.data.chunkLength);
        }
        if (event.event === "Finished") {
          setMessage("更新已下载，正在安装");
        }
      });
      setPhase("installed");
      setMessage("更新已安装，正在重启");
      await api.relaunch();
    } catch (caught) {
      setPhase("error");
      setMessage(translateUpdateError(caught));
    }
  };

  const statusText = phase === "installing" ? progressLabel(downloadedBytes, totalBytes) : message;

  return (
    <section className="update-panel" aria-label="应用更新">
      <div className="update-panel-main">
        <span className="status-pill compact">
          {phase === "up-to-date" || phase === "installed" ? <CheckCircle2 size={15} aria-hidden="true" /> : <ShieldAlert size={15} aria-hidden="true" />}
          当前版本 {currentVersion}
        </span>
        <p className={phase === "error" ? "update-message error" : "update-message"} role={phase === "error" ? "alert" : "status"}>
          {statusText}
        </p>
        {update && phase !== "installing" ? (
          <div className="update-detail">
            {updateDate ? <span>{updateDate}</span> : null}
            {update.body ? <span>{update.body}</span> : null}
          </div>
        ) : null}
      </div>
      <div className="update-actions">
        {phase === "available" ? (
          <button type="button" className="primary-button" onClick={installUpdate}>
            <Download size={16} aria-hidden="true" /> 安装并重启
          </button>
        ) : (
          <button type="button" className="secondary-button" onClick={checkForUpdate} disabled={busy || !runtimeAvailable}>
            <RefreshCw size={16} aria-hidden="true" /> 检查更新
          </button>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Add update panel to the topbar**

Modify `frontend/src/App.tsx`:

```tsx
import { UpdatePanel } from "./components/UpdatePanel";
```

Then replace the existing `topbar-actions` content:

```tsx
<div className="topbar-actions" aria-label="运行状态">
  <UpdatePanel />
  <span className="status-pill"><Activity size={16} aria-hidden="true" /> 保守日线撮合</span>
  <span className="status-pill"><Database size={16} aria-hidden="true" /> 本地缓存</span>
</div>
```

- [ ] **Step 3: Style update panel**

Append to `frontend/src/styles.css` near the existing topbar styles:

```css
.update-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto;
  gap: 10px;
  align-items: center;
  min-width: 360px;
  max-width: 520px;
  border: 1px solid #d6e2ea;
  border-radius: 8px;
  background: #fbfcfe;
  padding: 10px;
}

.update-panel-main {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.update-actions {
  display: flex;
  justify-content: flex-end;
}

.update-message {
  margin: 0;
  color: #536174;
  font-size: 12px;
  line-height: 1.35;
}

.update-message.error {
  color: #9a3412;
  font-weight: 700;
}

.update-detail {
  display: grid;
  gap: 3px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
}
```

Inside the existing `@media (max-width: 760px)` block, add:

```css
  .topbar-actions,
  .update-panel {
    width: 100%;
  }

  .update-panel {
    grid-template-columns: minmax(0, 1fr);
    min-width: 0;
  }

  .update-actions {
    justify-content: flex-start;
  }
```

- [ ] **Step 4: Add App regression assertion**

In `frontend/src/__tests__/strategyEditor.test.tsx`, inside `renders the Chinese workstation areas`, add:

```tsx
expect(screen.getByRole("button", { name: "检查更新" })).toBeInTheDocument();
expect(screen.getByText(/当前版本/)).toBeInTheDocument();
```

- [ ] **Step 5: Run focused UI tests**

Run:

```powershell
npm run test:ui -- --run frontend/src/components/UpdatePanel.test.tsx frontend/src/__tests__/strategyEditor.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add frontend/src/updateClient.ts frontend/src/components/UpdatePanel.tsx frontend/src/components/UpdatePanel.test.tsx frontend/src/App.tsx frontend/src/styles.css frontend/src/__tests__/strategyEditor.test.tsx
git commit -m "feat: add Chinese update checker UI"
```

## Task 4: Document Release And Update Operations

**Files:**
- Create: `docs/release.md`
- Modify: `docs/dev.md`

- [ ] **Step 1: Write release documentation**

Create `docs/release.md`:

```markdown
# Windows Release And Updates

This app uses Tauri updater with GitHub Releases.

## First Updater Migration

Builds before the updater feature cannot update themselves. Users already on those builds must manually install the first updater-enabled NSIS installer once. Later versions can be installed from inside the app with `检查更新`.

## Signing Key

Generate the key pair outside the repository:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.tauri"
npm run tauri -- signer generate -w "$env:USERPROFILE\.tauri\a-stock-receiver.key"
```

Commit only the public key in `src-tauri/tauri.conf.json`.

Never commit:

- `%USERPROFILE%\.tauri\a-stock-receiver.key`
- private key text
- signing key passwords
- GitHub repository secrets

If the private key is lost, existing updater-enabled installs cannot receive new signed updates from the old key. Rotate keys only with an intentional migration release.

## Versioning

Before a release, update all app version fields to the same SemVer value:

- `package.json`
- `src-tauri/Cargo.toml`
- `src-tauri/tauri.conf.json`

Use a tag matching the version, for example `v0.2.0`.

## Build A Signed Windows Release

PowerShell:

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
npm run build
npm run tauri -- build --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

Expected Windows outputs:

- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe`
- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe.sig`

The `.sig` file content must be copied into `latest.json`; the `.sig` path itself is not valid updater metadata.

## GitHub Release Assets

Create a GitHub Release in `dzc-bit/A_stock_receiver` and upload:

- the NSIS setup `.exe`
- `latest.json`

For a static GitHub Release updater endpoint, `latest.json` must be uploaded with this name:

```text
latest.json
```

The app is configured to read:

```text
https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json
```

## `latest.json` Shape

Use PowerShell to create `latest.json` so the version, URL, and signature come from concrete release values:

```powershell
$version = "0.2.0"
$tag = "v$version"
$assetName = "A股策略回测工作台_0.2.0_x64-setup.exe"
$signature = (Get-Content -Raw "src-tauri\target\release\bundle\nsis\$assetName.sig").Trim()
$latest = @{
  version = $version
  notes = "新增应用内更新。"
  pub_date = "2026-05-24T08:00:00Z"
  platforms = @{
    "windows-x86_64" = @{
      signature = $signature
      url = "https://github.com/dzc-bit/A_stock_receiver/releases/download/$tag/$assetName"
    }
  }
}
$latestJson = $latest | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText((Resolve-Path ".\latest.json"), $latestJson, [System.Text.UTF8Encoding]::new($false))
```

Do not include platform entries for macOS or Linux until those release assets are valid. Tauri validates the whole static JSON before comparing versions.

## Installed User Flow

1. User opens the Windows app.
2. User clicks `检查更新`.
3. If `latest.json` has a greater version and a valid signature, the app shows `发现新版本`.
4. User clicks `安装并重启`.
5. Tauri downloads the signed NSIS installer, verifies the signature, installs, and relaunches the app.
```

- [ ] **Step 2: Link release docs from development docs**

Append to `docs/dev.md`:

```markdown
## Release And Updates

Windows update signing, release asset requirements, and installed-user update flow are documented in `docs/release.md`.
```

- [ ] **Step 3: Commit Task 4**

Run:

```powershell
git add docs/release.md docs/dev.md
git commit -m "docs: document Windows update releases"
```

## Task 5: Full Verification And Push

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run backend regression tests**

Run:

```powershell
pytest tests -q
```

Expected: all backend tests pass. If this workspace lacks `python` on PATH, use the bundled Python command from `docs/dev.md`.

- [ ] **Step 2: Run all UI tests**

Run:

```powershell
npm run test:ui -- --run
```

Expected: all Vitest tests pass, including `UpdatePanel.test.tsx`.

- [ ] **Step 3: Run frontend production build**

Run:

```powershell
npm run build
```

Expected: Vite build succeeds. Existing chunk-size warnings are acceptable if there are no errors.

- [ ] **Step 4: Run Tauri debug installer build**

Run:

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
npm run tauri -- build --debug --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

Expected:

- The NSIS debug installer still builds.
- The NSIS `.sig` file is generated next to the setup `.exe`.
- No updater permission or missing public key errors occur.

If this Codex workspace hits the known MSVC PDB write issue, use the `CARGO_PROFILE_DEV_DEBUG=0` command documented in `docs/dev.md`.

- [ ] **Step 5: Inspect git status**

Run:

```powershell
git status --short --branch
```

Expected: only intended files are changed before the final commit; after final commit the branch is clean.

- [ ] **Step 6: Final commit if verification required changes**

If Task 5 produced fixes after previous task commits, run:

```powershell
git add package.json package-lock.json src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/lib.rs src-tauri/tauri.conf.json src-tauri/capabilities/main.json frontend/src/updateClient.ts frontend/src/components/UpdatePanel.tsx frontend/src/components/UpdatePanel.test.tsx frontend/src/App.tsx frontend/src/styles.css frontend/src/__tests__/strategyEditor.test.tsx docs/release.md docs/dev.md
git commit -m "fix: verify Windows updater integration"
```

Skip this commit if the working tree is already clean.

- [ ] **Step 7: Push branch**

Run:

```powershell
git push origin codex/a-stock-backtester
```

Expected: push succeeds to `dzc-bit/A_stock_receiver`.

## Implementation Notes

- Use `apply_patch` for manual file edits.
- Do not commit private signing keys or generated installers.
- `src-tauri/target/`, `dist/`, `.tools/`, and `node_modules/` remain ignored.
- Real cross-version update validation requires two signed GitHub Releases. Local verification can prove the app builds, the updater is configured, and signed update artifacts are generated, but cannot prove a newer release downloads until a newer `latest.json` exists on GitHub.
