# Card styling

New AnkiLoom models include a bundled theme: system fonts, a readable column,
comfortable spacing, table borders, code formatting, bounded media and day/night
colors. No stylesheet or network font download is required in your card repository.

Ordinary sync leaves existing model CSS and templates alone, including your
customizations in Anki. Installing a newer AnkiLoom version does not overwrite
them. To explicitly apply the current bundled theme to existing models:

```sh
ankiloom style --default --dry-run
ankiloom style --default
```

To replace their CSS with your own stylesheet:

```sh
ankiloom style ./custom.css --dry-run
ankiloom style ./custom.css
```

Use `.card` for the card itself and `.ankiloom` for rendered Markdown content.
Generated content uses no `.yanki` compatibility class. Update custom selectors
from `.yanki` to `.ankiloom` when moving an old stylesheet to native notes.

**Styles belong to models, not individual notes or repositories.** These commands
affect every note using the listed AnkiLoom models. They apply once to models that
already exist. If you later create your first note of another kind, its new model
gets the bundled theme; rerun the custom styling command to style that model too.

Yanki migration uses the destination AnkiLoom models' styling. Existing native
models keep their CSS; newly created native models receive the bundled theme.
