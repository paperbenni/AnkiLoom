"""Optional real-engine checks: uv run --with anki pytest tests/test_real_anki.py."""

import pytest

pytest.importorskip("anki")
from anki.collection import Collection

from ankiloom.cards import MODELS, parse_card
from ankiloom.sync import CSS, templates


@pytest.mark.parametrize(
    ("kind", "source", "count"),
    [
        ("basic", "Q $x$\n\n---\n\nA", 1),
        ("reverse", "Q\n\n---\n\n---\n\nA\n\n---\n\nExtra", 2),
        ("cloze", "~~1 Paris _city_~~ is in ~~2 France~~.", 2),
        ("type", "Capital?\n\n_Paris_", 1),
    ],
)
def test_real_anki_renders_generated_cards(tmp_path, kind, source, count):
    collection = Collection(str(tmp_path / "collection.anki2"))
    try:
        path = tmp_path / "card.md"
        path.write_text(source)
        card = parse_card(path, tmp_path)
        assert card.kind == kind
        model = collection.models.new(MODELS[kind])
        model["css"] = CSS
        model["type"] = 1 if kind == "cloze" else 0
        for name in card.fields:
            collection.models.add_field(model, collection.models.new_field(name))
        for spec in templates(kind):
            template = collection.models.new_template(spec["Name"])
            template["qfmt"], template["afmt"] = spec["Front"], spec["Back"]
            collection.models.add_template(model, template)
        collection.models.add(model)
        note = collection.new_note(model)
        for name, value in card.fields.items():
            note[name] = value
        collection.add_note(note, collection.decks.id("Test"))
        cards = note.cards()
        assert len(cards) == count
        for actual in cards:
            assert actual.question() and actual.answer()
            assert "{{" not in actual.question() and "{{" not in actual.answer()
        if kind == "cloze":
            assert "[city]" in cards[0].question()
            assert "Paris" in cards[0].answer()
        elif kind == "type":
            assert "[[type:Back]]" in cards[0].question()
    finally:
        collection.close()
