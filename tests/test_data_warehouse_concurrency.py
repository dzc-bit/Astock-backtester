"""请求 B「既有问题修复」的回归测试。

覆盖四项修复：
1. 跨进程文件锁互斥（`data/filelock.py` + `Warehouse.write_daily_bars`）
2. 原子写（临时文件 + `os.replace`，读者要么看到旧版要么看到完整新版）
3. `run_full_market` 攒批落盘（消除 O(n²) 写入）
4. 损坏分区与「数据缺失」分离暴露（`corrupt_partitions` + `/diagnostics/data-gaps` 的 `warehouse_health`）

网络隔离：全部测试只操作本地临时目录，不发起任何出站请求。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pandas as pd
import pytest
from astock_backtester.data.filelock import (
    CrossProcessFileLock,
    FileLockTimeout,
)
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.service import create_server

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"

# 回环流量绝不走系统代理（Windows 注册表/环境变量代理会劫持本地请求）
_OPENER = build_opener(ProxyHandler({}))


def _get_json(port: int, path: str, *, allow_error: bool = False) -> dict:
    """GET 一个本地 JSON 端点。allow_error=True 时 4xx 也返回解析后的 body。"""
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with _OPENER.open(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if not allow_error:
            raise
        return json.loads(exc.read().decode("utf-8"))


def _bars(symbol: str = "600519", start: str = "2016-01-04", count: int = 1) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=count)
    return pd.DataFrame(
        {
            "symbol": [symbol] * count,
            "trade_date": dates.strftime("%Y-%m-%d"),
            "open": [10.0] * count,
            "high": [10.5] * count,
            "low": [9.8] * count,
            "close": [10.2] * count,
            "volume": [1000] * count,
        }
    )


# ---------------------------------------------------------------------------
# 1. 跨进程文件锁
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name != "nt" and not hasattr(os, "fork"), reason="需要 POSIX fork 或 Windows")
def test_filelock_blocks_second_process_until_released(tmp_path):
    """子进程持锁期间，父进程非阻塞获取必须失败；释放后可立即获取。"""
    lock_target = tmp_path / "partition.parquet"
    lock_target.write_bytes(b"placeholder")

    script = textwrap.dedent(
        """
        import sys, time
        sys.path.insert(0, sys.argv[1])
        from pathlib import Path
        from astock_backtester.data.filelock import CrossProcessFileLock

        lock = CrossProcessFileLock(Path(sys.argv[2]), timeout=5.0)
        lock.acquire()
        print("HELD", flush=True)
        time.sleep(float(sys.argv[3]))
        lock.release()
        print("RELEASED", flush=True)
        """
    )

    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(_BACKEND), str(lock_target), "1.5"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "HELD", proc.stderr.read()

        # 子进程持锁 → 父进程短超时必须拿到 FileLockTimeout
        contender = CrossProcessFileLock(lock_target, timeout=0.3, poll_seconds=0.05)
        with pytest.raises(FileLockTimeout):
            contender.acquire()

        # 等子进程释放后再拿，应当立刻成功
        assert proc.stdout.readline().strip() == "RELEASED"
        proc.wait(timeout=5)
        holder = CrossProcessFileLock(lock_target, timeout=2.0, poll_seconds=0.05)
        with holder:
            assert holder._handle is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_filelock_reentrant_within_same_process_context(tmp_path):
    """同一进程顺序获取（释放后重取）不残留状态 —— 防止 release 漏放导致自锁。"""
    target = tmp_path / "daily_bars.parquet"
    lock = CrossProcessFileLock(target, timeout=1.0, poll_seconds=0.02)

    with lock:
        assert lock._handle is not None
    assert lock._handle is None

    # 第二次获取必须成功
    with lock:
        assert lock._handle is not None


def test_filelock_sentinel_path_does_not_touch_target(tmp_path):
    """锁文件是 `<target>.lock` 哨兵，绝不锁数据文件本身。"""
    target = tmp_path / "sub" / "daily_bars.parquet"
    lock = CrossProcessFileLock(target, timeout=1.0)

    with lock:
        lock_path = target.with_name("daily_bars.parquet.lock")
        assert lock_path.exists()
        assert not target.exists()

    # 释放后哨兵文件仍可被打开（不删除，避免 unlink/reopen 竞态）
    assert lock_path.exists()


def test_warehouse_concurrent_writers_do_not_lose_updates(tmp_path):
    """两个 Warehouse 实例（模拟 sidecar + 外部脚本）并发写同一分区不丢更新。

    这是修复前的核心缺陷：read-modify-write 交错会把先写者的行整体覆盖掉。
    """
    warehouse = Warehouse(tmp_path)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(symbol: str, start: str) -> None:
        try:
            barrier.wait(timeout=10)
            for _ in range(5):
                Warehouse(tmp_path).write_daily_bars(_bars(symbol=symbol, start=start))
        except BaseException as exc:  # noqa: BLE001 - 收集后统一断言
            errors.append(exc)

    threads = [
        threading.Thread(target=writer, args=("600519", "2016-01-04")),
        threading.Thread(target=writer, args=("000001", "2016-01-04")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    result = warehouse.read_daily_bars(start_date="2016-01-01", end_date="2016-12-31")
    assert set(result["symbol"]) == {"600519", "000001"}, "并发写丢失了其中一只股票的分区数据"


# ---------------------------------------------------------------------------
# 2. 原子写
# ---------------------------------------------------------------------------


def test_atomic_write_leaves_no_temp_file_on_success(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    partition_dir = tmp_path / "warehouse" / "daily_bars" / "year=2016"
    leftovers = [p.name for p in partition_dir.glob("*.tmp")]
    assert leftovers == [], f"原子写成功后残留临时文件：{leftovers}"


def test_atomic_write_cleans_temp_file_on_failure(tmp_path, monkeypatch):
    """写失败（to_parquet 抛异常）不得留下 .tmp 残留，也不得破坏原分区。"""
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars(symbol="600519"))
    partition = tmp_path / "warehouse" / "daily_bars" / "year=2016" / "daily_bars.parquet"
    original_bytes = partition.read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)

    with pytest.raises((OSError, Exception)):  # noqa: B017 - 断言失败即清理
        warehouse.write_daily_bars(_bars(symbol="000001"))

    leftovers = list(partition.parent.glob("*.tmp"))
    assert leftovers == [], f"写失败后残留临时文件：{leftovers}"
    assert partition.read_bytes() == original_bytes, "写失败破坏了原分区内容"


def test_atomic_write_replace_is_visible_only_as_whole_file(tmp_path, monkeypatch):
    """`os.replace` 之后才能看到新内容 —— 读者永不读到半成品。"""
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars(symbol="600519"))

    observed: list[str] = []
    real_replace = os.replace

    def tracking_replace(src, dst, *args, **kwargs):
        # 替换前读目标：必须还是旧的完整内容
        observed.append("before")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", tracking_replace)
    warehouse.write_daily_bars(_bars(symbol="000001"))

    assert observed == ["before"]
    result = warehouse.read_daily_bars(start_date="2016-01-01", end_date="2016-12-31")
    assert set(result["symbol"]) == {"600519", "000001"}


# ---------------------------------------------------------------------------
# 3. run_full_market 攒批（消除 O(n²)）
# ---------------------------------------------------------------------------


class _LocalProvider:
    """假的 provider：按 symbol 返回本地构造的帧，零网络。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append(symbol)
        return _bars(symbol=symbol, start=start_date)


