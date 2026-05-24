# A股策略回测工作台

一个面向 A 股历史数据的 Windows 桌面回测工具。目标是把 `a-stock-data` 数据包中的日线、流通市值、资金流向、换手率等字段接入本地缓存，让用户自己选择 MACD、量比、换手率、前期涨幅、形态、市值、主力资金流入、市场热度等条件，再回滚历史查看策略预期收益。

## 当前能力

- Windows 桌面壳：Tauri + React + Python 后端。
- 中文工作台界面：数据中心、策略条件、回测设置、收益概览、交易明细。
- 常见 A 股条件库：市场热度、流通市值、近 N 日主力净流入、MACD、均线、量比、换手率、前期涨幅、突破前高。
- 历史回测结果：总收益、最大回撤、胜率、交易次数、权益曲线、买入原因。
- 数据健康提示：展示本地缓存覆盖范围、缺失行和资金流向数据状态。

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
