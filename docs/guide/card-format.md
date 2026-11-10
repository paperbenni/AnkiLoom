# Card format

Each visible `.md` file below the root is one note. Keep supporting documents
outside that directory or exclude them. Hidden files/directories are ignored.

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

### Tags and IDs

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

AnkiLoom writes `loomId` (a retry-safe identity) and `noteId` (Anki's numeric ID).
**Commit these with your cards.** Filenames can change without creating new notes.
When copying a file to make a different note, remove **both** IDs from the copy.
Duplicate IDs fail validation rather than silently targeting the same note.

Folders below the supplied root become deck levels: `cards/maths/algebra/x.md`
becomes `maths::algebra`. A file directly under the root uses the root's name.
`--deck University` adds a prefix: `University::maths::algebra`.

### Rendering and media

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
root. Local files are copied to Anki using content-hashed names: identical
assets deduplicate and changed content gets a new name. Missing media fails
validation. Remote image URLs remain remote and are never downloaded.

This is a focused format, not an Obsidian renderer. Wiki note links/transclusions,
PDF embeds, Mermaid rendering, syntax highlighting, task-list checkboxes,
highlights, video embeds and local media inside raw HTML are not processed.
Use Markdown images or wiki image embeds for managed media. There is no
user-supplied regex format or plugin system.
