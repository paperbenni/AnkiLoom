"""Native note model definitions and bundled card styling."""

from importlib.resources import files

from .cards import MODELS
from .errors import LoomError

CSS = files("ankiloom").joinpath("default.css").read_text(encoding="utf-8")


def fields(kind):
    return ["Front", "Back"] + (["Extra"] if kind == "reverse" else [])


def templates(kind):
    if kind == "cloze":
        return [
            {"Name": "Cloze", "Front": "{{cloze:Front}}", "Back": "{{cloze:Front}}<br>{{Back}}"}
        ]
    if kind == "type":
        return [
            {
                "Name": "Type Answer",
                "Front": "{{Front}}<br>{{type:Back}}",
                "Back": "{{Front}}<hr>{{type:Back}}",
            }
        ]
    result = [
        {"Name": "Forward", "Front": "{{Front}}", "Back": "{{FrontSide}}<hr id=answer>{{Back}}"}
    ]
    if kind == "reverse":
        result[0]["Back"] += "<hr>{{Extra}}"
        result.append(
            {
                "Name": "Reverse",
                "Front": "{{Back}}",
                "Back": "{{FrontSide}}<hr id=answer>{{Front}}<hr>{{Extra}}",
            }
        )
    return result


def ensure_model(client, kind, available):
    name = MODELS[kind]
    expected = fields(kind)
    if name in available:
        actual = client.call("modelFieldNames", modelName=name)
        if actual != expected:
            raise LoomError(
                f"Model {name} has unexpected fields: {actual}; expected {expected}.", "model"
            )
    else:
        client.call(
            "createModel",
            modelName=name,
            inOrderFields=expected,
            css=CSS,
            isCloze=kind == "cloze",
            cardTemplates=templates(kind),
        )
        available.append(name)
