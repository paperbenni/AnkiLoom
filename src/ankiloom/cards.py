"""Parse one Markdown file per note. Structural decisions use Markdown tokens."""

import hashlib
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from yaml.resolver import BaseResolver

from .errors import LoomError

MODELS = {
    "basic": "AnkiLoom - Basic",
    "reverse": "AnkiLoom - Reversed",
    "cloze": "AnkiLoom - Cloze",
    "type": "AnkiLoom - Type Answer",
}
YANKI_MODELS = {
    "basic": "Yanki - Basic",
    "reverse": "Yanki - Basic (and reversed card with extra)",
    "cloze": "Yanki - Cloze",
    "type": "Yanki - Basic (type in the answer)",
}


def markdown():
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    md.use(dollarmath_plugin)
    md.add_render_rule(
        "math_inline", lambda self, ts, i, opts, env: r"\(" + html.escape(ts[i].content) + r"\)"
    )
    md.add_render_rule(
        "math_block",
        lambda self, ts, i, opts, env: (
            '<div class="math">' + r"\[" + html.escape(ts[i].content) + r"\]" + "</div>"
        ),
    )
    return md


def frontmatter(source: str):
    lines = source.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, source, 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise LoomError("Unclosed YAML frontmatter; add its closing ---.", "parse")
    try:
        # Reject duplicate keys: silently choosing an ID is dangerous.
        class UniqueLoader(yaml.SafeLoader):
            pass

        def mapping(loader, node):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node)
                if key in result:
                    raise LoomError(f"Duplicate frontmatter key: {key}", "parse")
                result[key] = loader.construct_object(value_node)
            return result

        UniqueLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        meta = yaml.load("".join(lines[1:end]), Loader=UniqueLoader) or {}
    except (yaml.YAMLError, TypeError) as exc:
        raise LoomError(f"Invalid YAML frontmatter: {exc}", "parse") from exc
    if not isinstance(meta, dict):
        raise LoomError("Frontmatter must be a mapping of keys to values.", "parse")
    return meta, "".join(lines[end + 1 :]), end + 1


@dataclass
class Card:
    path: Path
    source: str
    meta: dict
    kind: str
    fields: dict[str, str]
    deck: str
    tags: list[str]
    media: dict[str, bytes] = field(default_factory=dict)

    @property
    def note_id(self):
        return self.meta.get("noteId")


def render(text: str, card: Card, root: Path, parsed_tokens=None):
    md = markdown()

    def asset(src):
        parsed = urlparse(src)
        if parsed.scheme in {"http", "https"}:
            return src  # Remote media remains remote; never fetch during validation.
        if parsed.scheme:
            raise LoomError(f"Unsupported media URL {src!r}; use a local file or HTTPS.", "media")
        path = (card.path.parent / unquote(parsed.path)).resolve()
        if not path.is_relative_to(root.resolve()):
            raise LoomError(f"Media escapes the card root: {src}", "media")
        if not path.is_file():
            raise LoomError(f"Missing media {src!r}, resolved as {path}", "media")
        data = path.read_bytes()
        filename = "ankiloom_" + hashlib.sha256(data).hexdigest() + path.suffix.lower()
        card.media[filename] = data
        return filename

    # Rewrite wiki embeds only inside inline text tokens, never code or math.
    def rewrite(tokens):
        for token in tokens:
            if token.type == "image":
                src = token.attrGet("src") or ""
                target = asset(src)
                if Path(urlparse(src).path).suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a"}:
                    token.type, token.content, token.children = (
                        "html_inline",
                        f"[sound:{target}]",
                        None,
                    )
                else:
                    token.attrSet("src", target)
            if token.children:
                children = []
                for child in token.children:
                    if child.type != "text":
                        children.append(child)
                        continue
                    parts = re.split(r"(!\[\[[^\]\n]+\]\])", child.content)
                    for part in parts:
                        from markdown_it.token import Token

                        new = Token("text", "", 0)
                        new.content = part
                        if part.startswith("![[") and part.endswith("]]"):
                            bits = part[3:-2].split("|")
                            target = asset(bits[0])
                            size = bits[1] if len(bits) > 1 else ""
                            if size and not re.fullmatch(r"\d+(?:x\d+)?", size):
                                raise LoomError(f"Invalid wiki image size: {size}", "media")
                            attrs = ""
                            if size:
                                dims = size.split("x")
                                attrs = f' width="{dims[0]}"'
                                if len(dims) == 2:
                                    attrs += f' height="{dims[1]}"'
                            new.type = "html_inline"
                            if Path(bits[0]).suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a"}:
                                new.content = f"[sound:{target}]"
                            else:
                                new.content = (
                                    f'<img src="{html.escape(target, quote=True)}"{attrs} alt="">'
                                )
                        children.append(new)
                token.children = children
                rewrite(token.children)

    tokens = md.parse(text) if parsed_tokens is None else parsed_tokens
    rewrite(tokens)
    return '<div class="ankiloom yanki">' + md.renderer.render(tokens, md.options, {}) + "</div>"


