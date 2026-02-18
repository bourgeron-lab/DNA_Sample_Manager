#!/bin/bash
# Launch DNA Sample Manager with graceful reload support
#
# Usage:
#   ./run.sh          - Start the server
#   ./run.sh reload   - Reload after code changes (zero downtime)
#   ./run.sh stop     - Stop the server

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/temp/.venv"
PIDFILE="$DIR/gunicorn.pid"
PORT=5002

case "${1:-start}" in
    start)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Server already running (PID $(cat "$PIDFILE")). Use './run.sh reload' to apply changes."
            exit 1
        fi
        echo "Starting DNA Sample Manager on http://127.0.0.1:$PORT ..."
        cd "$DIR"
        "$VENV/bin/gunicorn" \
            --bind "127.0.0.1:$PORT" \
            --workers 2 \
            --pid "$PIDFILE" \
            --access-logfile - \
            --error-logfile - \
            --graceful-timeout 10 \
            --daemon \
            app:app
        sleep 1
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Server started (PID $(cat "$PIDFILE"))"
        else
            echo "Failed to start. Check logs."
            exit 1
        fi
        ;;
    reload)
        if [ ! -f "$PIDFILE" ] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Server not running. Use './run.sh' to start."
            exit 1
        fi
        echo "Reloading workers gracefully (zero downtime)..."
        kill -HUP "$(cat "$PIDFILE")"
        echo "Done. New code is now live."
        ;;
    stop)
        if [ ! -f "$PIDFILE" ] || ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "Server not running."
            exit 0
        fi
        echo "Stopping server (PID $(cat "$PIDFILE"))..."
        kill -TERM "$(cat "$PIDFILE")"
        sleep 2
        echo "Stopped."
        ;;
    *)
        echo "Usage: $0 {start|reload|stop}"
        exit 1
        ;;
esac
