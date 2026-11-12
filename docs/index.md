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
    details: Write one note per file, or combine quick facts and longer cards in a study sheet. Folders become decks.
  - title: Preview before syncing
    details: Validate offline and compare with Anki in a dry run. Ordinary sync preserves review history; deletion is explicit.
  - title: Made for the terminal
    details: Run through uvx. Preview changes, watch your edits, and export card-writing instructions for an agent.
---

## Start with a simple card

```markdown
Frobenius norm

---

Square every entry, sum them, then take the square root.

$$
\|A\|_F = \sqrt{\sum_{i,j} a_{ij}^2}
$$
```

For several cards in one document, use [multi-card files](./guide/card-format.md#multiple-notes-per-file)
with `question :: answer` lines and `##` heading sections.

## Try it without installing

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.7.0 ankiloom check ./cards
```

Validation works offline. To sync, run Anki desktop with AnkiConnect installed,
then follow the [getting started guide](./guide/getting-started.md).
