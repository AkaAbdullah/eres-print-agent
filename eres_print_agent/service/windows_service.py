"""Windows Service wrapper around core.agent.Agent.

NOT importable on macOS/Linux — pywin32 only exists on Windows. cli.py only
imports this module when a service-management command actually runs, and
only after checking sys.platform == "win32", so the rest of the CLI stays
usable on any OS.

The asyncio agent loop runs on a background thread because
win32serviceutil.ServiceFramework's SvcDoRun must block on a Win32 event,
not an asyncio loop, to receive SCM stop requests promptly.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading

if sys.platform == "win32":
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

from ..config import load_config
from ..constants import SERVICE_DESCRIPTION, SERVICE_DISPLAY_NAME, SERVICE_NAME
from ..core.agent import Agent
from ..credentials import load_agent_secret
from ..logging_setup import configure_logging

logger = logging.getLogger(__name__)


class ERESPrintAgentService(win32serviceutil.ServiceFramework if sys.platform == "win32" else object):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_handle = win32event.CreateEvent(None, 0, 0, None)
        self._agent: Agent | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self._agent is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._agent.stop)
        win32event.SetEvent(self._stop_handle)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )

        configure_logging()
        config = load_config()
        agent_secret = load_agent_secret(config.agentId) if config.agentId else None

        if not config.is_paired or not agent_secret:
            servicemanager.LogErrorMsg(
                "ERES Print Agent is not paired. On this machine, run: "
                "eres-print-agent pair <code from ERES Settings > Printers>"
            )
            # Report started-then-stopped rather than crash-looping — an
            # unpaired install is a normal, expected state right after
            # `install`, before pairing has happened.
            return

        self._agent = Agent(config, agent_secret)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_agent_loop, daemon=True)
        self._thread.start()

        win32event.WaitForSingleObject(self._stop_handle, win32event.INFINITE)
        if self._thread is not None:
            self._thread.join(timeout=15)

    def _run_agent_loop(self) -> None:
        assert self._loop is not None and self._agent is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._agent.run())
        except Exception:
            logger.exception("Agent loop crashed")
            servicemanager.LogErrorMsg("ERES Print Agent crashed — see agent.log for details.")


def _configure_auto_restart() -> None:
    """SCM's own restart-on-crash — `sc create`/pywin32's InstallService
    does not set this by default, so it must be configured explicitly.
    Three restart attempts with a 5s delay, then leave it stopped rather
    than looping forever if something is fundamentally broken (e.g. a
    corrupted config that will fail every time).
    """
    subprocess.run(
        [
            "sc.exe",
            "failure",
            SERVICE_NAME,
            "reset=",
            "86400",
            "actions=",
            "restart/5000/restart/5000/restart/5000",
        ],
        check=True,
    )


def install_service() -> None:
    win32serviceutil.InstallService(
        pythonClassString=f"{__name__}.ERESPrintAgentService",
        serviceName=SERVICE_NAME,
        displayName=SERVICE_DISPLAY_NAME,
        description=SERVICE_DESCRIPTION,
        startType=win32service.SERVICE_AUTO_START,
    )
    _configure_auto_restart()


def uninstall_service() -> None:
    try:
        win32serviceutil.StopService(SERVICE_NAME)
    except Exception:
        pass  # not running — fine
    win32serviceutil.RemoveService(SERVICE_NAME)


def start_service() -> None:
    win32serviceutil.StartService(SERVICE_NAME)


def stop_service() -> None:
    win32serviceutil.StopService(SERVICE_NAME)


def restart_service() -> None:
    win32serviceutil.RestartService(SERVICE_NAME)


def query_service_status() -> str:
    status_code = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
    return {
        win32service.SERVICE_STOPPED: "stopped",
        win32service.SERVICE_START_PENDING: "starting",
        win32service.SERVICE_STOP_PENDING: "stopping",
        win32service.SERVICE_RUNNING: "running",
    }.get(status_code, f"unknown ({status_code})")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ERESPrintAgentService)
