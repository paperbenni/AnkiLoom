# Configuration

Set the endpoint with `--url` or `ANKICONNECT_URL`. Authentication uses
`ANKICONNECT_KEY`; keys are not CLI arguments or journal contents.
`--timeout` controls request timeout in seconds. If a sync fails, follow
[Sync and recovery](./sync.md#recover-an-interrupted-sync) before retrying.

Optional `ROOT/ankiloom.toml` configures just three settings:

```toml
deck = "University"
exclude = ["README.md", "drafts/**"]
url = "http://127.0.0.1:8765"
```

CLI values override deck/url; `--exclude` adds patterns. Unknown settings fail
with an error. Connection-only commands (`doctor`, `list`, `style`) have no
root and use `--url` / `ANKICONNECT_URL` directly.
