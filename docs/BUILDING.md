# Building Studio 1810c on any distribution

The application has no compiled code. "Building" means: install the desktop
libraries your distribution already ships, then either run it from the checkout
or wrap it in a package.

Runtime requirements, everywhere:

| requirement | why |
|---|---|
| Python 3.8+ | the application itself |
| PyGObject (`gi`) + GTK 3 | the window |
| WebKitGTK 4.1 **or** 4.0 | the UI engine (the app falls back automatically) |
| libusb 1.0 | talking to the interface |
| `alsa-utils` (recommended) | sample-rate readout, `uc1810c.py doctor` |
| a udev rule | permission to open the interface |

`pyusb` is **vendored** in `vendor/`, so no `pip install` is needed at runtime and
PEP 668 never gets in the way.

---

## 1. Dependencies per distribution

### Debian / Ubuntu / Mint

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0 libusb-1.0-0 alsa-utils \
                 gir1.2-webkit2-4.1      # 20.04: gir1.2-webkit2-4.0
```

### Fedora

```bash
sudo dnf install python3 python3-gobject gtk3 webkit2gtk4.1 libusb1 alsa-utils
```

Fedora 38 and older call the WebKit package `webkit2gtk3`. Both provide the GI
typelib the app needs.

### Arch / Manjaro

```bash
sudo pacman -S python python-gobject gtk3 webkit2gtk-4.1 libusb alsa-utils
```

### openSUSE

```bash
sudo zypper install python3-gobject gtk3 libwebkit2gtk-4_1-0 libusb-1_0-0 alsa-utils
```

### Anything else

You need: Python 3.8+, a `gi` typelib for `Gtk-3.0` and `WebKit2-4.1` (or `-4.0`),
and `libusb-1.0`. Check before building:

```bash
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','3.0'); print('gtk ok')"
/usr/bin/python3 -c "import gi; gi.require_version('WebKit2','4.1'); print('webkit ok')"
```

---

## 2. Run it from a checkout

```bash
git clone https://github.com/xenprotocol/studio-1810c
cd studio-1810c

# the app must run on the system interpreter, because that is where gi lives
/usr/bin/python3 ucapp.py
```

For the CLI, any interpreter with `pyusb` works; a venv is the tidy option:

```bash
python3 -m venv .venv && ./.venv/bin/pip install pyusb
./uc1810c.py doctor
```

Install the udev rule once:

```bash
sudo install -m644 99-presonus-1810c.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --action=add --subsystem-match=usb
```

Run the tests (no hardware needed):

```bash
./.venv/bin/python tests/test_protocol.py
```

---

## 3. Build the Debian package

```bash
./packaging/build-deb.sh
# -> dist/studio-1810c_1.0.0_amd64.deb
```

The script stages everything, generates the icon PNGs with `rsvg-convert` (from
`librsvg2-bin`), and builds with `dpkg-deb --root-owner-group`. The result is
`lintian`-clean:

```bash
sudo apt install lintian && lintian dist/studio-1810c_1.0.0_amd64.deb
```

Bump the version with `VERSION=1.0.1 ./packaging/build-deb.sh`.

---

## 4. Build the RPM

`packaging/studio-1810c.spec` is included. From a clean tree (it installs from
the source directory, so no tarball is required):

```bash
rpmbuild -bb packaging/studio-1810c.spec \
  --define "_sourcedir $PWD" \
  --define "_topdir $PWD/rpmbuild"
