# Migrate from Yanki

Keep your Markdown and its existing `noteId` values. First stop syncing those
notes with Yanki, then preview and adopt them:

```sh
ankiloom check ./cards
ankiloom sync ./cards --adopt --dry-run
ankiloom sync ./cards --adopt
```

AnkiLoom updates those exact notes in place, keeping their models, card IDs,
review history and unrelated tags/fields. It supports Yanki Basic, Reversed
with Extra, Cloze and Type Answer models. It refuses a note type change instead
of deleting and recreating cards. New notes use AnkiLoom models.

Older AnkiLoom versions also wrote a `loomId` field and `ankiloom::id::…` tag.
A normal sync removes them after confirming `noteId`, so no manual cleanup is
needed.

After adoption, use ordinary `ankiloom sync ./cards`. To keep existing card
styling, no additional step is needed: adopted note templates and CSS stay in
Anki. To apply a CSS file explicitly:

```sh
ankiloom style ./style.css --include-yanki --dry-run
ankiloom style ./style.css --include-yanki
```

Style changes affect **all** notes using the listed models. Rendered content
has both `.ankiloom` and `.yanki` classes so existing Yanki CSS selectors work.
