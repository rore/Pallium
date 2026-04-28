#!/usr/bin/env bash
#
# Install Pallium as a systemd user service (Linux).
# Starts at login, restarts on failure.
#
# Usage:
#   ./install-service.sh [--port PORT] [--python PATH]
#

set -euo pipefail

PORT=19836
PYTHON_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --python)
            PYTHON_PATH="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--port PORT] [--python PATH]"
            exit 1
            ;;
    esac
done

# Detect Python
if [[ -z "$PYTHON_PATH" ]]; then
    PYTHON_PATH=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
    if [[ -z "$PYTHON_PATH" ]]; then
        echo "Error: Python not found. Specify --python or ensure Python is on PATH."
        exit 1
    fi
fi

# Detect repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [[ ! -f "$REPO_ROOT/app/run.py" ]]; then
    echo "Error: Cannot find app/run.py in $REPO_ROOT."
    exit 1
fi

echo "Installing Pallium systemd user service..."
echo "  Python: $PYTHON_PATH"
echo "  Repo:   $REPO_ROOT"
echo "  Port:   $PORT"

# Service data directory — isolated from dev DB
DATA_DIR="$HOME/.pallium/data"
mkdir -p "$DATA_DIR"
SQLITE_URL="sqlite:///$DATA_DIR/pallium.db"
VECTOR_INDEX_PATH="$DATA_DIR/vector_index"
echo "  Data:   $DATA_DIR"

SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/pallium.service"

mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Pallium memory sidecar service
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_PATH -m app.run all --port $PORT
WorkingDirectory=$REPO_ROOT
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=PALLIUM_SQLITE_URL=$SQLITE_URL
Environment=PALLIUM_VECTOR_INDEX_PATH=$VECTOR_INDEX_PATH

[Install]
WantedBy=default.target
EOF

echo "  Wrote $SERVICE_FILE"

# Reload and enable
systemctl --user daemon-reload
systemctl --user enable --now pallium.service

echo ""
echo "Pallium service installed and started."
echo "  Status: systemctl --user status pallium"
echo "  Logs:   journalctl --user -u pallium -f"
