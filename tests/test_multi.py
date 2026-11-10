"""Odd Markdown and interrupted writes in documents containing several notes."""

import json
from copy import deepcopy

import pytest
from test_sync import invoke

from ankiloom.cards import parse_document, scan
from ankiloom.errors import LoomError
from ankiloom.storage import write_metadata

HEADER = "---\nankiloom: multi\ntags: [study/topic]\n---\n"


def document(root, body, name="study.md"):
    path = root / name
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_mixed_forms_and_all_section_note_types(tmp_path):
    document(
        tmp_path,
        """# Study sheet

Ordinary prose stays outside cards.
Capital? :: **Paris**
Planet? :: Jupiter

## Why seasons?

---

Axial tilt.

## ~~1 Oxygen~~ has symbol ~~2 O~~.

## Translate oxygen

---

---

Oxygène

---

Extra

## Type the capital

_Paris_

# More quick cards

Ocean? :: Pacific
""",
    )
    cards = scan(tmp_path)
    assert [c.kind for c in cards] == [
        "basic",
        "basic",
        "basic",
        "cloze",
        "reverse",
        "type",
        "basic",
    ]
    assert all(c.tags == ["study::topic"] for c in cards)
    assert all("Ordinary prose" not in c.fields["Front"] for c in cards)
    assert "<strong>Paris</strong>" in cards[0].fields["Back"]
    assert "Why seasons?" in cards[2].fields["Front"]
    assert "{{c2::O}}" in cards[3].fields["Front"]
    assert "Extra" in cards[4].fields["Extra"]
    assert "Paris" not in cards[5].fields["Front"]


@pytest.mark.parametrize(
    "protected",
    [
        "`literal :: delimiter`",
        "$x :: y$",
        "*emphasis :: text*",
        "**strong :: text**",
        "~~strike :: text~~",
        "[link :: label](https://example.com)",
        "![alt :: text](https://example.com/image.png)",
        r"escaped \:: text",
        '<span title="x :: y">HTML</span>',
        '<span title="<!-- ankiloom noteId: 123 -->">HTML</span>',
    ],
)
def test_inline_protection_in_quick_cards(tmp_path, protected):
    document(tmp_path, f"{protected} :: Answer\n")
    cards = scan(tmp_path)
    assert len(cards) == 1
    assert "Answer" in cards[0].fields["Back"]
    assert cards[0].kind == "basic"


def test_quick_cards_are_always_basic(tmp_path):
    document(tmp_path, "~~hidden~~ :: _formatted answer_\n")
    card = scan(tmp_path)[0]
    assert card.kind == "basic"
    assert "<s>hidden</s>" in card.fields["Front"]
    assert "<em>formatted answer</em>" in card.fields["Back"]


def test_non_card_blocks_and_multiline_inline_code_are_ignored(tmp_path):
    document(
        tmp_path,
        """# Notes

```markdown
## Fake heading
Q :: A
<!-- ankiloom noteId: 99 -->
```

$$
Q :: A
$$

> ## Quoted heading
> Q :: A

- Q :: A

| Question | Answer |
| --- | --- |
| Q :: A | X |

<div>
Q :: A
</div>

`multiline code
Q :: A
ends here`

Real :: Answer
""",
    )
    cards = scan(tmp_path)
    assert len(cards) == 1 and "Real" in cards[0].fields["Front"]


def test_quick_looking_text_and_lower_headings_stay_in_section(tmp_path):
    document(
        tmp_path,
        """## Question

---

Answer :: still part of this answer

### More detail

```markdown
## Not a boundary
```

# Back to quick cards

New :: Card
""",
    )
    cards = scan(tmp_path)
    assert len(cards) == 2
    assert "Answer :: still" in cards[0].fields["Back"]
    assert "More detail" in cards[0].fields["Back"]
    assert "Not a boundary" in cards[0].fields["Back"]


@pytest.mark.parametrize(
    "body",
    [
        "Q :: A :: B\n",
        "Q :: \n",
        " :: A\n",
        "## Missing answer\n",
        "##\n\n---\n\nA\n",
        "Q :: A <!-- ankiloom noteId: 0 -->\n",
        "Q :: A <!-- ankiloom noteId: true -->\n",
        "Q :: A <!-- ankiloom noteId: 1 --> trailing\n",
        "<!-- ankiloom noteId: 1 -->\nQ :: A\n",
        "## Q\n<!-- ankiloom noteId: 1 -->\n<!-- ankiloom noteId: 2 -->\n\n---\n\nA\n",
        "Q :: A <!-- ankiloom noteId: 1 -->\nR :: B <!-- ankiloom noteId: 1 -->\n",
    ],
)
def test_ambiguous_or_invalid_cards_fail_with_line_numbers(tmp_path, body):
    document(tmp_path, body)
    with pytest.raises(LoomError, match=r"line \d+|study.md:\d+"):
        scan(tmp_path)


