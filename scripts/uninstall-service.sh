#!/usr/bin/env bash
#
# Remove the Pallium systemd user service.
#
# Usage:
#   ./uninstall-service.sh
#

set -euo pipefail

SERVICE_FILE="$HOME/.config/systemd/user/pallium.service"

if systemctl --user is-active pallium.service &>/dev/null; then
    systemctl --user stop pallium.service
    echo "Stopped Pallium service."
fi

if systemctl --user is-enabled pallium.service &>/dev/null; then
    systemctl --user disable pallium.service
    echo "Disabled Pallium service."
fi

if [[ -f "$SERVICE_FILE" ]]; then
    rm "$SERVICE_FILE"
    systemctl --user daemon-reload
    echo "Removed $SERVICE_FILE"
else
    echo "No Pallium service file found."
fi

echo "Pallium service uninstalled."