def parse_card(path: Path, root: Path, deck_prefix: str = ""):
    source = path.read_bytes().decode("utf-8")
    meta, body, _ = frontmatter(source)
    note_id = meta.get("noteId")
    if note_id is not None and (type(note_id) is not int or note_id <= 0):
        raise LoomError("noteId must be a positive integer; omit it for new notes.", "parse")
    loom_id = meta.get("loomId")
    if loom_id is not None and (
        not isinstance(loom_id, str) or not re.fullmatch(r"[0-9a-f]{32}", loom_id)
    ):
        raise LoomError("loomId must be an AnkiLoom-generated 32-character hex ID.", "parse")
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or any(
        not isinstance(t, str) or not t or re.search(r"\s", t) for t in tags
    ):
        raise LoomError("tags must be a YAML list of nonempty strings without whitespace.", "parse")
    if any(t.lower().startswith("ankiloom::") for t in tags):
        raise LoomError("The ankiloom:: tag prefix is reserved for sync identities.", "parse")
    parts = list(path.relative_to(root).parent.parts)
    deck = "::".join(([deck_prefix] if deck_prefix else []) + parts) or root.name
    card = Card(path, source, meta, "basic", {}, deck, sorted({t.replace("/", "::") for t in tags}))
    md = markdown()
    tokens = md.parse(body)
    rules = [t for t in tokens if t.type == "hr" and t.level == 0]
    lines = body.splitlines(keepends=True)
    first = rules[0].map[0] if rules else len(lines)
    front = "".join(lines[:first])
    back = "".join(lines[rules[0].map[1] :]) if rules else ""
    front_tokens = md.parse(front)
    clozes = [t for block in front_tokens for t in (block.children or []) if t.type == "s_open"]
    extra = ""
    converted = None
    if clozes:
        card.kind = "cloze"
        counter = 0

        def cloze_renderer(self, ts, idx, opts, env):
            nonlocal counter
            counter += 1
            # Explicit numbering is consumed from the following text token.
            n = counter
            if idx + 1 < len(ts) and ts[idx + 1].type == "text":
                match = re.match(r"(\d{1,2}) (.*)", ts[idx + 1].content, re.DOTALL)
                if match:
                    n = int(match[1])
                    if n < 1:
                        raise LoomError("Cloze numbers start at 1.", "parse")
                    ts[idx + 1].content = match[2]
            return "{{c" + str(n) + "::"

        # Convert via tokens to leave code/math untouched. Hints use final emphasis.
        converted = md.parse(front)
        for block in converted:
            children = block.children or []
            for i, token in enumerate(children):
                if token.type == "s_open":
                    token.type = "html_inline"
                    token.content = cloze_renderer(None, children, i, {}, {})
                elif token.type == "s_close":
                    token.type, token.content = "html_inline", "}}"
                elif token.type == "em_open":
                    # Only an emphasis immediately before a closing cloze is a hint.
                    close = next(
                        (j for j in range(i + 1, len(children)) if children[j].type == "em_close"),
                        None,
                    )
                    if (
                        close is not None
                        and close + 1 < len(children)
                        and children[close + 1].type == "s_close"
                    ):
                        token.type, token.content = "html_inline", "::"
                        children[close].type, children[close].content = "html_inline", ""
    elif len(rules) >= 2 and not "".join(lines[rules[0].map[1] : rules[1].map[0]]).strip():
        card.kind = "reverse"
        start = rules[1].map[1]
        end = rules[2].map[0] if len(rules) > 2 else len(lines)
        back = "".join(lines[start:end])
        extra = "".join(lines[rules[2].map[1] :]) if len(rules) > 2 else ""
    elif not rules:
        inline = [t for block in tokens for t in (block.children or [])]
        if inline and inline[-1].type == "em_close":
            # Locate the final emphasis by token source-independent rendered children.
            opening = max((i for i, t in enumerate(inline) if t.type == "em_open"), default=-1)
            if opening >= 0 and all(t.type == "text" for t in inline[opening + 1 : -1]):
                answer = "".join(t.content for t in inline[opening + 1 : -1])
                match = re.search(r"([*_])([^\n]*?)\1\s*$", body)
                if match and answer:
                    card.kind, front, back = "type", body[: match.start()], answer
        if card.kind == "basic":
            raise LoomError(
                "Expected a front/back separator (blank line, ---, blank line), a cloze, or a final _typed answer_.",
                "parse",
            )
    if not front.strip() or (card.kind != "cloze" and not back.strip()):
        raise LoomError("The prompt and answer must both contain content.", "parse")
    card.fields = {"Front": render(front, card, root, converted), "Back": render(back, card, root)}
    if card.kind == "reverse":
        card.fields["Extra"] = render(extra, card, root)
    return card


def visible_files(root: Path, excludes=()):
    """Select source files consistently for parsing and change detection."""
    excluded_paths = set()
    for pattern in excludes:
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise LoomError(
                f"Exclude pattern must be relative to the card root: {pattern!r}", "config"
            )
        excluded_paths.update(root.glob(pattern))
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (
            any(p.startswith(".") for p in rel.parts)
            or path in excluded_paths
            or any(parent in excluded_paths for parent in path.parents)
        ):
            continue
        if path.is_file():
            yield path


def scan(root: Path, deck_prefix="", excludes=()):
    root = root.resolve()
    if not root.is_dir():
        raise LoomError(f"Card root is not a directory: {root}", "input")
    cards, errors, ids, loom_ids = [], [], {}, {}
    for path in visible_files(root, excludes):
        if path.suffix != ".md":
            continue
        rel = path.relative_to(root)
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise LoomError("Symlinked cards are unsupported; use ordinary files.", "input")
            card = parse_card(path, root, deck_prefix)
            for value, seen, label in [
                (card.note_id, ids, "noteId"),
                (card.meta.get("loomId"), loom_ids, "loomId"),
            ]:
                if value is not None:
                    if value in seen:
                        raise LoomError(
                            f"Duplicate {label} {value}; also used in {seen[value]}", "duplicate"
                        )
                    seen[value] = rel.as_posix()
            cards.append(card)
        except (LoomError, UnicodeError, OSError) as exc:
            errors.append(f"{rel}: {exc}")
    if errors:
        raise LoomError("\n".join(errors), "validation")
    return cards