def test_file_level_ids_are_rejected(tmp_path):
    path = document(tmp_path, "Q :: A")
    path.write_text(path.read_text().replace("ankiloom: multi", "ankiloom: multi\nnoteId: 12"))
    with pytest.raises(LoomError, match="file-level"):
        scan(tmp_path)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("ending", ["", "\n"])
def test_shared_source_marker_writes_preserve_text_and_fields(tmp_path, newline, ending):
    path = document(tmp_path, "Q :: A\n\n## Second\n\n---\n\nB" + ending)
    source = path.read_text().replace("\n", newline)
    path.write_bytes(source.encode())
    cards = scan(tmp_path)
    before = [deepcopy(c.fields) for c in cards]
    for index, card in enumerate(cards):
        write_metadata(card, noteId=100 + index)
    assert cards[0].source == cards[1].source == path.read_bytes().decode()
    reparsed = scan(tmp_path)
    assert [c.note_id for c in reparsed] == [100, 101]
    assert [c.fields for c in reparsed] == before
    assert (
        path.read_bytes()
        .decode()
        .replace(" <!-- ankiloom noteId: 100 -->", "")
        .replace("<!-- ankiloom noteId: 101 -->" + newline, "")
        == source
    )
    write_metadata(cards[0], noteId=102)
    assert [c.note_id for c in scan(tmp_path)] == [102, 101]


def test_single_card_files_keep_existing_syntax(tmp_path):
    path = tmp_path / "old.md"
    path.write_text("## Q\n\n---\n\nA :: B\n")
    cards = parse_document(path, tmp_path)
    assert len(cards) == 1 and cards[0].section is None
    assert "A :: B" in cards[0].fields["Back"]


def test_unicode_cards_remain_utf8_after_id_writes(tmp_path):
    path = document(tmp_path, "Français :: 東京\n\n## Où ?\n\n---\n\nÀ Paris.\n")
    cards = scan(tmp_path)
    before = [deepcopy(card.fields) for card in cards]
    for index, card in enumerate(cards):
        write_metadata(card, noteId=100 + index)
    assert "東京" in path.read_bytes().decode("utf-8")
    assert [card.fields for card in scan(tmp_path)] == before


@pytest.mark.parametrize(
    "body",
    [
        "Q :: `code\ncontinued`\n",
        "Q :: *emphasis\ncontinued*\n",
        "Q :: [link\ncontinued](https://example.com)\n",
        "Q :: $x\ny$\n",
    ],
)
def test_multiline_quick_card_answers_are_rejected(tmp_path, body):
    document(tmp_path, body)
    with pytest.raises(LoomError, match="multiline"):
        scan(tmp_path)


def test_reference_links_can_be_shared_across_cards(tmp_path):
    document(
        tmp_path,
        "[label :: text][ref] :: [Answer][ref]\n\n## Heading [ref]\n\n---\n\n[Answer][ref]\n\n# Sources\n\n[ref]: https://example.com\n",
    )
    cards = scan(tmp_path)
    assert len(cards) == 2
    assert all('href="https://example.com"' in c.fields["Back"] for c in cards)


def test_removing_multi_mode_cannot_silently_recreate_notes(tmp_path):
    path = document(tmp_path, "## Q\n<!-- ankiloom noteId: 123 -->\n\n---\n\nA\n")
    path.write_text(path.read_text().replace("ankiloom: multi\n", ""))
    with pytest.raises(LoomError, match="require ankiloom: multi"):
        scan(tmp_path)


@pytest.mark.parametrize("action", ["addNote", "removeTags"])
def test_interrupted_creation_recovers_after_reorder_and_rename(server, tmp_path, action):
    path = document(tmp_path, "Q :: A\nR :: B\n")
    collection, _ = server
    collection.fail_after = action
    assert invoke(server, tmp_path).exit_code == 4
    original_ids = set(collection.notes)
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines[:4] + list(reversed(lines[4:]))))
    renamed = tmp_path / "renamed.md"
    path.rename(renamed)
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 2 and original_ids <= set(collection.notes)
    cards = scan(tmp_path)
    assert "R" in cards[0].fields["Front"]
    assert "Q" in cards[1].fields["Front"]
    assert {c.note_id for c in cards} == set(collection.notes)


