#!/usr/bin/python3
"""
Studio 1810c - desktop application.

A real window (GTK3 + WebKit2) around the same control surface the daemon
serves, with the daemon running in-process on an ephemeral loopback port.
No browser, no address bar, no terminal.

    studio-1810c                 # installed launcher
    ./ucapp.py                   # from a checkout
"""

import os
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

import gi

gi.require_version("Gtk", "3.0")
try:                                   # Ubuntu 22.04+, Debian 12+
    gi.require_version("WebKit2", "4.1")
except ValueError:                     # Ubuntu 20.04, older 22.04 installs
    try:
        gi.require_version("WebKit2", "4.0")
    except ValueError:
        raise SystemExit(
            "This app needs WebKitGTK. Install it with:\n"
            "    sudo apt install gir1.2-webkit2-4.1\n"
            "or, on older releases, gir1.2-webkit2-4.0")
from gi.repository import Gtk, GLib, WebKit2  # noqa: E402

APP_ID = "io.github.uc1810c.Mixer"
APP_NAME = "Studio 1810c"
RULE_NAME = "99-presonus-1810c.rules"


def find_rule():
    for path in (os.path.join(HERE, RULE_NAME),
                 "/usr/lib/udev/rules.d/" + RULE_NAME,
                 "/etc/udev/rules.d/" + RULE_NAME):
        if os.path.exists(path):
            return path
    return None


GRANT_CMD = (
    'install -m644 "{rule}" /etc/udev/rules.d/{name} && '
    "udevadm control --reload && "
    "udevadm trigger --action=add --subsystem-match=usb"
)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, url, surface):
        super().__init__(application=app, title=APP_NAME)
        self.surface = surface
        self.url = url
        # Fit the screen it will actually run on: 1400x880 is the comfortable
        # size, but a musician's laptop is often 1366x768 and a window taller
        # than the screen hides the master faders.
        width, height = 1400, 880
        # Gtk.Widget.get_screen() rather than importing Gdk: a bare
        # "from gi.repository import Gdk" loads Gdk 4.0 alongside Gtk 3.0 and
        # the import dies with "Gdk version 3.0, but 4.0 is already loaded".
        try:
            screen = self.get_screen()
            monitor = screen.get_primary_monitor() or screen.get_monitor(0)
            area = monitor.get_workarea()
            width = min(width, max(1024, area.width - 40))
            height = min(height, max(680, area.height - 60))
        except (AttributeError, TypeError):
            pass
        self.set_default_size(width, height)
        self.set_size_request(min(1024, width), min(680, height))
        for icon in ("packaging/studio-1810c.svg", "studio-1810c.svg",
                     "/usr/share/icons/hicolor/scalable/apps/studio-1810c.svg"):
            path = icon if icon.startswith("/") else os.path.join(HERE, icon)
            if os.path.exists(path):
                try:
                    self.set_icon_from_file(path)
                    break
                except GLib.Error:
                    pass
        else:
            self.set_icon_name("studio-1810c")

        geom = os.environ.get("UC_APP_GEOM")
        if geom:
            try:
                x, y, w, h = (int(v) for v in geom.split(","))
                self.move(x, y)
                self.resize(w, h)
                self.set_keep_above(True)
            except ValueError:
                pass

        self.web = WebKit2.WebView()
        settings = self.web.get_settings()
        settings.set_property("enable-page-cache", False)
        self.web.load_uri(url)
        self.add(self.web)
        self.show_all()   # present() shows the window, not its children

        self.connect("key-press-event", self.on_key)

    def on_key(self, _widget, event):
        if event.state & 4 and event.keyval in (ord("r"), ord("R")):  # Ctrl+R
            self.web.reload()
            return True
        return False

    def recheck_device(self):
        self.surface._start_device()
        self.web.reload()


def grant_dialog(parent):
    rule = find_rule()
    if rule is None:
        dialog = Gtk.MessageDialog(
            transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="udev rule not found")
        dialog.format_secondary_text(
            "The package should have installed %s in /usr/lib/udev/rules.d/." % RULE_NAME)
        dialog.run()
        dialog.destroy()
        return False

    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text="Allow access to the audio interface?")
    dialog.format_secondary_text(
        "Linux only lets administrators talk to the interface directly.\n"
        "This installs a udev rule so you (and only logged-in desktop users) "
        "can control the mixer without running the app as root.\n\n"
        "You will be asked for your password once.")
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok = dialog.add_button("Grant access", Gtk.ResponseType.OK)
    ok.get_style_context().add_class("suggested-action")
    response = dialog.run()
    dialog.destroy()
    if response != Gtk.ResponseType.OK:
        return False

    cmd = GRANT_CMD.format(rule=rule, name=RULE_NAME)
    try:
        proc = subprocess.run(["pkexec", "sh", "-c", cmd],
                              capture_output=True, text=True)
    except FileNotFoundError:
        proc = None
    if proc is not None and proc.returncode == 0:
        return True

    fail = Gtk.MessageDialog(
        transient_for=parent, modal=True, message_type=Gtk.MessageType.WARNING,
        buttons=Gtk.ButtonsType.CLOSE, text="Access was not granted")
    detail = (proc.stderr.strip() if proc and proc.stderr else
              "pkexec is not available on this system.")
    fail.format_secondary_text(
        "%s\n\nYou can run this once in a terminal instead:\n\n"
        "sudo install -m644 %s /etc/udev/rules.d/\n"
        "sudo udevadm control --reload && sudo udevadm trigger --action=add "
        "--subsystem-match=usb" % (detail, rule))
    fail.run()
    fail.destroy()
    return False


class App(Gtk.Application):
    def __init__(self, url, surface, httpd):
        super().__init__(application_id=APP_ID)
        self.url = url
        self.surface = surface
        self.httpd = httpd
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = Window(self, self.url, self.surface)
        self.win.present()

        def maybe_grant():
            err = (self.surface.error or "").lower()
            if "access denied" in err or "permission" in err:
                if grant_dialog(self.win):
                    self.win.recheck_device()
            return False
        GLib.timeout_add(900, maybe_grant)


def main():
    GLib.set_prgname("studio-1810c")     # matches StartupWMClass in the .desktop
    GLib.set_application_name(APP_NAME)
    # daemon in-process on an ephemeral port so it never collides with a CLI run
    sys.argv = [sys.argv[0]]
    import ucd
    httpd, url, surface = ucd.serve("127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("studio-1810c: %s (device: %s)" % (url, surface.error or "ok"), flush=True)

    app = App(url, surface, httpd)
    try:
        code = app.run(sys.argv)
    finally:
        httpd.shutdown()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
