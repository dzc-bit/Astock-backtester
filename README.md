# A股策略回测工作台

一个面向 A 股历史数据的 Windows 桌面回测工具。目标是把 `a-stock-data` 数据包中的日线、流通市值、资金流向、换手率等字段接入本地缓存，让用户自己选择 MACD、量比、换手率、前期涨幅、形态、市值、主力资金流入、市场热度等条件，再回滚历史查看策略预期收益。

## 当前能力

- Windows 桌面壳：Tauri + React + Python 后端。
- 中文工作台界面：数据中心、策略条件、回测设置、收益概览、交易明细。
- 常见 A 股条件库：市场热度、流通市值、近 N 日主力净流入、MACD、均线、量比、换手率、前期涨幅、突破前高。
- 历史回测结果：总收益、最大回撤、胜率、交易次数、权益曲线、买入原因。
- 数据健康提示：展示本地缓存覆盖范围、缺失行和资金流向数据状态。

## 安装方式

### 普通用户（Windows）

1. 打开 [Releases](https://github.com/dzc-bit/A_stock_receiver/releases) 页面。
2. 下载最新版本里的 `A股策略回测工作台_*_x64-setup.exe` 安装包。
3. 双击安装包并按提示安装。
4. 安装完成后打开 `A股策略回测工作台`。

如果 Windows SmartScreen 提示未知发布者，请确认安装包来自本仓库 Releases 页面后，再选择继续运行。当前更新包使用 Tauri updater 签名校验，但 Windows 安装包本身还没有配置商业代码签名证书。

已经安装过旧版的用户，如果旧版没有“检查更新”入口，需要先手动安装一次最新安装包。之后可以在应用内点击“检查更新”完成后续升级。

### 开发者从源码运行

普通 Windows 开发环境需要先安装：

- Node.js LTS
- Python 3.10+
- Rust 和 `x86_64-pc-windows-msvc` 工具链
- Visual Studio Build Tools 2022 C++ 工作负载

然后执行：

```powershell
git clone https://github.com/dzc-bit/A_stock_receiver.git
cd A_stock_receiver
python -m pip install -e ".[dev]"
npm install
npm run test:ui -- --run
python -m pytest tests -q
npm run tauri -- build --debug
```

调试安装包会生成在：

```text
src-tauri\target\debug\bundle\nsis\
```

## 数据说明

当前版本专注本地历史回测，不模拟实时行情。`a-stock-data` 的具体抓取函数仍通过适配器边界接入，回测引擎读取本地缓存中的历史数据。参考 `docs/dev.md` 查看导入、测试和打包命令。

## 开发运行

```powershell
npm install
npm run test:ui -- --run
npm run build
python -m pytest tests -q
npm run tauri -- build --debug
```

普通 Windows 开发环境需要安装 Node.js LTS、Rust/MSVC 工具链和 Python 依赖。Codex 工作区里的特殊运行方式记录在 `docs/dev.md`。
