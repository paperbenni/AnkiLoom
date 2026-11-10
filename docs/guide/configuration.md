# Configuration

Set the endpoint with `--url` or `ANKICONNECT_URL`. Authentication uses
`ANKICONNECT_KEY`; keys are not CLI arguments or journal contents.
`--timeout` controls request timeout in seconds. Mutating requests are never
retried automatically; noteId, legacy identity and journal checks govern a
subsequent invocation.

Optional `ROOT/ankiloom.toml` configures just three settings:

```toml
deck = "University"
exclude = ["README.md", "drafts/**"]
url = "http://127.0.0.1:8765"
```

CLI values override deck/url; `--exclude` adds patterns. Unknown settings fail
with an error. Connection-only commands (`doctor`, `list`, `style`) have no
root and use `--url` / `ANKICONNECT_URL` directly.
