# Windows 发布与应用内更新

本项目的 Windows 桌面版使用 Tauri updater 和 GitHub Releases 发布更新。应用内更新入口读取：

```text
https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json
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

## 版本号

发布前把这些版本号保持一致：

- `package.json`
- `src-tauri/Cargo.toml`
- `src-tauri/tauri.conf.json`

Git tag 使用 `v版本号`，例如：

```text
v0.2.0
```

## 构建签名安装包

在 Windows 发布机器上执行：

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
npm run build
npm run tauri -- build
```

预期生成：

- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe`
- `src-tauri\target\release\bundle\nsis\*_x64-setup.exe.sig`

`.sig` 文件的内容要写入 `latest.json`，不是把 `.sig` 文件路径写进去。

## GitHub Release 资产

在 `dzc-bit/A_stock_receiver` 创建 GitHub Release，并上传：

- NSIS 安装包 `.exe`
- `latest.json`

`latest.json` 必须以这个文件名上传，因为应用配置固定读取 `releases/latest/download/latest.json`。

## latest.json

用发布版本、安装包 URL 和签名内容生成 `latest.json`。示例：

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
$latest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 latest.json
```

不要提前加入 macOS 或 Linux 平台字段。静态 JSON 会被 updater 整体解析，只有真实可用的平台资产才应该写入。

## 用户更新流程

1. 用户打开 Windows 桌面应用。
2. 点击“检查更新”。
3. 如果 `latest.json` 版本更高，并且签名有效，应用显示“发现新版本”。
4. 用户点击“安装并重启”。
5. Tauri 下载 NSIS 安装包、校验签名、安装并重启应用。

真实跨版本验证需要至少两个已发布的签名版本。本地验证只能证明构建、签名产物和应用内更新入口可用。
