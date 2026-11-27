#!/usr/bin/env bash
# Register the control surface in the desktop app menu, for this checkout.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"

cat > "$APPS/uc1810c.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Studio 1810c
Comment=PreSonus / Fender Studio 1810c mixer on Linux
Exec=${DIR}/uc1810c-gui
Icon=audio-card
Terminal=false
Categories=AudioVideo;Audio;Mixer;
Keywords=mixer;audio;presonus;fender;1810c;
EOF

update-desktop-database "$APPS" 2>/dev/null || true
echo "installed $APPS/uc1810c.desktop -> ${DIR}/uc1810c-gui"
