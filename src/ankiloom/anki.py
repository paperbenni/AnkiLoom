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

    def find_identities(self, identities: list[str]) -> dict[str, list[int]]:
        """Batch read-only identity lookups; never batch or retry mutations."""
        matches = {}
        for offset in range(0, len(identities), 100):
            batch = identities[offset : offset + 100]
            results = self.call(
                "multi",
                actions=[
                    {"action": "findNotes", "version": 6, "params": {"query": f"tag:{identity}"}}
                    for identity in batch
                ],
            )
            if not isinstance(results, list) or len(results) != len(batch):
                raise LoomError(
                    "AnkiConnect multi returned an unexpected identity response.", "connection"
                )
            for identity, response in zip(batch, results):
                if (
                    not isinstance(response, dict)
                    or "error" not in response
                    or "result" not in response
                ):
                    raise LoomError(
                        "AnkiConnect multi returned an invalid findNotes response.", "connection"
                    )
                if response["error"]:
                    raise LoomError(f"AnkiConnect findNotes: {response['error']}", "anki")
                if not isinstance(response["result"], list):
                    raise LoomError(
                        "AnkiConnect findNotes did not return a list of note IDs.", "connection"
                    )
                matches[identity] = response["result"]
        return matches

    def notes(self, note_ids: list[int]) -> dict[int, dict]:
        """Read note fields and card decks in batches instead of two requests per note."""
        notes = {}
        ids = sorted(set(note_ids))
        for offset in range(0, len(ids), 100):
            result = self.call("notesInfo", notes=ids[offset : offset + 100])
            found = [note for note in result if note and note.get("noteId")]
            card_ids = [card_id for note in found for card_id in note["cards"]]
            cards = self.call("cardsInfo", cards=card_ids) if card_ids else []
            decks = {card["cardId"]: card["deckName"] for card in cards}
            for note in found:
                notes[note["noteId"]] = {
                    "id": note["noteId"],
                    "model": note["modelName"],
                    "fields": {name: value["value"] for name, value in note["fields"].items()},
                    "tags": sorted(note["tags"]),
                    "cards": sorted(note["cards"]),
                    "decks": sorted({decks[card_id] for card_id in note["cards"]}),
                }
        return notes

    @staticmethod
    def require_note(notes: dict[int, dict], note_id: int) -> dict:
        if note_id not in notes:
            raise LoomError(
                f"Anki note {note_id} no longer exists. Restore it from an Anki backup, "
                "or remove noteId AND loomId from the Markdown to deliberately create a new note.",
                "missing",
            )
        return notes[note_id]

    def note(self, note_id):
        return self.require_note(self.notes([note_id]), note_id)
