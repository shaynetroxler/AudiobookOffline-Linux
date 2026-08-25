# AudiobookOffline (Linux)

A native GTK4/libadwaita desktop client for [Audiobookshelf](https://github.com/advplyr/audiobookshelf) — browse your library, stream, download books for true offline playback, and keep listening progress synced back to your server.

A Linux counterpart to the [macOS AudiobookOffline app](https://github.com/shaynetroxler/AudiobookOffline), built for the same reason: none of the existing Audiobookshelf clients do local pre-download for offline use.

## Status

**v1.0.1** — working and in daily use, but young. Expect rough edges; fixes will land as point releases.

## Features

- Log in to any self-hosted Audiobookshelf server
- Browse your full library, search by title or author
- Browse by Series or Collections
- Continue Listening shelf, with a per-book download-status dot (tap the blue arrow to grab a book for offline before you head out; green means it's already downloaded), and the ability to remove a book from the shelf at any time
- Library stats dashboard — item/author/genre/track counts, total listening time and size, top authors and genres, longest and largest items
- Stream playback, or download a book for fully offline listening
- Chapter list with jump-to-chapter, current chapter highlighted, seek slider scoped to the current chapter
- ±30s skip buttons
- Variable playback speed (0.75×–2×, pitch-corrected)
- Sleep timer (5–60 min, or end of chapter) with a live countdown of time remaining
- Now Playing integration via MPRIS — media keys, GNOME Shell's media widget, waybar/polybar modules, `playerctl`
- Progress reported back to the server as you listen, reconciled on resume so progress made on another device is picked up correctly
- Cover art throughout
- Help menu with usage tips, and an About screen with links to the macOS and Windows versions

## Installing

**Don't want to install anything or touch a terminal?** Grab the AppImage from [Releases](https://github.com/shaynetroxler/audiobookshelf-linux/releases) — it bundles GTK4, libadwaita, GStreamer, and everything else it needs, so there's nothing to install first. Download it, then:

```
chmod +x AudiobookOffline-x86_64.AppImage
./AudiobookOffline-x86_64.AppImage
```

(or just tick "Allow executing" in your file manager's Properties dialog and double-click it). Needs a 64-bit Linux desktop from roughly the last couple of years.

It'll show up as a generic executable icon in your file manager rather than the app's real icon — that's normal for a plain AppImage and not a sign anything's wrong. If you want a proper icon, an app-launcher entry, and update handling, install [Gear Lever](https://github.com/mijorus/gearlever) (or AppImageLauncher) and point it at the file once; neither is required just to run it.

### Running from source

If you'd rather run it from source (or you're on an architecture the AppImage doesn't cover):

- Python 3.11+
- GTK4 and libadwaita (`gtk4`, `libadwaita`)
- GStreamer with `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad`, and `gst-libav` (for HTTP streaming and AAC/M4B decoding)
- libsecret (for storing your server credentials in the system keyring)
- An Audiobookshelf server you can reach (local network or otherwise)

On Arch:

```
sudo pacman -S gtk4 libadwaita gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav libsecret python-gobject
```

Then:

```
pip install -r requirements.txt
python3 -m absplayer.app
```

To add it to your app launcher with an icon, run `./install.sh` once (installs a `.desktop` entry and icon for the current user).

## Building the AppImage

`build-aux/appimage/run-docker-build.sh` builds it inside a pinned Ubuntu 24.04 Docker image (so the result doesn't depend on whatever happens to be installed on the dev machine) and writes `dist/AudiobookOffline-x86_64.AppImage`. `.github/workflows/appimage.yml` runs the same script and attaches the result to the GitHub Release whenever a `v*` tag is pushed.

## License

MIT
