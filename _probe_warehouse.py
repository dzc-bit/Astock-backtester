# -*- coding: utf-8 -*-
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

warehouse = Path("D:/New project 6/运行产物/本地数据仓/warehouse/daily_bars")

path_2026 = warehouse / "year=2026" / "daily_bars.parquet"
pf = pq.ParquetFile(str(path_2026))
print("Schema:", pf.schema_arrow.names)

df = pd.read_parquet(str(path_2026), columns=["symbol", "trade_date", "open", "high", "low", "close"])
print("Shape:", df.shape)
print("Unique symbols:", df["symbol"].nunique())
print("Date range:", df["trade_date"].min(), "to", df["trade_date"].max())
print("OHLC nulls:", df[["open", "high", "low", "close"]].isna().sum().to_dict())

total_symbols = set()
for p in sorted(warehouse.glob("year=*/daily_bars.parquet")):
    sub = pd.read_parquet(str(p), columns=["symbol"])
    syms = set(sub["symbol"].astype(str).unique())
    total_symbols.update(syms)
    print(f"{p.parent.name}: {len(syms)} symbols")

print(f"\nTotal unique symbols across all partitions: {len(total_symbols)}")
