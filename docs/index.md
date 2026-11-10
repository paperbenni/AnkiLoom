---
layout: home

hero:
  name: AnkiLoom
  text: Markdown in. Anki cards out.
  tagline: Write cards in a text editor. Sync from your terminal. Keep your review history.
  actions:
    - theme: brand
      text: Get started
      link: /guide/getting-started
    - theme: alt
      text: Migrate from Yanki
      link: /guide/migration

features:
  - title: Your Markdown, your editor
    details: One file per note. A horizontal rule separates question and answer. Folders become decks, without Obsidian or custom regexes.
  - title: Preview before syncing
    details: Validate offline, compare with Anki in a dry run, and adopt existing Yanki notes in place. Deletion is always explicit.
  - title: Made for the terminal
    details: Run through uvx. Get useful errors, structured JSON, and an agent skill with help generated from the actual CLI.
---

## A card is just a Markdown file

```markdown
Frobenius norm

---

Square every entry, sum them, then take the square root.

$$
\|A\|_F = \sqrt{\sum_{i,j} a_{ij}^2}
$$
```

## Try it without installing

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.2.0 ankiloom check ./cards
```

Validation works offline. To sync, run Anki desktop with AnkiConnect installed,
then follow the [getting started guide](./guide/getting-started.md).
