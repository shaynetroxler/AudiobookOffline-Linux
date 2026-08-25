from __future__ import annotations

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gst, Gtk, Pango

from . import covers, downloads
from .client import ABSClient, ABSError
from .credentials import ServerCredentials, load as load_creds, save as save_creds
from .models import LibraryItem
from .mpris import MprisService

Gst.init(None)

APP_VERSION = "1.0.1"
MAC_URL = "https://github.com/shaynetroxler/AudiobookOffline"
WINDOWS_URL = "https://github.com/shaynetroxler/AudiobookOffline-Windows"
LINUX_URL = "https://github.com/shaynetroxler/audiobookshelf-linux"

# A plain colored circle stands in for a platform-native "download status" dot:
# blue+arrow when a Continue Listening book isn't downloaded yet, green once it is.
_DOWNLOAD_INDICATOR_CSS = b"""
.download-indicator-needed {
    background-color: #3584e4;
    color: white;
    border-radius: 999px;
    min-width: 22px;
    min-height: 22px;
    padding: 0;
}
.download-indicator-done {
    background-color: #26a269;
    border-radius: 999px;
    min-width: 12px;
    min-height: 12px;
    padding: 0;
}
"""


def run_in_background(work, on_done):
    """Run `work()` off the main thread; deliver its result (or exception) to
    `on_done` back on the GTK main thread, since GTK widgets may only be
    touched from there."""

    def target():
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
            GLib.idle_add(on_done, None, exc)
        else:
            GLib.idle_add(on_done, result, None)

    threading.Thread(target=target, daemon=True).start()


class LoginPage(Gtk.Box):
    def __init__(self, on_success):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=48, margin_start=48, margin_end=48)
        self.on_success = on_success

        self.server_entry = Gtk.Entry(placeholder_text="Server URL, e.g. http://192.168.1.136:8092")
        self.username_entry = Gtk.Entry(placeholder_text="Username")
        self.password_entry = Gtk.PasswordEntry(show_peek_icon=True)
        self.status_label = Gtk.Label(label="", wrap=True)
        self.status_label.add_css_class("error")

        login_button = Gtk.Button(label="Log In")
        login_button.add_css_class("suggested-action")
        login_button.connect("clicked", self._on_login_clicked)

        for widget in (self.server_entry, self.username_entry, self.password_entry, login_button, self.status_label):
            self.append(widget)

    def _on_login_clicked(self, _button):
        server = self.server_entry.get_text().strip()
        username = self.username_entry.get_text().strip()
        password = self.password_entry.get_text()
        self.status_label.set_label("Logging in…")

        def work():
            client, token = ABSClient.login(server, username, password)
            save_creds(ServerCredentials(server_url=client.base_url, username=username, token=token))
            return client

        def done(client, error):
            if error is not None:
                self.status_label.set_label(str(error))
                return
            self.on_success(client)

        run_in_background(work, done)


