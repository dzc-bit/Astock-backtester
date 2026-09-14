"""跨进程文件锁 —— 数据仓写入互斥的最小实现。

为什么需要：`Warehouse.write_daily_bars` 是 read-modify-write + 整文件覆盖。
桌面端 sidecar 与外部补齐脚本同时运行时，两方交错的「读 → 合 → 写」会
**丢失更新**（后写者覆盖先写者）并可能产生 **撕裂写**（一方读到另一方
写到一半的文件 → parquet footer 与数据块不匹配 → 分区损坏）。

`threading.Lock` 只在单进程内有效，因此这里用操作系统级文件锁：
- Windows：`msvcrt.locking`（锁 1 字节区域）
- POSIX：`fcntl.flock`

锁的持有者是**文件描述符**，进程崩溃时由 OS 自动释放，不会留下死锁。
"""

from __future__ import annotations

import errno
import os
import time
from pathlib import Path
from types import TracebackType

if os.name == "nt":  # pragma: no cover - platform specific
    import msvcrt
else:  # pragma: no cover - platform specific
    import fcntl

DEFAULT_LOCK_TIMEOUT_SECONDS = 120.0
DEFAULT_LOCK_POLL_SECONDS = 0.1


class FileLockTimeout(RuntimeError):
    """在超时时间内未能取得跨进程文件锁。"""

    def __init__(self, path: str, timeout: float) -> None:
        super().__init__(f"等待数据仓写入锁超时（{timeout:g}s）：{path}")
        self.path = path
        self.timeout = timeout


def _try_lock_file(handle) -> bool:
    """非阻塞尝试加锁，成功返回 True，被占用返回 False。"""
    try:
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return False
        # Windows 的 msvcrt 在竞争时抛的是 EDEADLOCK/其他 errno，按占用处理。
        if os.name == "nt":
            return False
        raise
    return True


def _unlock_file(handle) -> None:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:  # pragma: no cover - 释放失败时文件即将关闭，由 OS 兜底
        pass


class CrossProcessFileLock:
    """基于 ``<target>.lock`` 哨兵文件的跨进程互斥锁。

    用法::

        with CrossProcessFileLock(partition_path):
            ...  # 读 → 合 → 写

    锁文件单独存在（不锁数据文件本身），因为数据文件的写入是
    "临时文件 + 原子替换"，inode 会更换，锁在旧 inode 上会失效。
    """

    def __init__(
        self,
        target: Path,
        *,
        timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        poll_seconds: float = DEFAULT_LOCK_POLL_SECONDS,
    ) -> None:
        self.target = Path(target)
        self.lock_path = self.target.with_name(f"{self.target.name}.lock")
        self.timeout = timeout
        self.poll_seconds = poll_seconds
        self._handle = None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")  # noqa: SIM115 - 生命周期由 acquire/release 管理
        try:
            deadline = time.monotonic() + self.timeout
            while True:
                if _try_lock_file(handle):
                    self._handle = handle
                    return
                if time.monotonic() >= deadline:
                    raise FileLockTimeout(str(self.lock_path), self.timeout)
                time.sleep(self.poll_seconds)
        except BaseException:
            handle.close()
            raise

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock_file(handle)
        finally:
            handle.close()

    def __enter__(self) -> CrossProcessFileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
