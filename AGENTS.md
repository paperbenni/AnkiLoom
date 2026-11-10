# AnkiLoom

Use `uv run` for development. Run `just check` (Ruff lint/format and ty) and
`uv run pytest` before committing changes. Development dependencies include
Anki's collection engine; tests verify models entirely in temporary collections.

The CLI definitions are the source of truth for help. Keep `--skill` generated
from those definitions; avoid static copies of option lists in the skill.

Preserve Anki note/card identities and scheduling. Note model changes must not
silently recreate notes. Preflight all inputs before note writes; dry runs must
not mutate Anki or source files. Never add implicit pruning or request retries
that can duplicate a timed-out write. Keep response-loss tests for create,
update and delete paths. Tests must never touch a user's real Anki profile.

The Markdown format is one file per note: horizontal-rule basic/reversed,
strike-through cloze, and final-emphasis typed answer. Parse structure using
Markdown tokens so code and math do not accidentally become card syntax.