class LibraryPage(Gtk.Box):
    def __init__(self, client: ABSClient, on_item_activated, on_stats_activated):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.client = client
        self.on_item_activated = on_item_activated
        self.on_stats_activated = on_stats_activated
        self.library_id = None
        self._all_items = []
        self._continue_items = []
        self._series_groups = []
        self._collection_groups = []
        self.browse_mode = "books"

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Search title or author…", hexpand=True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        header_row.append(self.search_entry)

        stats_button = Gtk.Button(label="📊 Stats")
        stats_button.connect("clicked", lambda _b: self.on_stats_activated())
        header_row.append(stats_button)
        self.append(header_row)

        browse_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER)
        browse_row.add_css_class("linked")
        self.books_toggle = Gtk.ToggleButton(label="Books", active=True)
        self.series_toggle = Gtk.ToggleButton(label="Series")
        self.series_toggle.set_group(self.books_toggle)
        self.collections_toggle = Gtk.ToggleButton(label="Collections")
        self.collections_toggle.set_group(self.books_toggle)
        for button, mode in ((self.books_toggle, "books"), (self.series_toggle, "series"), (self.collections_toggle, "collections")):
            button.connect("toggled", self._on_browse_mode_toggled, mode)
            browse_row.append(button)
        self.append(browse_row)

        # Continue Listening and the main book list live in one shared scroll
        # area so the shelf scrolls away with the rest of the page instead of
        # permanently eating window space (it has no bounded height of its own).
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller.set_child(content)
        self.append(scroller)

        self.continue_label = Gtk.Label(label="Continue Listening", xalign=0, visible=False)
        self.continue_label.add_css_class("heading")
        content.append(self.continue_label)

        self.continue_list = Gtk.ListBox(visible=False)
        self.continue_list.add_css_class("boxed-list")
        self.continue_list.connect("row-activated", self._on_row_activated)
        content.append(self.continue_list)

        self.status_label = Gtk.Label(label="Loading libraries…")
        content.append(self.status_label)

        self.list_box = Gtk.ListBox()
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect("row-activated", self._on_row_activated)
        content.append(self.list_box)

        run_in_background(self._load_first_library, self._on_items_loaded)

    def _load_first_library(self):
        libraries = self.client.libraries()
        if not libraries:
            return None, [], [], [], []
        library_id = libraries[0].id
        items = self.client.items(library_id)
        continue_items = self.client.continue_listening(library_id)
        series_groups = self.client.series(library_id)
        collection_groups = self.client.collections(library_id)
        return library_id, items, continue_items, series_groups, collection_groups

    def _on_items_loaded(self, result, error):
        if error is not None:
            self.status_label.set_label(f"Failed to load library: {error}")
            return
        library_id, items, continue_items, series_groups, collection_groups = result
        self.library_id = library_id
        self._all_items = items
        self._continue_items = continue_items
        self._series_groups = series_groups
        self._collection_groups = collection_groups
        self._populate_continue(continue_items)
        self.status_label.set_label(f"{len(items)} books")
        self._populate(items)

    def _make_row(self, item, removable=False):
        # Title and author are stacked (not side-by-side) and BOTH ellipsize, so
        # the only thing that can push a trailing button off the visible area
        # (a fixed-width sibling like author text refusing to shrink) can't
        # happen here -- the text column is the sole flexible element and the
        # remove button always gets its natural size first.
        author = item.metadata.author_name or "Unknown author"

        cover = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        cover.set_size_request(40, 56)
        self._load_cover(item, cover)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)

        title_label = Gtk.Label(label=item.metadata.title, xalign=0)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(title_label)

        author_label = Gtk.Label(label=author, xalign=0)
        author_label.add_css_class("dim-label")
        author_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(author_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        row.append(cover)
        row.append(text_box)

        if removable:
            row.append(self._make_download_indicator(item))
            remove_button = Gtk.Button(label="✕", tooltip_text="Remove from Continue Listening")
            remove_button.add_css_class("flat")
            remove_button.connect("clicked", lambda _b: self._on_remove_continue(item))
            row.append(remove_button)

        list_row = Gtk.ListBoxRow()
        list_row.set_child(row)
        list_row.item = item
        return list_row

    def _make_download_indicator(self, item):
        # Hidden until the background fetch below learns whether this item's
        # tracks are on disk -- there's no track list on the shelf's LibraryItem
        # itself, only on the fuller detail fetched here.
        button = Gtk.Button(label="", visible=False, valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.item_tracks = None
        button.connect("clicked", lambda _b: self._on_download_indicator_clicked(item, button))

        client = self.client

        def done(tracks, error):
            if error is not None or tracks is None:
                return
            button.item_tracks = tracks
            self._refresh_download_indicator(item, button)

        run_in_background(lambda: client.item_detail(item.id).tracks, done)
        return button

    def _refresh_download_indicator(self, item, button):
        tracks = button.item_tracks
        if tracks is None:
            return
        button.remove_css_class("download-indicator-needed")
        button.remove_css_class("download-indicator-done")
        if downloads.is_fully_downloaded(item.id, tracks):
            button.set_label("")
            button.add_css_class("download-indicator-done")
            button.set_tooltip_text("Downloaded for offline listening")
            # Let clicks fall through to the row underneath instead of the dot
            # eating them -- there's nothing left to do here but open the book.
            button.set_can_target(False)
        else:
            button.set_label("⬇")
            button.add_css_class("download-indicator-needed")
            button.set_tooltip_text("Download for offline listening")
            button.set_can_target(True)
        button.set_sensitive(True)
        button.set_visible(True)

    def _on_download_indicator_clicked(self, item, button):
        tracks = button.item_tracks
        if not tracks:
            return
        button.set_sensitive(False)
        client = self.client

        def progress(done, total):
            GLib.idle_add(button.set_label, f"{done}/{total}")

        def work():
            downloads.download_tracks(client, item.id, tracks, progress)

        def done(_result, error):
            if error is not None:
                button.set_label("⬇")
                button.set_tooltip_text("Download failed — tap to retry")
                button.set_sensitive(True)
                return
            self._refresh_download_indicator(item, button)

        run_in_background(work, done)

    def _load_cover(self, item, picture_widget):
        client = self.client

        def on_done(path):
            if path is not None:
                GLib.idle_add(picture_widget.set_filename, str(path))

        covers.fetch_async(client, item.id, on_done, width=80)

    def _populate(self, items):
        child = self.list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child
        for item in items:
            self.list_box.append(self._make_row(item))

    def _populate_continue(self, items):
        child = self.continue_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.continue_list.remove(child)
            child = next_child
        has_items = bool(items)
        self.continue_label.set_visible(has_items)
        self.continue_list.set_visible(has_items)
        for item in items:
            self.continue_list.append(self._make_row(item, removable=True))

    def _on_remove_continue(self, item):
        client = self.client
        run_in_background(
            lambda: client.hide_from_continue_listening(item.id),
            lambda _result, error: self._on_removed_from_continue(item, error),
        )

    def _on_removed_from_continue(self, item, error):
        if error is not None:
            self.status_label.set_label(f"Couldn't remove from Continue Listening: {error}")
            return
        self._continue_items = [i for i in self._continue_items if i.id != item.id]
        self._populate_continue(self._continue_items)

    def _on_row_activated(self, _list_box, row):
        if getattr(row, "is_back", False):
            groups = self._series_groups if self.browse_mode == "series" else self._collection_groups
            self._show_groups(groups, self.browse_mode)
            return
        group = getattr(row, "group", None)
        if group is not None:
            self._show_group_detail(group)
            return
        self.on_item_activated(row.item)

    def _on_browse_mode_toggled(self, button, mode):
        if not button.get_active():
            return
        self.browse_mode = mode
        if mode == "books":
            self.status_label.set_label(f"{len(self._all_items)} books")
            self._populate(self._all_items)
        elif mode == "series":
            self._show_groups(self._series_groups, "series")
        elif mode == "collections":
            self._show_groups(self._collection_groups, "collections")

    def _show_groups(self, groups, kind):
        self.status_label.set_label(f"{len(groups)} {kind}")
        child = self.list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child
        for group in groups:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
            name_label = Gtk.Label(label=group.name, xalign=0, hexpand=True)
            name_label.set_ellipsize(Pango.EllipsizeMode.END)
            count_label = Gtk.Label(label=f"{len(group.books)} books", xalign=1)
            count_label.add_css_class("dim-label")
            row_box.append(name_label)
            row_box.append(count_label)
            list_row = Gtk.ListBoxRow()
            list_row.set_child(row_box)
            list_row.group = group
            self.list_box.append(list_row)

    def _show_group_detail(self, group):
        self.status_label.set_label(f"{group.name} · {len(group.books)} books")
        child = self.list_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.list_box.remove(child)
            child = next_child

        back_box = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        back_box.append(Gtk.Label(label=f"← All {self.browse_mode.capitalize()}", xalign=0))
        back_row = Gtk.ListBoxRow()
        back_row.set_child(back_box)
        back_row.is_back = True
        self.list_box.append(back_row)

        for item in group.books:
            self.list_box.append(self._make_row(item))

    def _on_search_changed(self, entry):
        if self.library_id is None:
            return
        query = entry.get_text().strip()
        if not query:
            self.status_label.set_label(f"{len(self._all_items)} books")
            self._populate(self._all_items)
            return
        self.status_label.set_label("Searching…")
        run_in_background(lambda: self.client.search(self.library_id, query, limit=40), self._on_search_results)

    def _on_search_results(self, items, error):
        if error is not None:
            self.status_label.set_label(f"Search failed: {error}")
            return
        self.status_label.set_label(f"{len(items)} result{'s' if len(items) != 1 else ''}")
        self._populate(items)


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_duration_long(seconds: float) -> str:
    total_hours = seconds / 3600
    days, hours = divmod(int(total_hours), 24)
    return f"{days}d {hours}h" if days else f"{hours}h"


class PlayerPage(Gtk.Box):
    def __init__(self, client: ABSClient, item: LibraryItem, on_back, mpris=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24, margin_bottom=12, margin_start=24, margin_end=24)
        self.client = client
        self.item = item
        self.on_back = on_back
        self.mpris = mpris
        self.tracks = []
        self.total_duration = 0.0
        self.track_index = 0
        self.seeking = False
        self.chapters = []
        self.chapter_index = 0
        self.chapter_rows = []
        self.playback_rate = 1.0
        self._sleep_timer_source = None
        self._sleep_end_of_chapter = False
        self._sleep_deadline = None

        back_button = Gtk.Button(label="← Back")
        back_button.set_halign(Gtk.Align.START)
        back_button.connect("clicked", lambda _b: self._go_back())
        self.append(back_button)

        # Everything below scrolls as one unit -- a long title or a small
        # window can otherwise push the download button and its status text
        # below the visible area with no way to reach them (there's nothing
        # else here that provides scrolling on its own, unlike the library's
        # ListBoxes).
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroller.set_child(content)
        self.append(scroller)

        cover = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, halign=Gtk.Align.CENTER)
        cover.set_size_request(180, 180)

        def on_cover_done(path):
            if path is not None:
                GLib.idle_add(cover.set_filename, str(path))

        covers.fetch_async(client, item.id, on_cover_done, width=300)
        content.append(cover)

        title_label = Gtk.Label(label=item.metadata.title, wrap=True, justify=Gtk.Justification.CENTER)
        title_label.add_css_class("title-2")
        content.append(title_label)

        author_label = Gtk.Label(label=item.metadata.author_name or "Unknown author")
        author_label.add_css_class("dim-label")
        content.append(author_label)

        self.download_status_label = Gtk.Label(label="", visible=False)
        self.download_status_label.add_css_class("dim-label")
        self.download_status_label.add_css_class("caption")
        content.append(self.download_status_label)

        self.chapter_label = Gtk.Label(label="", wrap=True)
        self.chapter_label.add_css_class("dim-label")
        content.append(self.chapter_label)

        self.status_label = Gtk.Label(label="Loading…")
        content.append(self.status_label)

        self.position_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        self.position_scale.set_range(0, 1)
        self.position_scale.set_draw_value(False)
        self.position_scale.set_sensitive(False)
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", lambda *_a: setattr(self, "seeking", True))
        gesture.connect("released", self._on_seek_released)
        self.position_scale.add_controller(gesture)
        content.append(self.position_scale)

        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        self.elapsed_label = Gtk.Label(label="0:00", xalign=0, hexpand=True)
        self.remaining_label = Gtk.Label(label="0:00", xalign=1)
        time_row.append(self.elapsed_label)
        time_row.append(self.remaining_label)
        content.append(time_row)

        transport_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)

        self.prev_chapter_button = Gtk.Button(label="⏮ Chapter")
        self.prev_chapter_button.set_sensitive(False)
        self.prev_chapter_button.connect("clicked", lambda _b: self._jump_chapter(-1))
        transport_row.append(self.prev_chapter_button)

        self.skip_back_button = Gtk.Button(label="-30s")
        self.skip_back_button.set_sensitive(False)
        self.skip_back_button.connect("clicked", lambda _b: self._skip(-30))
        transport_row.append(self.skip_back_button)

        self.play_button = Gtk.Button(label="Play")
        self.play_button.add_css_class("suggested-action")
        self.play_button.set_sensitive(False)
        self.play_button.connect("clicked", lambda _b: self._toggle_play())
        transport_row.append(self.play_button)

        self.skip_forward_button = Gtk.Button(label="+30s")
        self.skip_forward_button.set_sensitive(False)
        self.skip_forward_button.connect("clicked", lambda _b: self._skip(30))
        transport_row.append(self.skip_forward_button)

        self.next_chapter_button = Gtk.Button(label="Chapter ⏭")
        self.next_chapter_button.set_sensitive(False)
        self.next_chapter_button.connect("clicked", lambda _b: self._jump_chapter(1))
        transport_row.append(self.next_chapter_button)

        content.append(transport_row)

        self.download_button = Gtk.Button(label="Download")
        self.download_button.set_sensitive(False)
        self.download_button.connect("clicked", self._on_download_clicked)
        self.download_button.set_halign(Gtk.Align.CENTER)
        content.append(self.download_button)

        options_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)

        self._speed_options = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        speed_model = Gtk.StringList.new([f"{s}×" for s in self._speed_options])
        self.speed_dropdown = Gtk.DropDown(model=speed_model, selected=self._speed_options.index(1.0))
        self.speed_dropdown.connect("notify::selected", self._on_speed_changed)
        options_row.append(self.speed_dropdown)

        self._sleep_options = [0, 5, 10, 15, 30, 45, 60, -1]
        sleep_model = Gtk.StringList.new(["Sleep: Off", "5 min", "10 min", "15 min", "30 min", "45 min", "60 min", "End of Chapter"])
        self.sleep_dropdown = Gtk.DropDown(model=sleep_model, selected=0)
        self.sleep_dropdown.connect("notify::selected", self._on_sleep_changed)
        sleep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER)
        sleep_box.append(self.sleep_dropdown)
        self.sleep_status_label = Gtk.Label(label="", visible=False, halign=Gtk.Align.CENTER)
        self.sleep_status_label.add_css_class("dim-label")
        self.sleep_status_label.add_css_class("caption")
        sleep_box.append(self.sleep_status_label)
        options_row.append(sleep_box)

        content.append(options_row)

        self.chapters_heading = Gtk.Label(label="", xalign=0, visible=False)
        self.chapters_heading.add_css_class("heading")
        self.chapters_heading.set_margin_top(12)
        content.append(self.chapters_heading)

        self.chapter_list = Gtk.ListBox(visible=False, selection_mode=Gtk.SelectionMode.SINGLE)
        self.chapter_list.add_css_class("boxed-list")
        self.chapter_list.connect("row-activated", self._on_chapter_row_activated)
        content.append(self.chapter_list)

        key_controller = Gtk.EventControllerKey()
        # BUBBLE (not the default TARGET) so spacebar keeps working after a
        # chapter row grabs focus for auto-scroll-into-view.
        key_controller.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

        self.playbin = Gst.ElementFactory.make("playbin", "player")
        scaletempo = Gst.ElementFactory.make("scaletempo", "scaletempo")
        if scaletempo is not None:
            self.playbin.set_property("audio-filter", scaletempo)
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self._tick_source = GLib.timeout_add(500, self._on_tick)
        self._report_source = GLib.timeout_add_seconds(20, self._periodic_report)

        def work():
            detail = client.item_detail(item.id)
            progress = client.media_progress().get(item.id)
            return detail, progress

        run_in_background(work, self._on_detail_loaded)

    def _on_detail_loaded(self, result, error):
        if error is not None:
            self.status_label.set_label(f"Failed to load book: {error}")
            return
        detail, progress = result
        self.tracks = detail.tracks
        if not self.tracks:
            self.status_label.set_label("This book has no playable tracks.")
            return
        self.chapters = detail.chapters
        self._populate_chapter_list()
        self.total_duration = sum(t.duration for t in self.tracks)
        self.status_label.set_label("")
        self.position_scale.set_sensitive(True)
        self.play_button.set_sensitive(True)
        self.skip_back_button.set_sensitive(True)
        self.skip_forward_button.set_sensitive(True)
        self.download_button.set_sensitive(True)
        self._refresh_download_button()
        if progress is not None and 0 < progress.current_time < self.total_duration and not progress.is_finished:
            index, offset = self._resolve_position(progress.current_time)
            self._load_track(index, autoplay=False, seek_offset=offset)
        else:
            self._load_track(0, autoplay=False)

    def _resolve_position(self, global_pos):
        remaining = global_pos
        for i, track in enumerate(self.tracks):
            if remaining < track.duration or i == len(self.tracks) - 1:
                return i, max(0.0, remaining)
            remaining -= track.duration
        return 0, 0.0

    def _track_start_offset(self, index):
        return sum(t.duration for t in self.tracks[:index])

    def _local_path(self, track):
        return downloads.track_path(self.item.id, track.index, track.mime_type)

    def _track_uri(self, track):
        local_path = self._local_path(track)
        if local_path.exists():
            return local_path.as_uri()
        return self.client.stream_url(track.content_url)

    def _refresh_download_button(self):
        if downloads.is_fully_downloaded(self.item.id, self.tracks):
            self.download_button.set_label("Remove Download")
            size = downloads.downloaded_size(self.item.id, self.tracks)
            self.download_status_label.set_label(f"Downloaded · {downloads.format_size(size)}")
            self.download_status_label.set_visible(True)
        else:
            self.download_button.set_label("Download")
            self.download_status_label.set_visible(False)

    def _on_download_clicked(self, _button):
        if downloads.is_fully_downloaded(self.item.id, self.tracks):
            downloads.delete_downloads(self.item.id)
            self._refresh_download_button()
            return

        self.download_button.set_sensitive(False)
        item_id, client, tracks = self.item.id, self.client, list(self.tracks)

        def progress(done, total):
            GLib.idle_add(self.download_button.set_label, f"Downloading {done}/{total}…")

        def work():
            downloads.download_tracks(client, item_id, tracks, progress)

        def done(_result, error):
            self.download_button.set_sensitive(True)
            if error is not None:
                self.download_button.set_label("Download failed — retry")
                return
            self._refresh_download_button()

        run_in_background(work, done)

    def _is_playing(self):
        _, state, _ = self.playbin.get_state(0)
        return state == Gst.State.PLAYING

    def _find_chapter_index(self, global_pos):
        for i, chapter in enumerate(self.chapters):
            if chapter.start <= global_pos < chapter.end:
                return i
        return len(self.chapters) - 1

    def _sync_chapter_ui(self, global_pos):
        self.chapter_index = self._find_chapter_index(global_pos)
        chapter = self.chapters[self.chapter_index]
        if len(self.chapters) > 1:
            self.chapter_label.set_label(f"Chapter {self.chapter_index + 1} of {len(self.chapters)}: {chapter.title}")
        else:
            self.chapter_label.set_label(chapter.title)
        self.position_scale.set_range(0, max(0.01, chapter.end - chapter.start))
        rel = global_pos - chapter.start
        self.position_scale.set_value(rel)
        self.elapsed_label.set_label(format_time(rel))
        self.remaining_label.set_label(f"-{format_time(chapter.end - global_pos)}")
        self.prev_chapter_button.set_sensitive(self.chapter_index > 0)
        self.next_chapter_button.set_sensitive(self.chapter_index < len(self.chapters) - 1)
        if self.chapter_rows:
            # select_row() only, no grab_focus(): focusing a row inside the
            # scroll area made GTK's built-in "Space scrolls the page" key
            # binding fire alongside our own play/pause handler.
            self.chapter_list.select_row(self.chapter_rows[self.chapter_index])

    def _populate_chapter_list(self):
        child = self.chapter_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.chapter_list.remove(child)
            child = next_child
        self.chapter_rows = []

        if len(self.chapters) <= 1:
            self.chapters_heading.set_visible(False)
            self.chapter_list.set_visible(False)
            return

        self.chapters_heading.set_label(f"Chapters ({len(self.chapters)})")
        self.chapters_heading.set_visible(True)
        self.chapter_list.set_visible(True)
        for i, chapter in enumerate(self.chapters):
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
            title_label = Gtk.Label(label=f"{i + 1}. {chapter.title}", xalign=0, hexpand=True)
            title_label.set_ellipsize(Pango.EllipsizeMode.END)
            duration_label = Gtk.Label(label=format_time(chapter.end - chapter.start), xalign=1)
            duration_label.add_css_class("dim-label")
            row_box.append(title_label)
            row_box.append(duration_label)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            row.chapter_index = i
            self.chapter_list.append(row)
            self.chapter_rows.append(row)

    def _on_chapter_row_activated(self, _list_box, row):
        chapter = self.chapters[row.chapter_index]
        self._seek_to_global(chapter.start, autoplay=self._is_playing())

    def _load_track(self, index, autoplay, seek_offset=0):
        self.track_index = index
        track = self.tracks[index]
        self.playbin.set_state(Gst.State.NULL)
        self.playbin.set_property("uri", self._track_uri(track))
        self.playbin.set_state(Gst.State.PAUSED)
        if seek_offset > 0 or self.playback_rate != 1.0:
            # Block until the pipeline prerolls so the seek lands on a pipeline
            # that actually has a position to seek within (a network source
            # queued straight from NULL silently drops a seek issued too early).
            self.playbin.get_state(Gst.CLOCK_TIME_NONE)
            self.playbin.seek(
                self.playback_rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                Gst.SeekType.SET, int(seek_offset * Gst.SECOND), Gst.SeekType.NONE, -1,
            )
        self._sync_chapter_ui(self._track_start_offset(index) + seek_offset)
        if autoplay:
            self.playbin.set_state(Gst.State.PLAYING)
        self.play_button.set_label("Pause" if autoplay else "Play")
        if self.mpris is not None:
            self.mpris.notify()

    def _seek_to_global(self, global_pos, autoplay):
        index, offset = self._resolve_position(global_pos)
        if index == self.track_index:
            self.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(offset * Gst.SECOND))
            self._sync_chapter_ui(global_pos)
        else:
            self._load_track(index, autoplay=autoplay, seek_offset=offset)
        if self.mpris is not None:
            self.mpris.seeked(int(global_pos * 1_000_000))

    def _jump_chapter(self, direction):
        target = self.chapter_index + direction
        if not (0 <= target < len(self.chapters)):
            return
        self._seek_to_global(self.chapters[target].start, autoplay=self._is_playing())

    def _skip(self, seconds):
        if not self.tracks:
            return
        ok, position = self.playbin.query_position(Gst.Format.TIME)
        if not ok:
            return
        current_global = self._track_start_offset(self.track_index) + position / Gst.SECOND
        target = min(max(0.0, current_global + seconds), self.total_duration - 0.1)
        self._seek_to_global(target, autoplay=self._is_playing())

    def _toggle_play(self):
        if not self.tracks:
            return
        if self._is_playing():
            self.playbin.set_state(Gst.State.PAUSED)
            self.play_button.set_label("Play")
            self._report_progress()
        else:
            self.playbin.set_state(Gst.State.PLAYING)
            self.play_button.set_label("Pause")
        if self.mpris is not None:
            self.mpris.notify()

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == 32:  # spacebar
            self._toggle_play()
            return True
        return False

    def _on_seek_released(self, _gesture, _n_press, _x, _y):
        self.seeking = False
        chapter = self.chapters[self.chapter_index]
        self._seek_to_global(chapter.start + self.position_scale.get_value(), autoplay=self._is_playing())

    def _on_speed_changed(self, dropdown, _pspec):
        self.playback_rate = self._speed_options[dropdown.get_selected()]
        if not self.tracks:
            return
        ok, position = self.playbin.query_position(Gst.Format.TIME)
        if not ok:
            return
        self.playbin.seek(
            self.playback_rate, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            Gst.SeekType.SET, position, Gst.SeekType.NONE, -1,
        )

    def _on_sleep_changed(self, dropdown, _pspec):
        if self._sleep_timer_source is not None:
            GLib.source_remove(self._sleep_timer_source)
            self._sleep_timer_source = None
        self._sleep_end_of_chapter = False
        self._sleep_deadline = None
        choice = self._sleep_options[dropdown.get_selected()]
        if choice == 0:
            self.sleep_status_label.set_visible(False)
            return
        if choice == -1:
            self._sleep_end_of_chapter = True
            self.sleep_status_label.set_visible(True)
            self._update_sleep_countdown()
            return
        self._sleep_deadline = time.monotonic() + choice * 60
        self.sleep_status_label.set_visible(True)
        self._update_sleep_countdown()
        self._sleep_timer_source = GLib.timeout_add_seconds(choice * 60, self._on_sleep_fire)

    def _update_sleep_countdown(self):
        if self._sleep_deadline is not None:
            remaining = max(0.0, self._sleep_deadline - time.monotonic())
            self.sleep_status_label.set_label(f"Sleeping in {format_time(remaining)}")
        elif self._sleep_end_of_chapter and self.chapters:
            ok, position = self.playbin.query_position(Gst.Format.TIME)
            if not ok:
                return
            chapter = self.chapters[self.chapter_index]
            global_pos = self._track_start_offset(self.track_index) + position / Gst.SECOND
            remaining = max(0.0, chapter.end - global_pos)
            self.sleep_status_label.set_label(f"Sleeping at end of chapter ({format_time(remaining)})")

    def _on_sleep_fire(self):
        self._sleep_timer_source = None
        self.sleep_dropdown.set_selected(0)
        self._pause_for_sleep()
        return False

    def _pause_for_sleep(self):
        if self._is_playing():
            self.playbin.set_state(Gst.State.PAUSED)
            self.play_button.set_label("Play")
            self._report_progress()

    def _on_tick(self):
        self._update_sleep_countdown()
        if not self.tracks or self.seeking:
            return True
        ok, position = self.playbin.query_position(Gst.Format.TIME)
        if not ok:
            return True
        global_pos = self._track_start_offset(self.track_index) + position / Gst.SECOND
        chapter_idx = self._find_chapter_index(global_pos)
        if chapter_idx != self.chapter_index:
            if self._sleep_end_of_chapter:
                self._sleep_end_of_chapter = False
                self.sleep_dropdown.set_selected(0)
                self._pause_for_sleep()
            self._sync_chapter_ui(global_pos)
        else:
            chapter = self.chapters[self.chapter_index]
            rel = global_pos - chapter.start
            self.position_scale.set_value(rel)
            self.elapsed_label.set_label(format_time(rel))
            self.remaining_label.set_label(f"-{format_time(chapter.end - global_pos)}")
        if self.mpris is not None:
            self.mpris.notify()
        return True

    def _on_bus_message(self, _bus, message):
        if message.type == Gst.MessageType.EOS:
            if self.track_index + 1 < len(self.tracks):
                self._load_track(self.track_index + 1, autoplay=True)
            else:
                self.playbin.set_state(Gst.State.PAUSED)
                self.play_button.set_label("Play")
                self._report_progress(is_finished=True)
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self.status_label.set_label(f"Playback error: {error}")

    def _periodic_report(self):
        _, state, _ = self.playbin.get_state(0)
        if state == Gst.State.PLAYING:
            self._report_progress()
        return True

    def _report_progress(self, is_finished=False):
        if not self.tracks:
            return
        ok, position = self.playbin.query_position(Gst.Format.TIME)
        if not ok:
            return
        global_pos = self._track_start_offset(self.track_index) + position / Gst.SECOND
        item_id, client, total_duration = self.item.id, self.client, self.total_duration
        run_in_background(
            lambda: client.update_progress(item_id, global_pos, total_duration, is_finished),
            lambda _result, _error: None,
        )

    def _go_back(self):
        self._report_progress()
        self.playbin.set_state(Gst.State.NULL)
        GLib.source_remove(self._tick_source)
        GLib.source_remove(self._report_source)
        if self._sleep_timer_source is not None:
            GLib.source_remove(self._sleep_timer_source)
        self.on_back()


