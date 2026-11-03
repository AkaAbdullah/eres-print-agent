"""The agent's own resource use (CPU and memory), sent to ERES with the
heartbeat so Settings > Printers can chart it. Standard library only, no
psutil: os.times() for CPU and one cheap OS call for memory.

CPU is reported like Activity Monitor / Task Manager do: percent of one CPU
core, averaged since the previous sample, including the short-lived helpers
the agent runs (lpstat, lp, SumatraPDF).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional, Tuple


def _cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def memory_mb() -> Optional[float]:
    """Current memory (resident set / working set) of this process, in MB."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            # Types declared explicitly: left to ctypes' defaults, the 64-bit
            # process handle is passed as a 32-bit int and the call fails.
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetCurrentProcess.argtypes = []
            # K32GetProcessMemoryInfo lives in kernel32 itself (Windows 7+),
            # so there's no dependency on psapi.dll.
            get_info = kernel32.K32GetProcessMemoryInfo
            get_info.restype = wintypes.BOOL
            get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            if not get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return None
            return counters.WorkingSetSize / (1024 * 1024)
        if os.path.exists("/proc/self/statm"):
            with open("/proc/self/statm") as handle:
                pages = int(handle.read().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        # macOS: `ps` reports the live RSS in KB (getrusage only has the peak).
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, timeout=5, check=False
        )
        return int(result.stdout.strip()) / 1024 if result.returncode == 0 and result.stdout.strip() else None
    except Exception:
        return None


class UsageSampler:
    """Call sample() periodically; each call returns CPU since the last one."""

    def __init__(self) -> None:
        self._last: Tuple[float, float] = (time.monotonic(), _cpu_seconds())

    def sample(self) -> Tuple[Optional[float], Optional[float]]:
        """(cpu percent of one core, memory MB); None for what can't be read."""
        now, cpu = time.monotonic(), _cpu_seconds()
        last_wall, last_cpu = self._last
        self._last = (now, cpu)
        elapsed = now - last_wall
        cpu_percent = max(0.0, (cpu - last_cpu) / elapsed * 100) if elapsed > 0 else None
        memory = memory_mb()
        return (
            round(cpu_percent, 2) if cpu_percent is not None else None,
            round(memory, 1) if memory is not None else None,
        )
