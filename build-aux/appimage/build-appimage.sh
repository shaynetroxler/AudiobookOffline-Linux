#!/usr/bin/env bash
# Assembles the AppDir and packages it into an AppImage. Meant to run inside
# the container built from build-aux/appimage/Dockerfile (see
# build-aux/appimage/run-docker-build.sh), which has the GTK4/libadwaita/
# GStreamer stack this script bundles installed from apt.
set -euo pipefail

APP_ID="org.shayne.AudiobookOffline"
APP_NAME="AudiobookOffline"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APPDIR="$DIST_DIR/AppDir"
TOOLS_DIR="$ROOT_DIR/.cache/appimage"
ARCH="${ARCH:-x86_64}"
MULTIARCH="x86_64-linux-gnu"

log_step() { printf '\n==> %s\n' "$1"; }

require_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required tool: $1" >&2
        exit 1
    fi
}

download_tool() {
    local target="$1" url="$2"
    if [ ! -x "$target" ]; then
        curl -L "$url" -o "$target"
        chmod +x "$target"
    fi
}

require_tool python3
require_tool curl

mkdir -p "$DIST_DIR" "$TOOLS_DIR"
LINUXDEPLOY_BIN="$TOOLS_DIR/linuxdeploy-x86_64.AppImage"
APPIMAGETOOL_BIN="$TOOLS_DIR/appimagetool-x86_64.AppImage"
download_tool "$LINUXDEPLOY_BIN" "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
download_tool "$APPIMAGETOOL_BIN" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

log_step "Preparing AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/girepository-1.0" \
    "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/512x512/apps"

log_step "Installing desktop file and icon"
cp "$ROOT_DIR/data/$APP_ID.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT_DIR/data/icon.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
ln -sr "$APPDIR/usr/share/applications/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
ln -sr "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png" "$APPDIR/$APP_ID.png"
ln -sr "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png" "$APPDIR/.DirIcon"

cp "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

SYSTEM_PYTHON="/usr/bin/python3"
PYTHON_VERSION="$("$SYSTEM_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_STDLIB="$("$SYSTEM_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"
TARGET_PYTHON_DIR="$APPDIR/usr/lib/python$PYTHON_VERSION"
TARGET_SITE_PACKAGES="$TARGET_PYTHON_DIR/dist-packages"

log_step "Copying Python $PYTHON_VERSION runtime"
mkdir -p "$TARGET_SITE_PACKAGES"
cp -aL "$SYSTEM_PYTHON" "$APPDIR/usr/bin/python3"
cp -a "$PYTHON_STDLIB/." "$TARGET_PYTHON_DIR/"
# All of dist-packages, not a curated subset: apt's python3-gi, python3-gi-cairo
# and python3-requests each drag in several transitive deps (pycairo, urllib3,
# certifi, idna, ...) and copying the lot is far less fragile than enumerating
# them by hand and missing one.
cp -a /usr/lib/python3/dist-packages/. "$TARGET_SITE_PACKAGES/"

log_step "Installing our own package"
cp -a "$ROOT_DIR/absplayer" "$TARGET_SITE_PACKAGES/"
rm -rf "$TARGET_SITE_PACKAGES/absplayer/__pycache__"

log_step "Collecting GObject introspection typelibs"
cp -a "/usr/lib/$MULTIARCH/girepository-1.0/." "$APPDIR/usr/lib/girepository-1.0/"

log_step "Bundling GStreamer plugins and scanner"
mkdir -p "$APPDIR/usr/lib/gstreamer-1.0"
cp -a "/usr/lib/$MULTIARCH/gstreamer-1.0/." "$APPDIR/usr/lib/gstreamer-1.0/"
GST_PLUGIN_SCANNER_SRC="$(find /usr/lib /usr/libexec -name gst-plugin-scanner 2>/dev/null | head -1 || true)"
if [ -z "$GST_PLUGIN_SCANNER_SRC" ]; then
    echo "Could not find gst-plugin-scanner" >&2
    exit 1
fi
mkdir -p "$APPDIR/usr/lib/gstreamer1.0/gstreamer-1.0"
cp -a "$GST_PLUGIN_SCANNER_SRC" "$APPDIR/usr/lib/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner"

