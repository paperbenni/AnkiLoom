"""Small, strict AnkiConnect v6 client; mutations are deliberately never retried."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import LoomError


class AnkiConnect:
    def __init__(self, endpoint="http://127.0.0.1:8765", key=None, timeout=15):
        if urlparse(endpoint).scheme not in {"http", "https"}:
            raise LoomError("AnkiConnect URL must use http:// or https://.", "config")
        self.endpoint, self.key, self.timeout = endpoint, key, timeout

    def call(self, action, **params):
        payload = {"action": action, "version": 6, "params": params}
        if self.key:
            payload["key"] = self.key
        request = Request(
            self.endpoint, json.dumps(payload).encode(), {"Content-Type": "application/json"}
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            raise LoomError(
                f"AnkiConnect {action} failed at {self.endpoint}: {exc}. "
                "Open Anki desktop with AnkiConnect installed (add-on 2055492159). "
                "Check --url and ANKICONNECT_KEY. If a write timed out, rerun the same sync to recover.",
                "connection",
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise LoomError(
                f"AnkiConnect {action} returned invalid JSON; check --url.", "connection"
            ) from exc
        if not isinstance(result, dict) or "error" not in result or "result" not in result:
            raise LoomError(
                f"AnkiConnect {action} returned an unexpected response; check --url.", "connection"
            )
        if result["error"]:
            raise LoomError(f"AnkiConnect {action}: {result['error']}", "anki")
        return result["result"]

    def connect(self):
        version = self.call("version")
        if not isinstance(version, int) or version < 6:
            raise LoomError("AnkiConnect v6 or newer is required; update the add-on.", "connection")

    def note(self, note_id):
        result = self.call("notesInfo", notes=[note_id])
        if not result or not result[0] or not result[0].get("noteId"):
            raise LoomError(
                f"Anki note {note_id} no longer exists. Restore it from an Anki backup, "
                "or remove noteId AND loomId from the Markdown to deliberately create a new note.",
                "missing",
            )
        note = result[0]
        cards = self.call("cardsInfo", cards=note["cards"]) if note["cards"] else []
        return {
            "id": note["noteId"],
            "model": note["modelName"],
            "fields": {name: value["value"] for name, value in note["fields"].items()},
            "tags": sorted(note["tags"]),
            "cards": sorted(note["cards"]),
            "decks": sorted({c["deckName"] for c in cards}),
        }