def test_metadata_failure_on_second_card_preserves_first_id(monkeypatch, server, tmp_path):
    from ankiloom import sync as sync_module

    path = document(tmp_path, "Q :: A\nR :: B\n\n## Third\n\n---\n\nC\n")
    original = sync_module.write_metadata
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("disk full")
        return original(*args, **kwargs)

    monkeypatch.setattr(sync_module, "write_metadata", fail_second)
    assert invoke(server, tmp_path).exit_code == 2
    assert path.read_text().count("<!-- ankiloom noteId:") == 1
    original_ids = set(server[0].notes)
    monkeypatch.setattr(sync_module, "write_metadata", original)
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(server[0].notes) == 3 and original_ids <= set(server[0].notes)


def test_multi_create_idempotence_edit_and_reorder(server, tmp_path):
    path = document(tmp_path, "Q :: A\nR :: B\n\n## Third\n\n---\n\nC\n")
    first = invoke(server, tmp_path)
    assert first.exit_code == 0, first.output
    collection, _ = server
    assert len(collection.notes) == 3
    cards = scan(tmp_path)
    identities = {c.note_id: deepcopy(collection.notes[c.note_id]) for c in cards}
    result = invoke(server, tmp_path)
    assert result.exit_code == 0 and json.loads(result.output)["summary"] == {"unchanged": 3}
    assert len({c["path"] for c in json.loads(result.output)["changes"]}) == 3
    lines = path.read_text().splitlines(keepends=True)
    lines[4], lines[5] = lines[5], lines[4]
    path.write_text("".join(lines).replace("Q :: A", "Edited :: New answer"))
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 3
    for note_id, before in identities.items():
        assert collection.notes[note_id]["cards"] == before["cards"]
        assert collection.notes[note_id]["reviews"] == before["reviews"]


@pytest.mark.parametrize("action", ["createDeck", "addNote", "removeTags"])
def test_multi_create_response_loss_and_dry_run(server, tmp_path, action):
    path = document(tmp_path, "Q :: A\nQ :: A\n\n## Third\n\n---\n\nC\n")
    collection, _ = server
    collection.fail_after = action
    assert invoke(server, tmp_path).exit_code == 4
    before = path.read_bytes()
    journal = tmp_path / ".ankiloom" / "state.json"
    state = journal.read_bytes()
    notes = deepcopy(collection.notes)
    preview = invoke(server, tmp_path, "--dry-run")
    assert preview.exit_code == 0, preview.output
    assert path.read_bytes() == before and journal.read_bytes() == state
    assert collection.notes == notes
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 3
    assert {c.note_id for c in scan(tmp_path)} == set(collection.notes)
    assert json.loads(journal.read_text())["pendingCreations"] == {}


def test_invalid_later_section_preflights_before_any_writes(server, tmp_path):
    path = document(tmp_path, "Q :: A\n\n## Incomplete\n")
    before = path.read_bytes()
    result = invoke(server, tmp_path)
    assert result.exit_code == 2
    assert not server[0].notes and "createModel" not in server[0].calls
    assert path.read_bytes() == before


def test_unfinished_html_comment_blocks_id_insertion_before_any_writes(server, tmp_path):
    path = document(tmp_path, "Valid :: Answer\nUnfinished :: HTML <!--\n")
    before = path.read_bytes()
    result = invoke(server, tmp_path)
    assert result.exit_code == 3, result.output
    assert not server[0].notes and "createModel" not in server[0].calls
    assert path.read_bytes() == before


@pytest.mark.parametrize("lose_response", [False, True])
def test_section_removal_only_prunes_explicitly(server, tmp_path, lose_response):
    path = document(tmp_path, "Q :: A\nR :: B\n")
    assert invoke(server, tmp_path).exit_code == 0
    removed_id = scan(tmp_path)[0].note_id
    path.write_text(
        "\n".join(line for line in path.read_text().splitlines() if not line.startswith("Q ::"))
        + "\n"
    )
    assert invoke(server, tmp_path).exit_code == 0
    assert removed_id in server[0].notes
    if lose_response:
        server[0].fail_after = "deleteNotes"
    result = invoke(server, tmp_path, "--prune")
    if lose_response:
        assert result.exit_code == 4
        result = invoke(server, tmp_path, "--prune")
    assert result.exit_code == 0, result.output
    assert removed_id not in server[0].notes


