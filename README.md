# A股策略回测工作台

一个面向 A 股历史数据的 Windows 桌面回测工具。目标是把 `a-stock-data` 风格的数据源接入本地缓存，让用户调整 MACD、量比、换手率、前期涨幅、形态、市值、主力资金流入、市场热度等条件，再回滚历史查看策略预期收益。

## 当前能力

- Windows 桌面壳：Tauri + React + Python 后端。
- 中文工作台界面：数据中心、策略条件、回测设置、收益概览、交易明细。
- 常见 A 股条件库：市场热度、流通市值、近 N 日主力净流入、MACD、均线、量比、换手率、前期涨幅、突破前高。
- 历史回测结果：总收益、最大回撤、胜率、交易次数、权益曲线、买入原因。
- 数据中心：展示本地缓存覆盖范围、缺失行、资金流和市值数据状态。
- 应用会启动本机 `127.0.0.1` 数据服务来补齐缺失历史数据。
- 回测引擎仍然只读取本地缓存，不在回测过程中联网。
- 新版本通过 GitHub Release 发布后，应用内“检查更新”可以检测并安装。

## 安装方式

### 普通用户（Windows）

1. 打开 [Releases](https://github.com/dzc-bit/Astock-backtester/releases) 页面。
2. 下载最新版本里的 `*_x64-setup.exe` 安装包。
3. 双击安装包并按提示安装。
4. 安装完成后打开 `A股策略回测工作台`。

如果 Windows SmartScreen 提示未知发布者，请确认安装包来自本仓库 Releases 页面后，再选择继续运行。当前更新包使用 Tauri updater 签名校验，但 Windows 安装包本身还没有配置商业代码签名证书。

已经安装过旧版的用户，如果旧版没有“检查更新”入口，需要先手动安装一次最新安装包。由于 `v0.1.7` 进行了更新签名密钥迁移，`v0.1.6` 用户这一次也需要手动安装 `v0.1.7` 安装包；从 `v0.1.7` 开始，后续版本可以继续在应用内点击“检查更新”完成升级。

## 数据说明

当前版本专注本地历史回测，不模拟实时行情。数据中心会通过应用托管的本地服务补齐或导入历史数据；回测路径只读本地缓存，避免在策略回放过程中发生网络请求。

`a-stock-data` 的具体抓取函数通过适配器边界接入。开发和发布命令见 `docs/dev.md` 与 `docs/release.md`。

## 开发运行

普通 Windows 开发环境需要先安装：

- Node.js LTS
- Python 3.11+
- Rust 和 `x86_64-pc-windows-msvc` 工具链
- Visual Studio Build Tools 2022 C++ 工作负载

然后执行：

```powershell
git clone https://github.com/dzc-bit/Astock-backtester.git
cd Astock-backtester
python -m pip install -e ".[dev]"
npm install
npm run test:ui -- --run
python -m pytest tests -q
npm run build:data-service
npm run tauri -- build --debug
```

调试安装包会生成在：

```text
src-tauri\target\debug\bundle\nsis\
```

Codex 工作区里的特殊运行方式记录在 `docs/dev.md`。
