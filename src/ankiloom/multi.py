"""Token-based boundaries and source positions for opt-in multi-card documents."""

import re
from dataclasses import dataclass

from markdown_it.rules_inline import html_inline, link
from markdown_it.rules_inline.backticks import backtick
from mdit_py_plugins.dollarmath.index import math_inline_dollar

from .cards import frontmatter, markdown
from .errors import LoomError

MARKER = re.compile(r"<!-- ankiloom noteId: ([1-9][0-9]*) -->")
RESERVED = re.compile(r"<!--\s*ankiloom\b.*?(?:-->|$)", re.DOTALL)


@dataclass
class Section:
    start: int
    end: int
    line: int
    body: str
    insert_at: int
    marker: tuple[int, int] | None = None
    note_id: int | None = None
    quick: tuple[str, str] | None = None


def inline_positions(text, env):
    """Let the inline parser protect code, math, links and emphasis delimiters."""
    md = markdown()
    # Markdown normalizes CRLF before inline parsing; translate positions back
    # to the original source so later cards and ID comments keep exact offsets.
    offsets = [
        index
        for index, char in enumerate(text)
        if not (char == "\n" and index > 0 and text[index - 1] == "\r")
    ] + [len(text)]
    multiline = False

    def track_multiline(rule):
        def tracked(state, silent):
            nonlocal multiline
            start = state.pos
            matched = rule(state, silent)
            if matched and "\n" in state.src[start : state.pos]:
                multiline = True
            return matched

        return tracked

    def separator(state, silent):
        pos = state.pos
        if (
            state.src[pos : pos + 2] != "::"
            or pos == 0
            or not state.src[pos - 1].isspace()
            or pos + 2 >= state.posMax
            or not state.src[pos + 2].isspace()
        ):
            return False
        if not silent:
            token = state.push("quick_separator", "", 0)
            token.meta["offset"] = pos
            token.content = "::"
        state.pos += 2
        return True

    def positioned_html(state, silent):
        start = state.pos
        matched = html_inline(state, silent)
        if matched and not silent:
            state.tokens[-1].meta["offset"] = start
        return matched

    md.inline.ruler.before("text", "quick_separator", separator)
    md.inline.ruler.at("html_inline", positioned_html)
    md.inline.ruler.at("backticks", track_multiline(backtick))
    md.inline.ruler.at("link", track_multiline(link))
    md.inline.ruler.at("math_inline", track_multiline(math_inline_dollar()))
    tokens = md.parseInline(text, env.copy())[0].children or []
    depth = 0
    separators, comments = [], []
    for token in tokens:
        if token.type == "quick_separator" and depth == 0:
            separators.append(offsets[token.meta["offset"]])
        if token.type == "html_inline" and RESERVED.match(token.content):
            start = offsets[token.meta["offset"]]
            end = offsets[token.meta["offset"] + len(token.content)]
            comments.append((start, text[start:end]))
        if (token.type in {"softbreak", "hardbreak"} and depth > 0) or (
            token.type == "html_inline" and "\n" in token.content
        ):
            multiline = True
        depth += token.nesting
    return separators, comments, multiline


