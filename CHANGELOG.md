# Changelog

## v1.0.2 — 2026-08-28

### Fixed

- Chapter seek slider: dragging the handle now actually seeks playback. It previously moved visually but left playback position unchanged. The slider used a separate `GtkGestureClick` to detect press/release and seek on release, but `GtkScale`'s own built-in drag gesture claims the pointer sequence as soon as a real drag starts, cancelling the other gesture's tracking — so the release callback that triggered the seek never fired during an actual drag. Replaced with `GtkRange`'s native `change-value` signal, which fires for every user-driven move (drag, click-to-jump, arrow keys) without that conflict. Also fixes the slider's position display getting stuck after a drag, caused by a `seeking` flag that the broken release handler never cleared.

## v1.0.1

- Initial versioned release.
