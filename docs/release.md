# Windows 发布与应用内更新

Windows 桌面版使用 Tauri updater 和 GitHub Releases 发布更新。应用内“检查更新”读取：

```text
https://github.com/dzc-bit/Astock-backtester/releases/latest/download/latest.json
```

## 首次迁移

已经安装过旧版本的用户，如果旧版本不包含 updater 插件，就不能自己更新到新版本。必须先手动安装一次“带更新器”的 NSIS 安装包。完成这次迁移后，后续版本可以在应用内点击“检查更新”并安装。

## 签名密钥

更新包必须签名。私钥只保存在发布机器或 GitHub Actions Secret 中，不能进入仓库。

首次生成密钥：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.tauri"
npm run tauri -- signer generate -w "$env:USERPROFILE\.tauri\a-stock-receiver.key"
```

当前本机私钥路径：

```text
%USERPROFILE%\.tauri\a-stock-receiver.key
```

仓库里只能提交公钥，也就是 `src-tauri/tauri.conf.json` 里的 `plugins.updater.pubkey`。

不要提交或打印到日志：

- `%USERPROFILE%\.tauri\a-stock-receiver.key`
- 私钥文本
- 私钥密码
- GitHub repository secrets

如果私钥丢失，已经安装的带更新器版本无法校验新密钥签出的更新包。除非有计划地做一次迁移发布，否则不要轮换密钥。

历史上如果旧私钥不可用，需要做一次计划内迁移发布：旧版用户必须手动安装新的 NSIS 安装包，之后才能重新走应用内更新。除非明确安排迁移，不要轮换更新私钥。

## 版本号

发布前把这些版本号保持一致：

- `package.json`
- `pyproject.toml`
- `src-tauri/Cargo.toml`
- `src-tauri/tauri.conf.json`

Git tag 使用 `v版本号`，例如：

```text
v1.1.1
```

## Release Order

1. Bump `package.json`, `pyproject.toml`, `src-tauri/Cargo.toml`, and `src-tauri/tauri.conf.json` to the same version.
2. Build the sidecar with `scripts/build-data-service.ps1`.
3. Build the signed NSIS installer.
4. Confirm the installer contains the latest `src-tauri\bin\astock-data-service.exe`; for a same-version local reinstall, also verify the installed `bin\astock-data-service.exe` was actually overwritten by comparing hashes.
5. Generate a fresh `latest.json` with `scripts/write-latest-json.ps1` from the real `.sig`.
6. Create the GitHub Release and upload the installer plus the freshly generated `latest.json`.
7. Verify `https://github.com/dzc-bit/Astock-backtester/releases/latest/download/latest.json` returns the new version.

`latest.json` must be generated from the real `.sig` file produced next to the installer. Do not hand-edit a future version into `release-assets/latest.json` before the installer and signature exist, because the app updater verifies that signature. The `release-assets` directory is ignored by Git; treat files there as local staging artifacts and upload the verified `latest.json` to the GitHub Release instead of keeping stale updater manifests in the repository.

If `npm run tauri -- build --ci` creates the NSIS `.exe` but exits with `A public key has been found, but no private key`, the local installer can be used for manual installation checks only. Do not upload that installer as an updater release, do not reuse an older `.sig`, and do not regenerate `latest.json` until `TAURI_SIGNING_PRIVATE_KEY` is available and the matching `.sig` is produced by the same build.

## Build The Local Data Service Sidecar

Before a release build, create the Windows service executable:

```powershell
python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1
```

Expected output:

- `src-tauri\bin\astock-data-service.exe`

## 构建签名安装包

在 Windows 发布机器上执行：

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
npm run build:data-service
npm run build
npm run tauri -- build --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

预期生成：

- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe`
- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe.sig`

`.sig` 文件的内容要写入 `latest.json`，不是把 `.sig` 文件路径写进去。
如果本机没有 `%USERPROFILE%\.tauri\a-stock-receiver.key` 或对应环境变量，Tauri 仍可能先生成 `.exe`，但会在 updater 签名阶段失败。此时应记录为“安装包构建完成、签名发布阻塞”，而不是把旧 `.sig` 或旧 `latest.json` 当成本次发布资产。

## 安装后 sidecar 验证

安装包退出码为 0 不代表 sidecar 已替换。覆盖安装后先停止旧桌面进程和旧数据服务，再比较工作区与安装目录 sidecar 的 SHA256：

```powershell
Get-Process | Where-Object { $_.Path -like '*A股策略回测工作台*' -or $_.ProcessName -like '*astock*' -or $_.ProcessName -like '*a-stock*' } | Stop-Process -Force
Get-FileHash "$env:LOCALAPPDATA\A股策略回测工作台\bin\astock-data-service.exe"
Get-FileHash "D:\New project 6\src-tauri\bin\astock-data-service.exe"
```

临时探针启动 sidecar 时，`D:\New project 6\运行产物\本地数据仓` 包含空格和中文。PowerShell `Start-Process -ArgumentList @(..., $cacheDir)` 容易拆参；应使用已加引号的单个参数字符串，或用 Python `subprocess.Popen([...])` 参数数组。

安装后至少探测 `/ping`、`/health`、`/coverage/daily-bars`、`/realtime/market-snapshot`、`/market/commentary`、`/market/fupan`、`/market/zaopan` 和 `/run/backtest/stream`。`/run/backtest/stream` 是 NDJSON 流，探针应逐行 `json.loads`，并断言最后一个事件为 `{"type":"result", ...}`，不能用 `Invoke-RestMethod` 当普通 JSON 判断。

## GitHub Release 资产

在 `dzc-bit/Astock-backtester` 创建 GitHub Release，并上传：

- NSIS 安装包 `.exe`
- `latest.json`

`latest.json` 必须以这个文件名上传，因为应用配置固定读取 `releases/latest/download/latest.json`。
安装包上传到 GitHub Release 时使用 ASCII 资产名，例如 `Astock-backtester_1.1.1_x64-setup.exe`；
`latest.json.platforms.windows-x86_64.url` 必须指向这个真实资产名。保留本地中文安装包文件名可以用于归档，但不要让 updater 指向 GitHub 自动转写后的乱码资产名。

## latest.json

用发布版本、安装包 URL 和签名内容生成 `latest.json`：

```powershell
$assetName = "A股策略回测工作台_1.1.1_x64-setup.exe"
$releaseAssetName = "Astock-backtester_1.1.1_x64-setup.exe"
powershell -ExecutionPolicy Bypass -File scripts/write-latest-json.ps1 `
  -Version "1.1.1" `
  -AssetName $assetName `
  -ReleaseAssetName $releaseAssetName `
  -Notes "发布实时行情完整性校验、行情评价严格降级、复盘候选分离、A 股交易日历覆盖和安装后 sidecar 验证增强。"
```

不要提前加入 macOS 或 Linux 平台字段。静态 JSON 会被 updater 整体解析，只有真实可用的平台资产才应该写入。

## 用户更新流程

1. 用户打开 Windows 桌面应用。
2. 点击“检查更新”。
3. 如果 `latest.json` 版本更高，并且签名有效，应用显示“发现新版本”。
4. 用户点击“安装并重启”。
5. Tauri 下载安装包、校验签名、安装并重启应用。

真实跨版本验证需要至少两个已经发布的签名版本。本地验证只能证明构建、签名产物和应用内更新入口可用。
