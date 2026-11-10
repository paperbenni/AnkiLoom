"""In-process HTTP AnkiConnect double with response-loss fault injection."""

import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class Collection:
    def __init__(self):
        self.notes = {}
        self.models = {}
        self.decks = {"Default"}
        self.calls = []
        self.next_id = 1000
        self.fail_after = None

    def note(self, model="Yanki - Basic", fields=None, deck="old", tags=None):
        self.next_id += 1
        note_id = self.next_id
        self.models.setdefault(model, {"fields": ["Front", "Back", "YankiNamespace"]})
        self.notes[note_id] = {
            "noteId": note_id,
            "modelName": model,
            "fields": fields
            or {"Front": "old front", "Back": "old back", "YankiNamespace": "Yanki"},
            "tags": tags or ["personal"],
            "cards": [note_id * 10],
            "deck": deck,
            "reviews": 42,
        }
        return note_id

    def action(self, action, p):
        self.calls.append(action)
        if action == "version":
            return 6
        if action == "findNotes":
            if p["query"].startswith("nid:"):
                note_id = int(p["query"][4:])
                return [note_id] if note_id in self.notes else []
            tag = p["query"][4:]
            return [i for i, n in self.notes.items() if tag in n["tags"]]
        if action == "notesInfo":
            result = []
            for note_id in p["notes"]:
                note = self.notes.get(note_id)
                if note:
                    value = deepcopy(note)
                    value["fields"] = {
                        k: {"value": v, "order": i}
                        for i, (k, v) in enumerate(note["fields"].items())
                    }
                    result.append(value)
                else:
                    result.append({})
            return result
        if action == "cardsInfo":
            return [
                {"cardId": c, "deckName": n["deck"]}
                for n in self.notes.values()
                for c in n["cards"]
                if c in p["cards"]
            ]
        if action == "modelNames":
            return list(self.models)
        if action == "modelFieldNames":
            return self.models[p["modelName"]]["fields"]
        if action == "deckNames":
            return sorted(self.decks)
        if action == "createDeck":
            self.decks.add(p["deck"])
            return 1
        if action == "createModel":
            self.models[p["modelName"]] = {"fields": p["inOrderFields"], **p}
            return p
        if action == "storeMediaFile":
            return p["filename"]
        if action == "addNote":
            n = p["note"]
            return self.note(n["modelName"], n["fields"], n["deckName"], n["tags"])
        if action == "updateNoteFields":
            n = p["note"]
            self.notes[n["id"]]["fields"].update(n["fields"])
        elif action == "changeDeck":
            for n in self.notes.values():
                if set(n["cards"]) & set(p["cards"]):
                    n["deck"] = p["deck"]
        elif action in {"addTags", "removeTags"}:
            for note_id in p["notes"]:
                tags = set(self.notes[note_id]["tags"])
                tags = (
                    tags | set(p["tags"].split())
                    if action == "addTags"
                    else tags - set(p["tags"].split())
                )
                self.notes[note_id]["tags"] = sorted(tags)
        elif action == "deleteNotes":
            for note_id in p["notes"]:
                self.notes.pop(note_id, None)
        elif action == "updateModelStyling":
            self.models[p["model"]["name"]]["css"] = p["model"]["css"]
        elif action == "sync":
            pass
        else:
            raise AssertionError(f"Unsupported action {action}")
        return None


@pytest.fixture
def server():
    collection = Collection()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                result = collection.action(request["action"], request.get("params", {}))
                if collection.fail_after == request["action"]:
                    collection.fail_after = None
                    self.connection.shutdown(2)
                    self.connection.close()
                    return
                response = {"result": result, "error": None}
            except (AssertionError, KeyError, ValueError, TypeError) as exc:
                response = {"result": None, "error": str(exc)}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield collection, f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()
