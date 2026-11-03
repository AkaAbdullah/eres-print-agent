#!/bin/bash
# Turn the ERES Print Agent background service on/off on a Mac.
#
#   ./mac_service.sh status    is it running? memory / CPU
#   ./mac_service.sh stop      stop it now (starts again at next login)
#   ./mac_service.sh start     start it again
#   ./mac_service.sh restart   stop + start
#   ./mac_service.sh disable   stop it AND keep it off after restart/login
#   ./mac_service.sh enable    undo disable and start it
#
# A plain `kill` doesn't work: launchd's KeepAlive restarts the agent
# straight away. This uses launchctl, which is what the agent's own
# `eres-print-agent stop` does. No sudo needed.

LABEL="cloud.eres.printagent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TARGET="gui/$(id -u)/$LABEL"
DOMAIN="gui/$(id -u)"

loaded() { launchctl print "$TARGET" >/dev/null 2>&1; }

show_status() {
  if [ ! -f "$PLIST" ]; then
    echo "Not installed (no $PLIST)."
    return
  fi
  if launchctl print-disabled "$DOMAIN" 2>/dev/null | grep -q "\"$LABEL\" => disabled"; then
    echo "Disabled: won't start at login (run: $0 enable)."
  fi
  if loaded; then
    echo "Service: loaded"
  else
    echo "Service: stopped"
  fi
  local pids
  pids=$(pgrep -f "ERES Print Agent/eres-print-agent run")
  if [ -n "$pids" ]; then
    echo "Running processes:"
    ps -o pid=,rss=,%cpu=,etime= -p "$(echo $pids | tr ' ' ',')" |
      awk '{printf "  pid %s  memory %.0f MB  cpu %s%%  up %s\n", $1, $2/1024, $3, $4}'
  else
    echo "No agent process running."
  fi
}

do_stop() {
  if loaded; then
    launchctl bootout "$TARGET" 2>/dev/null
  fi
  # Anything left over (e.g. started by hand with `eres-print-agent run`).
  pkill -f "ERES Print Agent/eres-print-agent run" 2>/dev/null
  sleep 1
  echo "Stopped. Receipts won't print on this Mac until you start it again."
}

do_start() {
  if [ ! -f "$PLIST" ]; then
    echo "Not installed. Re-run the install command from ERES > Settings > Printers."
    exit 1
  fi
  loaded || launchctl bootstrap "$DOMAIN" "$PLIST"
  launchctl kickstart "$TARGET" 2>/dev/null
  sleep 2
  echo "Started."
}

case "$1" in
  status) show_status ;;
  stop) do_stop ;;
  start) do_start ;;
  restart) do_stop; do_start ;;
  disable)
    launchctl disable "$TARGET"
    do_stop
    echo "Disabled: it stays off after restart/login."
    ;;
  enable)
    launchctl enable "$TARGET"
    do_start
    ;;
  *)
    echo "Usage: $0 {status|stop|start|restart|disable|enable}"
    exit 1
    ;;
esac
