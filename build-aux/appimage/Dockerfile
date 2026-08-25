# Build environment for the AppImage: Ubuntu 24.04 gives us libadwaita 1.5
# (we need 1.4+ for Adw.ToolbarView) while staying well behind Arch's
# bleeding-edge glibc, so the AppImage runs on a broader range of target
# systems than building on the dev machine directly would.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-gi python3-gi-cairo python3-requests \
    gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 \
    gir1.2-secret-1 gir1.2-gst-plugins-base-1.0 \
    libgtk-4-1 libadwaita-1-0 libsecret-1-0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-libav \
    desktop-file-utils file curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