class StatsPage(Gtk.Box):
    def __init__(self, client: ABSClient, library_id: str | None, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24, margin_bottom=12, margin_start=24, margin_end=24)

        back_button = Gtk.Button(label="← Back")
        back_button.set_halign(Gtk.Align.START)
        back_button.connect("clicked", lambda _b: on_back())
        self.append(back_button)

        title = Gtk.Label(label="Library Stats")
        title.add_css_class("title-2")
        self.append(title)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        scroller.set_child(self.content)
        self.append(scroller)

        self.status_label = Gtk.Label(label="Loading…")
        self.content.append(self.status_label)

        if library_id is None:
            self.status_label.set_label("Library not loaded yet — go back and try again.")
            return

        run_in_background(lambda: client.library_stats(library_id), self._on_stats_loaded)

    def _on_stats_loaded(self, stats, error):
        if error is not None:
            self.status_label.set_label(f"Failed to load stats: {error}")
            return
        self.status_label.set_visible(False)

        overview = Gtk.Grid(column_spacing=24, row_spacing=6, margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        overview.add_css_class("card")
        rows = [
            ("Books", str(stats.total_items)),
            ("Authors", str(stats.total_authors)),
            ("Genres", str(stats.total_genres)),
            ("Audio tracks", str(stats.num_tracks)),
            ("Total listening time", format_duration_long(stats.total_duration)),
            ("Total size", downloads.format_size(stats.total_size)),
        ]
        for i, (label, value) in enumerate(rows):
            label_widget = Gtk.Label(label=label, xalign=0)
            label_widget.add_css_class("dim-label")
            value_widget = Gtk.Label(label=value, xalign=1, hexpand=True)
            value_widget.add_css_class("title-4")
            overview.attach(label_widget, 0, i, 1, 1)
            overview.attach(value_widget, 1, i, 1, 1)
        self.content.append(overview)

        self.content.append(self._section("Top 10 Authors", [(a.name, f"{a.count} books") for a in stats.top_authors]))
        self.content.append(self._section("Top 5 Genres", [(g.genre, f"{g.count} books") for g in stats.top_genres[:5]]))
        self.content.append(self._section("Longest Books", [(i.title, format_time(i.value)) for i in stats.longest_items]))
        self.content.append(self._section("Largest Books", [(i.title, downloads.format_size(int(i.value))) for i in stats.largest_items]))

    @staticmethod
    def _section(heading_text, rows):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = Gtk.Label(label=heading_text, xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        for title, value in rows:
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=2,
                margin_top=6, margin_bottom=6, margin_start=12, margin_end=12,
            )
            title_label = Gtk.Label(label=title, xalign=0, wrap=True, justify=Gtk.Justification.LEFT)
            row_box.append(title_label)
            value_label = Gtk.Label(label=value, xalign=0)
            value_label.add_css_class("dim-label")
            row_box.append(value_label)
            row = Gtk.ListBoxRow(activatable=False)
            row.set_child(row_box)
            list_box.append(row)
        box.append(list_box)
        return box


class HelpWindow(Adw.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, title="Help", default_width=440, default_height=520)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=16,
            margin_top=16, margin_bottom=16, margin_start=20, margin_end=20,
        )
        scroller.set_child(content)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        content.append(self._section(
            "Downloading for offline listening",
            "Open a book and tap Download to save it to this device, or Remove Download to free up space.\n\n"
            "On the Continue Listening shelf, each book also shows a status dot: a blue ⬇ means it hasn't "
            "been downloaded yet — tap it to download without opening the book. A green dot means it's "
            "already downloaded and ready to take with you.",
        ))
        content.append(self._section(
            "Sleep timer",
            "Pick a duration (or \"End of Chapter\") from the Sleep dropdown while playing. The label "
            "underneath counts down how much listening time is left before playback pauses itself.",
        ))

        other_heading = Gtk.Label(label="Other platforms", xalign=0)
        other_heading.add_css_class("heading")
        content.append(other_heading)
        other_label = Gtk.Label(
            label=f'Audiobook Offline is also available for <a href="{MAC_URL}">macOS</a> '
                  f'and <a href="{WINDOWS_URL}">Windows</a>.',
            use_markup=True, wrap=True, xalign=0,
        )
        content.append(other_label)

    @staticmethod
    def _section(heading_text, body_text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = Gtk.Label(label=heading_text, xalign=0)
        heading.add_css_class("heading")
        box.append(heading)
        body = Gtk.Label(label=body_text, xalign=0, wrap=True, justify=Gtk.Justification.LEFT)
        box.append(body)
        return box


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Audiobook Offline", default_width=480, default_height=640)
        self.set_icon_name("org.shayne.AudiobookOffline")
        self.stack = Gtk.Stack()

        menu = Gio.Menu()
        menu.append("Help", "app.help")
        menu.append("About Audiobook Offline", "app.about")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Main Menu")

        header = Adw.HeaderBar()
        header.pack_end(menu_button)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)
        toolbar_view.set_content(self.stack)
        self.set_content(toolbar_view)

        self.active_player = None
        self.mpris = MprisService(
            get_status=self._mpris_status,
            get_metadata=self._mpris_metadata,
            get_position_us=self._mpris_position_us,
            actions={
                "play": self._mpris_play,
                "pause": self._mpris_pause,
                "play_pause": self._mpris_play_pause,
                "next": self._mpris_next,
                "previous": self._mpris_previous,
                "seek": self._mpris_seek,
                "set_position": self._mpris_set_position,
            },
        )

        self.client = None
        creds = load_creds()
        if creds is not None:
            self.client = ABSClient(creds.server_url, creds.token)
            self.stack.add_named(LibraryPage(self.client, self._on_item_activated, self._on_stats_activated), "library")
        else:
            self.stack.add_named(LoginPage(self._on_logged_in), "login")

    def _on_logged_in(self, client: ABSClient):
        self.client = client
        self.stack.add_named(LibraryPage(client, self._on_item_activated, self._on_stats_activated), "library")
        self.stack.set_visible_child_name("library")

    def _on_item_activated(self, item):
        old_player = self.stack.get_child_by_name("player")
        if old_player is not None:
            self.stack.remove(old_player)
        player = PlayerPage(self.client, item, self._show_library, mpris=self.mpris)
        self.active_player = player
        self.stack.add_named(player, "player")
        self.stack.set_visible_child_name("player")

    def _on_stats_activated(self):
        old_stats = self.stack.get_child_by_name("stats")
        if old_stats is not None:
            self.stack.remove(old_stats)
        library_page = self.stack.get_child_by_name("library")
        self.stack.add_named(StatsPage(self.client, library_page.library_id, self._show_library), "stats")
        self.stack.set_visible_child_name("stats")

    def _show_library(self):
        self.active_player = None
        self.mpris.notify()
        self.stack.set_visible_child_name("library")

    def _mpris_status(self):
        p = self.active_player
        if p is None or not p.tracks:
            return "Stopped"
        return "Playing" if p._is_playing() else "Paused"

    def _mpris_metadata(self):
        p = self.active_player
        if p is None or not p.tracks:
            return None
        return {
            "title": p.item.metadata.title,
            "artist": p.item.metadata.author_name or "",
            "length_us": int(p.total_duration * 1_000_000),
            "track_id": f"/org/audiobookoffline/track/{p.item.id.replace('-', '_')}",
        }

    def _mpris_position_us(self):
        p = self.active_player
        if p is None or not p.tracks:
            return 0
        ok, pos = p.playbin.query_position(Gst.Format.TIME)
        if not ok:
            return 0
        return int((p._track_start_offset(p.track_index) + pos / Gst.SECOND) * 1_000_000)

    def _mpris_play(self):
        if self.active_player is not None and not self.active_player._is_playing():
            self.active_player._toggle_play()

    def _mpris_pause(self):
        if self.active_player is not None and self.active_player._is_playing():
            self.active_player._toggle_play()

    def _mpris_play_pause(self):
        if self.active_player is not None:
            self.active_player._toggle_play()

    def _mpris_next(self):
        if self.active_player is not None:
            self.active_player._jump_chapter(1)

    def _mpris_previous(self):
        if self.active_player is not None:
            self.active_player._jump_chapter(-1)

    def _mpris_seek(self, offset_us):
        p = self.active_player
        if p is None:
            return
        target = max(0.0, (self._mpris_position_us() + offset_us) / 1_000_000)
        p._seek_to_global(target, autoplay=p._is_playing())

    def _mpris_set_position(self, _track_id, position_us):
        p = self.active_player
        if p is None:
            return
        p._seek_to_global(position_us / 1_000_000, autoplay=p._is_playing())


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.shayne.AudiobookOffline")
        for name, handler in (("help", self._on_help), ("about", self._on_about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(_DOWNLOAD_INDICATOR_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_activate(self):
        # GApplication routes a second launch to this same do_activate() on the
        # already-running primary instance -- without this check it would spawn
        # a whole separate MainWindow each time instead of just refocusing.
        window = self.get_active_window()
        if window is None:
            window = MainWindow(self)
        window.present()

    def _on_help(self, _action, _param):
        HelpWindow(self.get_active_window()).present()

    def _on_about(self, _action, _param):
        about = Adw.AboutWindow(
            transient_for=self.get_active_window(),
            application_name="Audiobook Offline",
            application_icon="org.shayne.AudiobookOffline",
            version=APP_VERSION,
            developer_name="Shayne Troxler",
            license_type=Gtk.License.MIT_X11,
            copyright="© 2026 Shayne Troxler",
            website=LINUX_URL,
            issue_url=f"{LINUX_URL}/issues",
            comments="A Linux client for Audiobookshelf with true offline downloads.",
        )
        about.add_link("macOS version", MAC_URL)
        about.add_link("Windows version", WINDOWS_URL)
        about.present()


def main():
    Application().run(None)


if __name__ == "__main__":
    main()