@pytest.mark.parametrize("action", ["updateNoteFields", "changeDeck", "removeTags", "addTags"])
def test_multi_update_response_loss_preserves_identities(server, tmp_path, action):
    path = document(tmp_path, "Q :: A\nR :: B\n")
    assert invoke(server, tmp_path).exit_code == 0
    collection, _ = server
    before = deepcopy(collection.notes)
    path.write_text(
        path.read_text().replace("Q :: A", "Q :: Updated").replace("study/topic", "new")
    )
    folder = tmp_path / "course"
    folder.mkdir()
    path.rename(folder / "moved.md")
    collection.fail_after = action
    assert invoke(server, tmp_path).exit_code == 4
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert set(collection.notes) == set(before)
    for note_id, note in collection.notes.items():
        assert note["cards"] == before[note_id]["cards"]
        assert note["reviews"] == before[note_id]["reviews"]
        assert note["deck"] == "course" and "new" in note["tags"]
        assert "study::topic" not in note["tags"]


def test_external_edit_between_metadata_writes_is_preserved(monkeypatch, server, tmp_path):
    from ankiloom import sync as sync_module

    path = document(tmp_path, "Q :: A\nR :: B\n")
    original = sync_module.write_metadata
    edited = False

    def edit_after_first(*args, **kwargs):
        nonlocal edited
        original(*args, **kwargs)
        if not edited:
            edited = True
            path.write_text(path.read_text() + "\nUser's new prose.\n")

    monkeypatch.setattr(sync_module, "write_metadata", edit_after_first)
    result = invoke(server, tmp_path)
    assert result.exit_code == 3
    assert len(server[0].notes) == 1
    assert "User's new prose." in path.read_text()
    monkeypatch.setattr(sync_module, "write_metadata", original)
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(server[0].notes) == 2 and "User's new prose." in path.read_text()


def test_move_card_between_documents_preserves_identity(server, tmp_path):
    path = document(tmp_path, "Q :: A\nR :: B\n")
    assert invoke(server, tmp_path).exit_code == 0
    moved = scan(tmp_path)[0]
    note_id = moved.note_id
    before = deepcopy(server[0].notes[note_id])
    lines = path.read_text().splitlines(keepends=True)
    folder = tmp_path / "course"
    folder.mkdir()
    document(folder, lines[4], name="new.md")
    path.write_text("".join(lines[:4] + lines[5:]))
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(server[0].notes) == 2
    note = server[0].notes[note_id]
    assert note["deck"] == "course"
    assert note["cards"] == before["cards"] and note["reviews"] == before["reviews"]


def test_new_multi_dry_run_creates_neither_markers_nor_state(server, tmp_path):
    path = document(tmp_path, "Q :: A\n\n## Second\n\n---\n\nB\n")
    before = path.read_bytes()
    result = invoke(server, tmp_path, "--dry-run")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["summary"] == {"create": 2}
    assert path.read_bytes() == before
    assert not (tmp_path / ".ankiloom").exists()
    assert not server[0].notes and not server[0].models


def test_identity_comment_in_code_is_never_edited(tmp_path):
    path = document(tmp_path, "`<!-- ankiloom noteId: 77 -->` :: A <!-- ankiloom noteId: 123 -->\n")
    card = scan(tmp_path)[0]
    assert card.note_id == 123
    before = deepcopy(card.fields)
    write_metadata(card, noteId=456)
    assert "`<!-- ankiloom noteId: 77 -->`" in path.read_text()
    assert scan(tmp_path)[0].fields == before


def test_section_marker_in_raw_html_code_is_content(tmp_path):
    document(tmp_path, "## Q\n\n---\n\n<pre>\n<!-- ankiloom noteId: 77 -->\n</pre>\n")
    card = scan(tmp_path)[0]
    assert card.note_id is None
    write_metadata(card, noteId=123)
    assert scan(tmp_path)[0].note_id == 123


@pytest.mark.parametrize(
    "body",
    [
        "Q :: A\nR :: B",
        "## ~~Cloze~~",
        "Q :: A",
        "Q :: A\nR :: B\nS :: C\n",
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_eof_and_adjacent_line_offsets_roundtrip(tmp_path, body, newline):
    path = document(tmp_path, body)
    path.write_bytes(path.read_text().replace("\n", newline).encode())
    cards = scan(tmp_path)
    fields = [deepcopy(c.fields) for c in cards]
    for index, card in enumerate(cards):
        write_metadata(card, noteId=100 + index)
    reparsed = scan(tmp_path)
    assert [c.note_id for c in reparsed] == list(range(100, 100 + len(cards)))
    assert [c.fields for c in reparsed] == fields
