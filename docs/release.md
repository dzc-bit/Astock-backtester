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
v1.1.0
```

## Release Order

1. Bump `package.json`, `pyproject.toml`, `src-tauri/Cargo.toml`, and `src-tauri/tauri.conf.json` to the same version.
2. Build the sidecar with `scripts/build-data-service.ps1`.
3. Build the signed NSIS installer.
4. Confirm the installer contains the latest `src-tauri\bin\astock-data-service.exe`; for a same-version local reinstall, also verify the installed `bin\astock-data-service.exe` was actually overwritten.
5. Generate `release-assets/latest.json` with `scripts/write-latest-json.ps1` from the real `.sig`.
6. Create the GitHub Release and upload the installer plus `latest.json`.
7. Verify `https://github.com/dzc-bit/Astock-backtester/releases/latest/download/latest.json` returns the new version.

`latest.json` must be generated from the real `.sig` file produced next to the installer. Do not hand-edit a future version into `release-assets/latest.json` before the installer and signature exist, because the app updater verifies that signature.

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

## GitHub Release 资产

在 `dzc-bit/Astock-backtester` 创建 GitHub Release，并上传：

- NSIS 安装包 `.exe`
- `latest.json`

`latest.json` 必须以这个文件名上传，因为应用配置固定读取 `releases/latest/download/latest.json`。
安装包上传到 GitHub Release 时使用 ASCII 资产名，例如 `Astock-backtester_1.1.0_x64-setup.exe`；
`latest.json.platforms.windows-x86_64.url` 必须指向这个真实资产名。保留本地中文安装包文件名可以用于归档，但不要让 updater 指向 GitHub 自动转写后的乱码资产名。

## latest.json

用发布版本、安装包 URL 和签名内容生成 `latest.json`：

```powershell
$assetName = "A股策略回测工作台_1.1.0_x64-setup.exe"
$releaseAssetName = "Astock-backtester_1.1.0_x64-setup.exe"
powershell -ExecutionPolicy Bypass -File scripts/write-latest-json.ps1 `
  -Version "1.1.0" `
  -AssetName $assetName `
  -ReleaseAssetName $releaseAssetName `
  -Notes "发布行情无感刷新、复盘/早盘全文、策略命中展示、回测口径校准与桌面更新增强。"
```

不要提前加入 macOS 或 Linux 平台字段。静态 JSON 会被 updater 整体解析，只有真实可用的平台资产才应该写入。

## 用户更新流程

1. 用户打开 Windows 桌面应用。
2. 点击“检查更新”。
3. 如果 `latest.json` 版本更高，并且签名有效，应用显示“发现新版本”。
4. 用户点击“安装并重启”。
5. Tauri 下载安装包、校验签名、安装并重启应用。

真实跨版本验证需要至少两个已经发布的签名版本。本地验证只能证明构建、签名产物和应用内更新入口可用。
