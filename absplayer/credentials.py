from __future__ import annotations

import json
from dataclasses import dataclass

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret

_SCHEMA = Secret.Schema.new(
    "org.shayne.AudiobookOffline",
    Secret.SchemaFlags.NONE,
    {"service": Secret.SchemaAttributeType.STRING},
)
_ATTRIBUTES = {"service": "abs-credentials"}


@dataclass
class ServerCredentials:
    server_url: str
    username: str
    token: str


def save(creds: ServerCredentials) -> None:
    Secret.password_store_sync(
        _SCHEMA,
        _ATTRIBUTES,
        Secret.COLLECTION_DEFAULT,
        "Audiobookshelf credentials",
        json.dumps(creds.__dict__),
        None,
    )


def load() -> ServerCredentials | None:
    raw = Secret.password_lookup_sync(_SCHEMA, _ATTRIBUTES, None)
    if raw is None:
        return None
    return ServerCredentials(**json.loads(raw))


def clear() -> None:
    Secret.password_clear_sync(_SCHEMA, _ATTRIBUTES, None)