def sections(source: str) -> list[Section]:
    _, body, front_lines = frontmatter(source)
    all_lines = source.splitlines(keepends=True)
    lines = body.splitlines(keepends=True)
    offsets = [len("".join(all_lines[:front_lines]))]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    env = {}
    tokens = markdown().parse(body, env)
    headings = [
        token
        for token in tokens
        if token.type == "heading_open" and token.level == 0 and token.markup in {"#", "##"}
    ]
    paragraphs = {tuple(t.map) for t in tokens if t.type == "paragraph_open" and t.level == 0}
    heading_text = {tuple(t.map): t.content for t in tokens if t.type == "inline" and t.map}
    result = []
    for index, heading in enumerate(headings):
        if heading.tag != "h2":
            continue
        start = heading.map[0]
        if not heading_text[tuple(heading.map)].strip():
            raise LoomError(
                f"line {front_lines + start + 1}: a card heading needs a prompt.", "parse"
            )
        end = headings[index + 1].map[0] if index + 1 < len(headings) else len(lines)
        result.append(
            Section(
                offsets[start],
                offsets[end],
                front_lines + start + 1,
                "".join(lines[start:end]),
                offsets[heading.map[1]],
            )
        )

    comments = []
    for token in tokens:
        if token.map is None:
            continue
        start, end = token.map
        raw = "".join(lines[start:end])
        if token.type == "html_block" and raw.lstrip().startswith("<!--"):
            comments.extend((offsets[start] + m.start(), m.group()) for m in RESERVED.finditer(raw))
        if token.type != "inline":
            continue
        separators, inline_comments, multiline = inline_positions(raw, env)
        comments.extend((offsets[start] + pos, content) for pos, content in inline_comments)
        # Only standalone paragraph lines outside heading cards are shorthand.
        if token.level != 1 or tuple(token.map) not in paragraphs:
            continue
        for line_index in range(start, end):
            absolute = offsets[line_index]
            if any(section.start <= absolute < section.end for section in result):
                continue
            positions = [
                offsets[start] + pos - absolute
                for pos in separators
                if absolute <= offsets[start] + pos < offsets[line_index + 1]
            ]
            if not positions:
                continue
            if multiline:
                raise LoomError(
                    f"line {front_lines + line_index + 1}: quick cards cannot share a paragraph with multiline inline formatting; use blank lines or a heading card.",
                    "parse",
                )
            if len(positions) != 1:
                raise LoomError(
                    f"line {front_lines + line_index + 1}: a quick card needs exactly one spaced :: separator; escape extra colons or put them in code.",
                    "parse",
                )
            line = lines[line_index].rstrip("\r\n")
            pos = positions[0]
            result.append(
                Section(
                    absolute,
                    offsets[line_index + 1],
                    front_lines + line_index + 1,
                    line,
                    absolute + len(line),
                    quick=(line[:pos].strip(), line[pos + 2 :].strip()),
                )
            )

    for start, content in comments:
        match = MARKER.fullmatch(content)
        line = source[:start].count("\n") + 1
        if not match:
            raise LoomError(
                f"line {line}: expected <!-- ankiloom noteId: positive-integer -->.", "parse"
            )
        section = next((s for s in result if s.start <= start < s.end), None)
        if section is None:
            raise LoomError(f"line {line}: ID comment is outside a card.", "parse")
        if section.marker:
            raise LoomError(f"line {line}: multiple ID comments in one card.", "parse")
        end = start + len(content)
        line_start = source.rfind("\n", 0, start) + 1
        line_end = source.find("\n", end)
        line_end = len(source) if line_end < 0 else line_end
        if source[end:line_end].strip() or (not section.quick and source[line_start:start].strip()):
            raise LoomError(
                f"line {line}: put the ID comment on its own line or at the end of a quick card.",
                "parse",
            )
        section.marker = start, end
        section.note_id = int(match[1])
        relative = start - section.start
        section.body = section.body[:relative] + section.body[relative + len(content) :]
        if section.quick:
            front, back = section.quick
            section.quick = front, back.removesuffix(content).strip()
        else:
            # Removing the whole marker line keeps rendering and fingerprints stable.
            section.body = (
                source[section.start : line_start]
                + source[min(line_end + 1, len(source)) : section.end]
            )

    for section in result:
        if section.quick and not all(section.quick):
            raise LoomError(
                f"line {section.line}: the quick card prompt and answer must both contain content.",
                "parse",
            )
    return sorted(result, key=lambda section: section.start)


def metadata_source(card, note_id):
    section = card.document.sections[card.section]
    marker = f"<!-- ankiloom noteId: {note_id} -->"
    if section.marker:
        start, end = section.marker
        source = card.source[:start] + marker + card.source[end:]
    else:
        pos = section.insert_at
        newline = "\r\n" if "\r\n" in card.source else "\n"
        if section.quick:
            insertion = " " + marker
        else:
            insertion = ("" if card.source[:pos].endswith("\n") else newline) + marker + newline
        source = card.source[:pos] + insertion + card.source[pos:]
    # An unfinished HTML comment, for example, can swallow an inserted ID.
    # Verify the edit during preflight, before any note mutations are possible.
    updated = sections(source)
    before = card.document.sections
    if len(updated) != len(before) or any(
        after.quick != old.quick
        or after.body.strip() != old.body.strip()
        or after.note_id != (note_id if index == card.section else old.note_id)
        for index, (old, after) in enumerate(zip(before, updated))
    ):
        raise LoomError(
            f"line {section.line}: cannot safely update the ID comment; fix the surrounding Markdown.",
            "parse",
        )
    return source