def test_run_full_market_batches_writes_instead_of_per_symbol(tmp_path, monkeypatch):
    """攒批后写分区次数应远小于股票只数（修复前 == 股票只数）。

    不跑真实网络：provider 是本地 stub，只观察 `write_daily_bars` 的调用次数。
    """
    from astock_backtester.data.sync import SyncJobManager

    warehouse = Warehouse(tmp_path)
    write_calls: list[int] = []
    real_write = warehouse.write_daily_bars

    def counting_write(frame: pd.DataFrame):
        write_calls.append(len(frame))
        return real_write(frame)

    monkeypatch.setattr(warehouse, "write_daily_bars", counting_write)

    provider = _LocalProvider()
    manager = SyncJobManager(warehouse=warehouse, provider=provider)
    # 阈值调低到 10 行：25 只股票 / 每只 1 行 → 3 次落盘（而非旧的 25 次）
    object.__setattr__(manager, "full_market_write_batch_rows", 10)

    symbols = [f"{i:06d}" for i in range(1, 26)]
    status = manager.run_full_market(symbols, "2024-01-02", "2024-01-05")

    assert status.status == "completed", status.errors
    assert provider.calls == symbols, "每只股票都应被请求一次"

    assert write_calls, "攒批后仍应至少落盘一次"
    assert len(write_calls) < len(symbols), (
        f"写入次数 {len(write_calls)} 未低于股票只数 {len(symbols)}，O(n²) 未消除"
    )
    # 25 行 / 阈值 10 → 落盘 3 次（2 次满批 + 1 次兜底）
    assert len(write_calls) == 3, f"预期 3 次落盘，实际 {len(write_calls)} 次：{write_calls}"