log_step "Bundling gdk-pixbuf loaders"
GDK_PIXBUF_MODULEDIR_SYS="$(pkg-config --variable=gdk_pixbuf_moduledir gdk-pixbuf-2.0 2>/dev/null || true)"
if [ -n "$GDK_PIXBUF_MODULEDIR_SYS" ] && [ -d "$GDK_PIXBUF_MODULEDIR_SYS" ]; then
    APPDIR_LOADERS="$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders"
    mkdir -p "$APPDIR_LOADERS"
    cp -a "$GDK_PIXBUF_MODULEDIR_SYS"/*.so "$APPDIR_LOADERS/"
    gdk-pixbuf-query-loaders "$APPDIR_LOADERS"/*.so > "$APPDIR/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
fi

log_step "Resolving shared libraries with linuxdeploy (patchelf disabled)"
# AppRun sets LD_LIBRARY_PATH explicitly, so we don't need (or want)
# linuxdeploy rewriting rpaths on libraries owned by the system's package
# manager -- point it at a no-op patchelf instead, same trick Meshy's
# AppImage build uses for the same reason.
NOOP_PATCHELF_DIR="$(mktemp -d)"
printf '#!/bin/sh\nexit 0\n' > "$NOOP_PATCHELF_DIR/patchelf"
chmod +x "$NOOP_PATCHELF_DIR/patchelf"

mapfile -t EXTRA_LIBS < <(find "$TARGET_SITE_PACKAGES" "$APPDIR/usr/lib/gstreamer-1.0" -name '*.so' -o -name '*.so.*')

LINUXDEPLOY_EXTRACTED="$(mktemp -d)"
(cd "$LINUXDEPLOY_EXTRACTED" && "$LINUXDEPLOY_BIN" --appimage-extract >/dev/null 2>&1)
cp "$NOOP_PATCHELF_DIR/patchelf" "$LINUXDEPLOY_EXTRACTED/squashfs-root/usr/bin/patchelf"

LIBRARY_ARGS=()
for so in "${EXTRA_LIBS[@]}"; do
    LIBRARY_ARGS+=(--library "$so")
done
for lib_name in libgtk-4.so libadwaita-1.so libgstreamer-1.0.so libsecret-1.so libgstapp-1.0.so libgstpbutils-1.0.so libgstaudio-1.0.so libgstvideo-1.0.so; do
    lib_path="$(find "/usr/lib/$MULTIARCH" -maxdepth 1 -name "$lib_name*" | head -1)"
    if [ -n "$lib_path" ]; then
        LIBRARY_ARGS+=(--library "$lib_path")
    fi
done

PATH="$NOOP_PATCHELF_DIR:$PATH" NO_STRIP=true ARCH="$ARCH" \
    "$LINUXDEPLOY_EXTRACTED/squashfs-root/AppRun" \
    --appdir "$APPDIR" \
    --executable "$APPDIR/usr/bin/python3" \
    --executable "$APPDIR/usr/lib/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner" \
    "${LIBRARY_ARGS[@]}" \
    --desktop-file "$APPDIR/usr/share/applications/$APP_ID.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"

rm -rf "$NOOP_PATCHELF_DIR" "$LINUXDEPLOY_EXTRACTED"

# linuxdeploy's desktop-file/icon handling also drops its own AppRun in place
# -- put ours back since it knows about PYTHONPATH/GST_PLUGIN_SCANNER/etc.
cp "$SCRIPT_DIR/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

log_step "Filling in any shared libraries linuxdeploy's walk missed"
# linuxdeploy only recurses through the deps of the files we hand it directly;
# a lib that's pulled in as someone else's dependency (e.g. libfribidi via
# libpango, which GObject-Introspection dlopen()s rather than linking) can
# still end up with ITS OWN deps unresolved. `ldd` can't detect that reliably
# from inside this build container, because the container has the full apt
# dependency tree installed system-wide -- ldd would happily resolve a "missing"
# lib from the SYSTEM path even when it never made it into the AppDir. So this
# reads each file's DT_NEEDED entries directly (readelf, no path resolution
# involved) and loops to a fixed point instead.
BASE_LIBS_REGEX='^(linux-vdso\.so.*|ld-linux-x86-64\.so\.2|libc\.so\.6|libm\.so\.6|libdl\.so\.2|libpthread\.so\.0|librt\.so\.1|libresolv\.so\.2|libutil\.so\.1|libnsl\.so\.1)$'
fill_missing_libs() {
    local changed=1 pass=0
    while [ "$changed" -eq 1 ]; do
        changed=0
        pass=$((pass + 1))
        while IFS= read -r -d '' f; do
            while IFS= read -r needed; do
                [ -z "$needed" ] && continue
                [[ "$needed" =~ $BASE_LIBS_REGEX ]] && continue
                [ -f "$APPDIR/usr/lib/$needed" ] && continue
                src="$(find "/usr/lib/$MULTIARCH" -maxdepth 1 -name "$needed" | head -1)"
                if [ -n "$src" ]; then
                    cp -aL "$src" "$APPDIR/usr/lib/$needed"
                    echo "  [$pass] added $needed (needed by $(basename "$f"))"
                    changed=1
                fi
            done < <(readelf -d "$f" 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p')
        done < <(find "$APPDIR/usr/lib" "$APPDIR/usr/bin" -type f \( -name '*.so*' -o -perm -u+x \) -print0 2>/dev/null)
    done
}
fill_missing_libs

log_step "Building final AppImage"
APPIMAGE_PATH="$DIST_DIR/${APP_NAME}-x86_64.AppImage"
ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL_BIN" "$APPDIR" "$APPIMAGE_PATH"

log_step "Done"
echo "AppImage written to $APPIMAGE_PATH"
