#!/usr/bin/env bash
# Builds the AppImage build environment (Ubuntu 24.04 + the GTK4/libadwaita/
# GStreamer stack) and runs build-appimage.sh inside it, so the result isn't
# tied to whatever's installed on the dev machine. Output lands in ./dist/
# on the host, same as a native build would.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
IMAGE_TAG="audiobookshelf-linux-appimage-builder"

docker build -t "$IMAGE_TAG" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"
docker run --rm -v "$ROOT_DIR:/src" -w /src "$IMAGE_TAG" \
    bash build-aux/appimage/build-appimage.sh
