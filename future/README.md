# Future notes

Shipped in 0.3: Backup snapshots, cross-chat search, Signal Browser name, official Signal mark with dashed outline. Public repo: github.com/leorami/signal-browser.

Still open if needed:

- Windows/Linux PyInstaller packages (same Python app; build on that OS). iOS/Android are not PyInstaller targets.
- Official Signal Desktop `metadata.json` / `main.jsonl` importer **into this app** (not write-back to Signal Desktop or iOS)
- Schema shims for very old Signal Desktop versions
- Pre-commit hooks and GitHub Actions CI
- Snapshot prune / size caps for very large histories
