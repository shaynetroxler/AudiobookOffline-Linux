# AudiobookOffline (Linux)

A native GTK4/libadwaita desktop client for [Audiobookshelf](https://github.com/advplyr/audiobookshelf) — browse your library, stream, download books for true offline playback, and keep listening progress synced back to your server.

A Linux counterpart to the [macOS AudiobookOffline app](https://github.com/shaynetroxler/AudiobookOffline), built for the same reason: none of the existing Audiobookshelf clients do local pre-download for offline use.

## Status

**v1** — working and in daily use, but young. Expect rough edges; fixes will land as point releases.

## Features

- Log in to any self-hosted Audiobookshelf server
- Browse your full library, search by title or author
- Browse by Series or Collections
- Continue Listening shelf, with the ability to remove a book from it at any time
- Library stats dashboard — item/author/genre/track counts, total listening time and size, top authors and genres, longest and largest items
- Stream playback, or download a book for fully offline listening
- Chapter list with jump-to-chapter, current chapter highlighted, seek slider scoped to the current chapter
- ±30s skip buttons
- Variable playback speed (0.75×–2×, pitch-corrected)
- Sleep timer (5–60 min, or end of chapter)
- Now Playing integration via MPRIS — media keys, GNOME Shell's media widget, waybar/polybar modules, `playerctl`
- Progress reported back to the server as you listen, reconciled on resume so progress made on another device is picked up correctly
- Cover art throughout

## Requirements

- Python 3.11+
- GTK4 and libadwaita (`gtk4`, `libadwaita`)
- GStreamer with `gst-plugins-base`, `gst-plugins-good`, `gst-plugins-bad`, and `gst-libav` (for HTTP streaming and AAC/M4B decoding)
- libsecret (for storing your server credentials in the system keyring)
- An Audiobookshelf server you can reach (local network or otherwise)

On Arch:

```
sudo pacman -S gtk4 libadwaita gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-libav libsecret python-gobject
```

## Running

```
pip install -r requirements.txt
python3 -m absplayer.app
```

To add it to your app launcher with an icon, run `./install.sh` once (installs a `.desktop` entry and icon for the current user).

## License

MIT
