%global debug_package %{nil}
%global appdir %{_prefix}/lib/studio-1810c

Name:           studio-1810c
Version:        1.1.0
Release:        1%{?dist}
Summary:        Mixer and routing control for the PreSonus / Fender Studio 1810c
License:        MIT
URL:            https://github.com/xenprotocol/studio-1810c
BuildArch:      noarch
BuildRequires:  librsvg2-tools
Requires:       python3
Requires:       python3-gobject
Requires:       gtk3
Requires:       webkit2gtk4.1
Requires:       libusb1
Recommends:     alsa-utils

%description
A desktop application for the Studio 1810c audio interface. It speaks the vendor
USB protocol to control the 18x10 routing matrix, the output faders and the
front-panel switches - the parts ALSA does not expose - with a mixer window
modelled on Universal Control. Audio keeps streaming through snd-usb-audio while
the mixer is in use.

%prep
# The package installs straight from the source tree:
#   rpmbuild -bb packaging/studio-1810c.spec --define "_sourcedir $PWD"

%install
rm -rf %{buildroot}
install -d %{buildroot}%{appdir}/ui \
           %{buildroot}%{appdir}/vendor \
           %{buildroot}%{_bindir} \
           %{buildroot}%{_datadir}/applications \
           %{buildroot}%{_datadir}/metainfo \
           %{buildroot}%{_datadir}/man/man1 \
           %{buildroot}%{_datadir}/doc/studio-1810c \
           %{buildroot}%{_prefix}/lib/udev/rules.d \
           %{buildroot}%{_datadir}/icons/hicolor/scalable/apps

install -m644 %{_sourcedir}/ucapp.py %{_sourcedir}/ucd.py %{_sourcedir}/uc1810c.py \
    %{_sourcedir}/meters.py %{buildroot}%{appdir}/
cp -r %{_sourcedir}/ui/. %{buildroot}%{appdir}/ui/
cp -r %{_sourcedir}/vendor/. %{buildroot}%{appdir}/vendor/
find %{buildroot}%{appdir} -name __pycache__ -type d -prune -exec rm -rf {} +

install -m755 %{_sourcedir}/packaging/studio-1810c %{buildroot}%{_bindir}/studio-1810c
install -m644 %{_sourcedir}/packaging/io.github.uc1810c.Mixer.desktop \
    %{buildroot}%{_datadir}/applications/
install -m644 %{_sourcedir}/packaging/io.github.uc1810c.Mixer.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/
install -m644 %{_sourcedir}/packaging/studio-1810c.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/
for size in 48 64 128 256; do
    install -d %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps
    rsvg-convert -w $size -h $size %{_sourcedir}/packaging/studio-1810c.svg \
        -o %{buildroot}%{_datadir}/icons/hicolor/${size}x${size}/apps/studio-1810c.png
done
install -m644 %{_sourcedir}/packaging/studio-1810c.1 %{buildroot}%{_datadir}/man/man1/
install -m644 %{_sourcedir}/packaging/copyright %{buildroot}%{_datadir}/doc/studio-1810c/
install -m644 %{_sourcedir}/packaging/changelog %{buildroot}%{_datadir}/doc/studio-1810c/
install -m644 %{_sourcedir}/99-presonus-1810c.rules %{buildroot}%{_prefix}/lib/udev/rules.d/

%post
command -v udevadm >/dev/null && udevadm control --reload-rules || :
command -v udevadm >/dev/null && udevadm trigger --action=add --subsystem-match=usb || :
update-desktop-database -q %{_datadir}/applications 2>/dev/null || :
gtk-update-icon-cache -q -t %{_datadir}/icons/hicolor 2>/dev/null || :

%postun
command -v udevadm >/dev/null && udevadm control --reload-rules || :

%files
%{_bindir}/studio-1810c
%dir %{appdir}
%{appdir}/ucapp.py
%{appdir}/ucd.py
%{appdir}/uc1810c.py
%{appdir}/meters.py
%{appdir}/ui
%{appdir}/vendor
%{_datadir}/applications/io.github.uc1810c.Mixer.desktop
%{_datadir}/metainfo/io.github.uc1810c.Mixer.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/studio-1810c.svg
%{_datadir}/icons/hicolor/*/apps/studio-1810c.png
%{_datadir}/man/man1/studio-1810c.1*
%{_datadir}/doc/studio-1810c/copyright
%{_datadir}/doc/studio-1810c/changelog
%{_prefix}/lib/udev/rules.d/99-presonus-1810c.rules

%changelog
* Fri Nov 27 2026 Studio 1810c for Linux <studio-1810c@users.noreply.github.com> - 1.1.0-1
- Level meters computed from the audio stream (PipeWire), per input and per output pair

* Fri Nov 27 2026 Studio 1810c for Linux <studio-1810c@users.noreply.github.com> - 1.0.0-1
- Initial package