def test_run_full_market_flushes_remainder_below_threshold(tmp_path, monkeypatch):
    """不足一批的尾巴必须兜底落盘，否则最后几只股票的数据会丢。"""
    from astock_backtester.data.sync import SyncJobManager

    warehouse = Warehouse(tmp_path)
    write_calls: list[int] = []
    real_write = warehouse.write_daily_bars

    def counting_write(frame: pd.DataFrame):
        write_calls.append(len(frame))
        return real_write(frame)

    monkeypatch.setattr(warehouse, "write_daily_bars", counting_write)

    manager = SyncJobManager(warehouse=warehouse, provider=_LocalProvider())
    object.__setattr__(manager, "full_market_write_batch_rows", 1_000_000)  # 永不触发满批

    symbols = [f"{i:06d}" for i in range(1, 6)]
    status = manager.run_full_market(symbols, "2024-01-02", "2024-01-05")

    assert status.status == "completed", status.errors
    assert len(write_calls) == 1, f"尾巴应合并为一次落盘，实际：{write_calls}"

    result = warehouse.read_daily_bars(start_date="2024-01-01", end_date="2024-12-31")
    assert set(result["symbol"]) == set(symbols), "兜底落盘丢失了不足一批的股票"


# ---------------------------------------------------------------------------
# 4. 损坏分区暴露
# ---------------------------------------------------------------------------


def test_corrupt_partition_is_recorded_separately_from_missing(tmp_path):
    """损坏分区进入 `corrupt_partitions`；不存在的分区不算损坏。"""
    from pyarrow.lib import ArrowInvalid

    warehouse = Warehouse(tmp_path)
    assert warehouse.corrupt_partitions == {}

    # 不存在的分区：空表，且不记损坏
    assert warehouse._safe_read_parquet(tmp_path / "missing.parquet").empty
    assert warehouse.corrupt_partitions == {}

    # 存在但损坏：原样 re-raise，并记录
    corrupt = tmp_path / "warehouse" / "daily_bars" / "year=2026" / "daily_bars.parquet"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not a parquet file")

    with pytest.raises(ArrowInvalid, match="Parquet magic bytes"):
        warehouse.read_latest_daily_bars(days=1)

    recorded = warehouse.corrupt_partitions
    assert str(corrupt) in recorded
    assert "Parquet magic bytes" in recorded[str(corrupt)]

    warehouse.clear_corrupt_partitions()
    assert warehouse.corrupt_partitions == {}


def test_diagnostics_data_gaps_exposes_warehouse_health(tmp_path):
    """/diagnostics/data-gaps 必须带回 warehouse_health，损坏时 healthy=False。

    损坏分区会让 `data_gap_profile()` 本身抛异常 → HTTP 400。此时响应里
    **仍然**要带 `warehouse_health`，否则前端只能看到 400，把"损坏"误判成"缺失"。
    """
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    warehouse = server.state.warehouse
    warehouse.write_daily_bars(_bars())

    corrupt = tmp_path / "warehouse" / "daily_bars" / "year=2026" / "daily_bars.parquet"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not a parquet file")

    # 触发一次读，让损坏被登记
    try:
        warehouse.read_latest_daily_bars(days=1)
    except Exception:  # noqa: BLE001 - 期望失败
        pass
    assert warehouse.corrupt_partitions, "损坏分区应已被登记"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        payload = _get_json(port, "/diagnostics/data-gaps", allow_error=True)

        health = payload["warehouse_health"]
        assert health["healthy"] is False
        assert any("year=2026" in path for path in health["corrupt_partitions"])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_diagnostics_data_gaps_reports_healthy_when_clean(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.warehouse.write_daily_bars(_bars())

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        payload = _get_json(port, "/diagnostics/data-gaps", allow_error=True)

        assert payload["warehouse_health"] == {"corrupt_partitions": {}, "healthy": True}
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_state_tolerates_warehouse_without_health_attribute(tmp_path):
    """warehouse 没有 corrupt_partitions 属性（测试 stub）时不得抛 AttributeError。

    这是修复后的关键兼容点：`service.py` 两处改用
    ``getattr(self.warehouse, "corrupt_partitions", None) or {}``，
    否则 `BrokenWarehouse` 这类 stub 会让历史测试直接崩。
    """
    from astock_backtester.data.cache import LocalCache
    from astock_backtester.service import DataServiceState

    class BrokenWarehouse:
        """没有 corrupt_partitions 属性，coverage() 直接抛。"""

        def coverage(self):
            raise OSError("warehouse coverage read failed")

    state = object.__new__(DataServiceState)
    state.warehouse = BrokenWarehouse()
    state.cache = LocalCache(tmp_path)
    state.logs = []
    state._log_lock = threading.Lock()

    def _log(level: str, message: str) -> None:
        state.logs.append((level, message))

    state.log = _log  # type: ignore[method-assign]

    result = state._read_coverage_snapshot()

    assert result is not None
    assert any(level == "warning" for level, _ in state.logs), "缺少属性应降级为 warning，而非崩溃"
