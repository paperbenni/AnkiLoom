# Card format

Each visible `.md` file below the root is one note by default. Opt into
[multiple notes per file](#multiple-notes-per-file) with `ankiloom: multi`.
Keep other documents outside that directory or exclude them. Hidden
files/directories are ignored.

## Multiple notes per file

Use quick lines for simple facts and `##` heading sections for longer cards:

```markdown
---
ankiloom: multi
tags: [geography]
---

# Geography revision

Ordinary prose outside card sections is ignored.

Capital of France? :: Paris
Largest ocean? :: Pacific

## Why do seasons occur?

---

Earth's axial tilt changes the angle and duration of sunlight.

## The capital of ~~France~~ is ~~Paris~~.

# More quick cards

Largest planet? :: Jupiter
```

A `##` heading outside a list or blockquote starts a note and is part of its
prompt. It ends at the next `##` or `#` heading. Lower headings belong to the
current note. Use the existing basic, reversed, cloze or typed-answer syntax
inside the section.
Write these headings with `#` or `##`; underlined headings do not define
card boundaries. Headings in code, math, lists, blockquotes and raw HTML are
left as content.

Outside those sections, each paragraph line with one unformatted, spaced
` :: ` delimiter becomes a **basic** note. Adjacent quick lines work without
blank lines between them. Both sides support inline Markdown and media, but
strike-through and final emphasis stay ordinary formatting in quick cards.
Delimiters inside code, math, emphasis, links or HTML attributes do not count.
Escape an extra delimiter as `\::` or put it in inline code. Lists, tables,
code and HTML blocks do not supply quick cards.

Quick cards take exactly one physical line. Multiline code, math, links or
emphasis in the same paragraph are rejected rather than truncated; add blank
lines around independent prose or use a heading card for multiline content.
Reference links can share definitions anywhere in the file.

::: tip Section boundaries
A quick-looking line **inside** a heading section stays part of that section.
Add a `#` heading to end the section before returning to quick cards.
:::

File-level tags and the folder's deck apply to every note. Do not put
`noteId` or `loomId` in a multi-card file's frontmatter. AnkiLoom writes a
hidden ID comment for each note instead:

```markdown
Capital of France? :: Paris <!-- ankiloom noteId: 123 -->

## Why do seasons occur?
<!-- ankiloom noteId: 456 -->

---

Earth's axial tilt.
```

Preserve these comments when moving or reordering cards, including between
multi-card files. Remove the comment from a copy intended to become a new
note. Duplicate IDs, malformed comments and comments outside cards fail
validation. Removing a section leaves its Anki note alone unless `--prune`
is explicit. Reports identify multi-card notes by file and line number.

If creation is interrupted before its ID reaches Markdown, rerun the sync
before editing the card's content. Recovery can follow a move or reorder when
content matches uniquely; ambiguous matches block sync instead of guessing.

## Card types

Use these formats in single-note files or inside `##` sections in multi-card files.

### Basic

```markdown
Question

---

Answer, with **formatting**, code, math, tables, or images.
```

### Reversed

Two rules between prompt and answer create cards in both directions. A third
rule introduces optional extra information on the answer side of both cards.

```markdown
Oxygen

---

---

O

---

A chemical symbol.
```

### Cloze

Strike-through hides an answer. Each unnumbered cloze creates a separate card;
explicit numbers group clozes and help keep their identities stable as you edit.
An optional final emphasis supplies a hint. Code and math are left alone.

```markdown
~~1 Paris _city_~~ is the capital of ~~2 France~~.

---

Extra information on the answer side.
```

Once studied, preserve cloze numbers. Anki can retain empty cards after clozes
are removed; use Anki's **Tools → Empty Cards** to review those.

### Type answer

Without a horizontal rule, a final emphasis span supplies a plain-text answer.

```markdown
Capital of France?

_Paris_
```

## Tags and IDs

```markdown
---
tags:
  - maths/linear-algebra
  - exam
---

Question

---

Answer
```

Tags use a YAML list; `/` becomes Anki's `::`. Use block-style frontmatter keys
as above, rather than a flow-style `{...}` mapping. Other metadata is preserved.

In single-note files, AnkiLoom writes `noteId` (Anki's numeric ID) in the
frontmatter. Multi-card files use [per-card ID comments](#multiple-notes-per-file).
**Keep these IDs with your cards**, including in version control. Filenames
can change without creating new notes.

When copying a card to make a different note, remove its ID from the copy:
`noteId` and any legacy `loomId` for a single-note file, or the ID comment for
a card in a multi-card file. Duplicate IDs fail validation rather than
targeting the same note.

Older AnkiLoom versions also wrote `loomId`. Sync removes that legacy field
after confirming the note, so no manual cleanup is needed. If a sync is
interrupted, follow [Sync and recovery](./sync.md#recover-an-interrupted-sync)
before changing IDs or copying unfinished cards.

Folders below the supplied root become deck levels: `cards/maths/algebra/x.md`
becomes `maths::algebra`. A file directly under the root uses the root's name.
`--deck University` adds a prefix: `University::maths::algebra`.

## Rendering and media

Supported: CommonMark, HTML, pipe tables, fenced code, inline `$x$`, display
`$$...$$` math, and local image/audio embeds. Math uses Anki's MathJax renderer.
AnkiLoom preserves normal Markdown paragraph and line-break behavior.

```markdown
![Diagram](assets/diagram.png)
![[assets/diagram.png|900]]
![[assets/diagram.png|900x600]]
![Pronunciation](assets/audio.mp3)
```

Media paths resolve relative to the card file and must stay inside the card
root. AnkiLoom copies local files to Anki and picks up changed media on the
next sync. Missing files fail validation. Remote images stay linked to their
original URL.

This is a focused format, not an Obsidian renderer. Wiki note links/transclusions,
PDF embeds, Mermaid rendering, syntax highlighting, task-list checkboxes,
highlights, video embeds and local media inside raw HTML are not processed.
Use Markdown images or wiki image embeds for managed media. There is no
user-supplied regex format or plugin system.