```

Result: `rpmbuild/RPMS/noarch/studio-1810c-1.1.1-1.*.rpm`.

The spec is marked `BuildArch: noarch` on purpose — there is nothing to compile —
and its `%post` reloads udev exactly like the Debian post-install does.

**Status: built and linted.** `studio-1810c-1.1.1-1.fc40.noarch.rpm` was produced
on Fedora 40 and `rpmlint` reports *0 errors, 0 warnings*. Eight findings are
filtered deliberately in `packaging/studio-1810c.rpmlintrc`, each with a reason
in the file (British spellings, non-binary payload in `/usr/lib`, and the explicit
`libusb1` requirement that rpm cannot generate because pyusb dlopens libusb).

If you build in a container, note that `%{_sourcedir}` points at your checkout:

```bash
docker run --rm -v "$PWD":/src:ro -v "$PWD/dist/rpm":/out fedora:40 bash -lc '
  dnf -y install rpm-build librsvg2-tools rpmlint
  rpmbuild -bb /src/packaging/studio-1810c.spec \
    --define "_sourcedir /src" --define "_rpmdir /out" --define "_buildrootdir /tmp/br"
  rpmlint -r /src/packaging/studio-1810c.rpmlintrc /out/noarch/*.rpm'
```

The output directory ends up owned by root: build into a mount point you can
delete, or fix ownership from inside a container afterwards.

---

## 5. Arch package

```bash
cd packaging && makepkg -si        # uses PKGBUILD
```

The PKGBUILD downloads the tagged release tarball and verifies its SHA-256, so a
wrong checksum fails the build instead of shipping.

**Status: built.** Run on a clean `archlinux` image it produced
`studio-1810c-1.1.0-1-any.pkg.tar.zst` from the `v1.1.0` tarball, which also
proves the checksum and the Arch dependency names (`python-gobject`, `gtk3`,
`webkit2gtk-4.1`, `libusb`) are correct.

In a container, install the dependencies as root first — `makepkg -s` cannot
`sudo` as the build user:

```bash
docker run --rm -v "$PWD/packaging":/pk:ro -v "$PWD/dist/arch":/out archlinux bash -lc '
  pacman -Sy --noconfirm --needed base-devel librsvg python-gobject gtk3 webkit2gtk-4.1 libusb
  useradd -m builder && mkdir -p /home/builder/pkg
  cp /pk/PKGBUILD /home/builder/pkg/ && chown -R builder /home/builder/pkg
  su builder -c "cd /home/builder/pkg && makepkg -f --noconfirm"'
```

---

## 6. What a package must contain

If you package this for your distribution, these are the moving parts (all of
them matter):

```
/usr/lib/studio-1810c/          ucapp.py, ucd.py, uc1810c.py, ui/, vendor/, icon
/usr/bin/studio-1810c           launcher: exec /usr/bin/python3 /usr/lib/studio-1810c/ucapp.py "$@"
/usr/share/applications/io.github.uc1810c.Mixer.desktop
/usr/share/icons/hicolor/{scalable,48x48,64x64,128x128,256x256}/apps/studio-1810c.*
/usr/share/metainfo/io.github.uc1810c.Mixer.metainfo.xml
/usr/share/man/man1/studio-1810c.1.gz
/usr/share/doc/studio-1810c/{copyright,changelog.gz}
/usr/lib/udev/rules.d/99-presonus-1810c.rules
```

Two details that are easy to get wrong and produce confusing bugs:

- **the desktop file must be named after the GApplication id**
  (`io.github.uc1810c.Mixer.desktop`). Wayland compositors match a window to its
  menu entry by app id == desktop file name; rename it and the app gets a generic
  icon and never groups in the dock.
- **`StartupWMClass=ucapp.py`** is the X11 `WM_CLASS` the window actually reports
  (it comes from the script's filename). Changing the payload filename without
  changing this breaks taskbar grouping on X11.

Post-install script must reload udev, or an interface that was already plugged in
stays inaccessible until the next replug:

```sh
udevadm control --reload-rules || true
udevadm trigger --action=add --subsystem-match=usb || true
```

---

## 7. Notes for porters

- **Do not ship the venv.** It pins the interpreter and does not see the system
  `gi`. The app must run on `/usr/bin/python3`.
- **Do not bundle a browser.** The package depends on the WebKitGTK the desktop
  already has; that is the whole reason the download is 70 KB instead of 150 MB.
- **Test the 4.0 fallback** if your distribution is older than 22.04 — `ucapp.py`
  asks for 4.1 and falls back to 4.0 when the typelib is missing.
- **`gio-querymodules`/`glib-compile-schemas` are not needed**; the app reads no
  GSettings.
- The interface is `194f:010c`; the sibling models are `194f:0107` (1824) and
  `194f:010d` (1824c). The udev rule already covers all three.

---

## 8. Reproducing the reverse engineering

Not required to build, but if you want to re-derive the protocol or extend it to
another model, `REPORT.md` and `PROTOCOL.md` describe the process and the
`ghidra_scripts/` directory contains the four scripts used against the macOS
Universal Control binary (Ghidra 11.x, JDK 21).

The vendor binaries themselves are **not** in this repository and are not
redistributed — extract them from your own Universal Control installer for your
own analysis.
