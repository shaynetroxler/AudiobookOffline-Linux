from __future__ import annotations

from gi.repository import Gio, GLib

BUS_NAME = "org.mpris.MediaPlayer2.audiobookoffline"
OBJECT_PATH = "/org/mpris/MediaPlayer2"

_INTROSPECTION_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Play"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Seek">
      <arg direction="in" type="x" name="Offset"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" type="o" name="TrackId"/>
      <arg direction="in" type="x" name="Position"/>
    </method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
    <signal name="Seeked">
      <arg type="x" name="Position"/>
    </signal>
  </interface>
</node>
"""


class MprisService:
    """Exposes an org.mpris.MediaPlayer2 D-Bus service so desktop media
    controls (GNOME Shell, waybar, media keys, playerctl) can see and
    control playback. `actions` is a dict of callables: play, pause,
    play_pause, next, previous, seek(offset_us), set_position(track_id, position_us)."""

    def __init__(self, get_status, get_metadata, get_position_us, actions):
        self._get_status = get_status
        self._get_metadata = get_metadata
        self._get_position_us = get_position_us
        self._actions = actions
        self._connection = None
        self._last_status = None
        self._last_track_id = None

        node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
        self._root_iface = node_info.lookup_interface("org.mpris.MediaPlayer2")
        self._player_iface = node_info.lookup_interface("org.mpris.MediaPlayer2.Player")

        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE, self._on_bus_acquired, None, None)

    def _on_bus_acquired(self, connection, _name):
        self._connection = connection
        connection.register_object(OBJECT_PATH, self._root_iface, self._handle_root_call, self._get_root_property, None)
        connection.register_object(OBJECT_PATH, self._player_iface, self._handle_player_call, self._get_player_property, None)

    def _handle_root_call(self, _connection, _sender, _path, _iface, method, _params, invocation):
        invocation.return_value(None)

    def _get_root_property(self, _connection, _sender, _path, _iface, prop_name):
        values = {
            "CanQuit": GLib.Variant("b", False),
            "CanRaise": GLib.Variant("b", False),
            "HasTrackList": GLib.Variant("b", False),
            "Identity": GLib.Variant("s", "Audiobook Offline"),
            "SupportedUriSchemes": GLib.Variant("as", []),
            "SupportedMimeTypes": GLib.Variant("as", []),
        }
        return values.get(prop_name)

    def _handle_player_call(self, _connection, _sender, _path, _iface, method, params, invocation):
        try:
            if method == "Play":
                self._actions["play"]()
            elif method == "Pause":
                self._actions["pause"]()
            elif method == "PlayPause":
                self._actions["play_pause"]()
            elif method == "Stop":
                self._actions["pause"]()
            elif method == "Next":
                self._actions["next"]()
            elif method == "Previous":
                self._actions["previous"]()
            elif method == "Seek":
                (offset,) = params.unpack()
                self._actions["seek"](offset)
            elif method == "SetPosition":
                track_id, position = params.unpack()
                self._actions["set_position"](track_id, position)
        finally:
            invocation.return_value(None)

    def _metadata_variant(self):
        meta = self._get_metadata()
        builder = GLib.VariantBuilder(GLib.VariantType.new("a{sv}"))
        if meta is not None:
            builder.add_value(GLib.Variant("{sv}", ("mpris:trackid", GLib.Variant("o", meta["track_id"]))))
            builder.add_value(GLib.Variant("{sv}", ("mpris:length", GLib.Variant("x", meta["length_us"]))))
            builder.add_value(GLib.Variant("{sv}", ("xesam:title", GLib.Variant("s", meta["title"]))))
            builder.add_value(GLib.Variant("{sv}", ("xesam:artist", GLib.Variant("as", [meta["artist"]]))))
        return builder.end()

    def _get_player_property(self, _connection, _sender, _path, _iface, prop_name):
        if prop_name == "PlaybackStatus":
            return GLib.Variant("s", self._get_status())
        if prop_name == "Position":
            return GLib.Variant("x", self._get_position_us())
        if prop_name == "Metadata":
            return self._metadata_variant()
        simple = {
            "Rate": GLib.Variant("d", 1.0),
            "MinimumRate": GLib.Variant("d", 0.75),
            "MaximumRate": GLib.Variant("d", 2.0),
            "Volume": GLib.Variant("d", 1.0),
            "CanGoNext": GLib.Variant("b", True),
            "CanGoPrevious": GLib.Variant("b", True),
            "CanPlay": GLib.Variant("b", True),
            "CanPause": GLib.Variant("b", True),
            "CanSeek": GLib.Variant("b", True),
            "CanControl": GLib.Variant("b", True),
        }
        return simple.get(prop_name)

    def notify(self):
        """Call after playback status or the active track changes."""
        if self._connection is None:
            return
        status = self._get_status()
        meta = self._get_metadata()
        track_id = meta["track_id"] if meta else None
        if status == self._last_status and track_id == self._last_track_id:
            return
        self._last_status = status
        self._last_track_id = track_id
        changed = GLib.VariantBuilder(GLib.VariantType.new("a{sv}"))
        changed.add_value(GLib.Variant("{sv}", ("PlaybackStatus", GLib.Variant("s", status))))
        changed.add_value(GLib.Variant("{sv}", ("Metadata", self._metadata_variant())))
        # Built from real Variant objects via new_tuple rather than a format-string
        # constructor: GLib.Variant("(sa{sv}as)", (...)) can't take an already-built
        # a{sv} Variant (from changed.end()) as a tuple element -- it tries to
        # re-iterate it as a plain dict and raises KeyError.
        signal_params = GLib.Variant.new_tuple(
            GLib.Variant("s", "org.mpris.MediaPlayer2.Player"),
            changed.end(),
            GLib.Variant("as", []),
        )
        self._connection.emit_signal(None, OBJECT_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged", signal_params)

    def seeked(self, position_us):
        if self._connection is None:
            return
        self._connection.emit_signal(
            None, OBJECT_PATH, "org.mpris.MediaPlayer2.Player", "Seeked", GLib.Variant("(x)", (position_us,)),
        )
