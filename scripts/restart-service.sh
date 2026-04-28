#!/usr/bin/env bash
#
# Restart the Pallium systemd user service.
#
# Usage:
#   ./restart-service.sh
#

set -euo pipefail

SERVICE_NAME="pallium.service"

if ! systemctl --user is-enabled "$SERVICE_NAME" &>/dev/null; then
    echo "Error: Pallium service not installed. Run install-service.sh first."
    exit 1
fi

echo "Restarting Pallium..."
systemctl --user restart "$SERVICE_NAME"

echo "Pallium restarted. Dashboard at http://localhost:19836/dashboard"
echo "  Status: systemctl --user status pallium"
echo "  Logs:   journalctl --user -u pallium -f"
