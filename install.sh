#!/bin/sh
# One-step installer for Ubuntu / Debian / Linux Mint.
#
#   bash install.sh                       # from this folder, uses the .deb beside it
#   bash install.sh <path-to.deb>
#
# It installs the package with apt (so missing dependencies are fetched),
# refreshes the desktop menu and reloads udev. You are asked for your
# password once, by apt, and nothing else.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
deb=${1:-}

if [ -z "$deb" ]; then
    for candidate in "$here"/studio-1810c_*.deb "$here"/dist/studio-1810c_*.deb; do
        [ -f "$candidate" ] && deb=$candidate && break
    done
fi

if [ -z "$deb" ] || [ ! -f "$deb" ]; then
    echo "No studio-1810c .deb found next to this script." >&2
    echo "Download studio-1810c_1.0.0_amd64.deb and run: bash install.sh that-file.deb" >&2
    exit 1
fi

echo "Installing $(basename "$deb") ..."
echo "apt will ask for your administrator password once."
echo

if command -v apt > /dev/null 2>&1; then
    sudo apt install -y "$deb"
else
    sudo dpkg -i "$deb" || sudo apt-get -f install -y
fi

if [ -x /usr/bin/studio-1810c ]; then
    echo
    echo "Done. Start it from your application menu (search for \"Studio 1810c\"),"
    echo "or run:  studio-1810c"
else
    echo "Installation did not complete - please send the output above." >&2
    exit 1
fi
