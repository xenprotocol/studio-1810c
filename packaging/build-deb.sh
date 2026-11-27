#!/usr/bin/env bash
# Build a .deb that installs the app for everyone: binary, icon, udev rule.
set -euo pipefail

umask 022                     # lintian-clean directory modes regardless of the caller's umask
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${VERSION:-1.1.2}"
ARCH="$(dpkg --print-architecture)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

APP="$STAGE/usr/lib/studio-1810c"
mkdir -p "$APP" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/metainfo" "$STAGE/usr/share/man/man1" \
         "$STAGE/usr/share/doc/studio-1810c" \
         "$STAGE/usr/lib/udev/rules.d" "$STAGE/DEBIAN"
for size in 48 64 128 256; do
    mkdir -p "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps"
done

# --- payload -----------------------------------------------------------
install -m644 "$ROOT/ucapp.py" "$ROOT/ucd.py" "$ROOT/uc1810c.py" "$ROOT/meters.py" "$APP/"
cp -r "$ROOT/ui" "$APP/ui"
cp -r "$ROOT/vendor" "$APP/vendor"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +

install -m755 "$ROOT/packaging/studio-1810c" "$STAGE/usr/bin/studio-1810c"
install -m644 "$ROOT/packaging/io.github.uc1810c.Mixer.desktop" \
    "$STAGE/usr/share/applications/io.github.uc1810c.Mixer.desktop"
install -m644 "$ROOT/packaging/studio-1810c.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/studio-1810c.svg"
install -m644 "$ROOT/packaging/studio-1810c.svg" "$APP/studio-1810c.svg"
for size in 48 64 128 256; do
    rsvg-convert -w "$size" -h "$size" "$ROOT/packaging/studio-1810c.svg" \
        -o "$STAGE/usr/share/icons/hicolor/${size}x${size}/apps/studio-1810c.png"
done
install -m644 "$ROOT/packaging/io.github.uc1810c.Mixer.metainfo.xml" \
    "$STAGE/usr/share/metainfo/io.github.uc1810c.Mixer.metainfo.xml"
install -m644 "$ROOT/99-presonus-1810c.rules" \
    "$STAGE/usr/lib/udev/rules.d/99-presonus-1810c.rules"
gzip -9n -c "$ROOT/packaging/studio-1810c.1" > "$STAGE/usr/share/man/man1/studio-1810c.1.gz"
chmod 644 "$STAGE/usr/share/man/man1/studio-1810c.1.gz"
install -m644 "$ROOT/packaging/copyright" \
    "$STAGE/usr/share/doc/studio-1810c/copyright"
gzip -9n -c "$ROOT/packaging/changelog" > "$STAGE/usr/share/doc/studio-1810c/changelog.gz"
chmod 644 "$STAGE/usr/share/doc/studio-1810c/changelog.gz"

# --- control -----------------------------------------------------------
SIZE="$(du -sk "$STAGE/usr" | awk '{s+=$1} END{print s}')"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: studio-1810c
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Maintainer: Studio 1810c for Linux <studio-1810c@users.noreply.github.com>
Installed-Size: $SIZE
Depends: python3, python3-gi, libglib2.0-0, libusb-1.0-0, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0
Recommends: alsa-utils
Description: Mixer and routing control for the PreSonus / Fender Studio 1810c
 A desktop application for the Studio 1810c audio interface on Linux.
 It speaks the vendor USB protocol to control the 18x10 routing matrix,
 the output faders and the front-panel switches - the parts ALSA does not
 expose - with a mixer window modelled on Universal Control.
 .
 Installs a udev rule granting desktop users access to the interface.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v udevadm > /dev/null && udevadm control --reload-rules || true
command -v udevadm > /dev/null && udevadm trigger --action=add --subsystem-match=usb || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
command -v udevadm > /dev/null && udevadm control --reload-rules || true
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postrm"

# --- build -------------------------------------------------------------
OUT="$ROOT/dist/studio-1810c_${VERSION}_${ARCH}.deb"
mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT" >/dev/null
echo "$OUT"
ls -lh "$OUT" | awk '{print $5, $9}'
