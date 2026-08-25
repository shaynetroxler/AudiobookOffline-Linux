# Build environment for the AppImage: Debian 12 (glibc 2.36, mid-2023) is the
# oldest widely-used base with a libadwaita new enough for Adw.AboutWindow
# (1.2+) and everything else the app uses -- Adw.ToolbarView was deliberately
# avoided in app.py because it needs 1.4+, which would have forced a much
# newer (and less portable) glibc. A first build on Ubuntu 24.04 (glibc 2.39)
# failed to launch on a real Debian 12 machine with a GLIBC_2.38-not-found
# error, which is what pinned this down to Debian 12 specifically rather than
# "whatever's newest".
FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-gi python3-gi-cairo python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 \
    gir1.2-secret-1 gir1.2-gst-plugins-base-1.0 \
    libgtk-4-1 libadwaita-1-0 libsecret-1-0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-libav \
    desktop-file-utils file curl ca-certificates binutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
