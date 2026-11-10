import pytest

from ankiloom.cards import parse_card, scan
from ankiloom.errors import LoomError
from ankiloom.storage import write_metadata


def card(tmp_path, text):
    p = tmp_path / "card.md"
    p.write_text(text)
    return parse_card(p, tmp_path)


def test_basic_math_table_and_code(tmp_path):
    c = card(
        tmp_path,
        "Prompt $x_i$\n\n---\n\n$$\nx \\times y\n$$\n\n|a|b|\n|-|-|\n|1|2|\n\n```python\n---\n~~literal~~\n```\n",
    )
    assert c.kind == "basic"
    assert r"\(x_i\)" in c.fields["Front"]
    assert r"\[" in c.fields["Back"] and r"\times" in c.fields["Back"]
    assert "<table>" in c.fields["Back"]
    assert "~~literal~~" in c.fields["Back"]


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("A\n\n---\n\n---\n\nB\n\n---\n\nextra", "reverse"),
        ("Capital of France?\n\n_Paris_", "type"),
        ("The capital is ~~Paris _city_~~.", "cloze"),
    ],
)
def test_note_types(tmp_path, text, kind):
    c = card(tmp_path, text)
    assert c.kind == kind
    if kind == "cloze":
        assert "{{c1::Paris ::city}}" in c.fields["Front"]
    elif kind == "reverse":
        assert "extra" in c.fields["Extra"]
    else:
        assert "Paris" not in c.fields["Front"]
        assert "Paris" in c.fields["Back"]


def test_cloze_code_and_math_remain_literal(tmp_path):
    c = card(tmp_path, "~~1 A~~ and ~~1 B~~, `~~code~~`, $x_i$\n\n---\n\nBack")
    assert c.fields["Front"].count("{{c1::") == 2
    assert "~~code~~" in c.fields["Front"]
    assert r"\(x_i\)" in c.fields["Front"]


def test_media_copy_and_content_hash(tmp_path):
    (tmp_path / "image.png").write_bytes(b"image")
    c = card(tmp_path, "Picture\n\n---\n\n![[image.png|900]]\n\n![same](image.png)")
    assert len(c.media) == 1
    name = next(iter(c.media))
    assert c.fields["Back"].count(name) == 2
    assert 'width="900"' in c.fields["Back"]
    (tmp_path / "image.png").write_bytes(b"changed")
    assert next(iter(parse_card(c.path, tmp_path).media)) != name


def test_cloze_media(tmp_path):
    (tmp_path / "image.png").write_bytes(b"image")
    c = card(tmp_path, "~~![name](image.png)~~ and ![[image.png]]")
    assert len(c.media) == 1
    assert "{{c1::<img" in c.fields["Front"]
    assert "![[" not in c.fields["Front"]


@pytest.mark.parametrize(
    "text",
    [
        "prose only",
        "Prompt\n\n---\n",
        "---\nnoteId: 2\nnoteId: 3\n---\nA\n\n---\n\nB",
        "---\nnoteId: true\n---\nA\n\n---\n\nB",
        "---\ntags: hello\n---\nA\n\n---\n\nB",
    ],
)
def test_invalid_notes(tmp_path, text):
    with pytest.raises(LoomError):
        card(tmp_path, text)


def test_media_outside_root(tmp_path):
    with pytest.raises(LoomError, match="escapes"):
        card(tmp_path, "A\n\n---\n\n![x](../outside.png)")


def test_duplicate_ids_and_excludes(tmp_path):
    for name in ["a", "b"]:
        (tmp_path / f"{name}.md").write_text("---\nnoteId: 3\n---\nA\n\n---\n\nB")
    with pytest.raises(LoomError, match="Duplicate noteId"):
        scan(tmp_path)
    assert len(scan(tmp_path, excludes=("b.md",))) == 1


def test_crlf_and_frontmatter_comments_survive(tmp_path):
    source = (
        "---\r\n# comment\r\ntags: [hello]\r\ncustom: value\r\n---\r\n\r\nA\r\n\r\n---\r\n\r\nB\r\n"
    )
    p = tmp_path / "card.md"
    p.write_bytes(source.encode())
    c = parse_card(p, tmp_path)
    write_metadata(c, loomId="a" * 32)
    write_metadata(c, noteId=123)
    actual = p.read_bytes().decode()
    assert "# comment\r\n" in actual and "custom: value\r\n" in actual
    assert actual.endswith("---\r\n\r\nA\r\n\r\n---\r\n\r\nB\r\n")
    assert parse_card(p, tmp_path).note_id == 123


def test_detect_edit_before_metadata_write(tmp_path):
    c = card(tmp_path, "A\n\n---\n\nB")
    c.path.write_text("changed")
    with pytest.raises(LoomError, match="changed during sync"):
        write_metadata(c, noteId=123)
