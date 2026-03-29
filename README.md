# granola-sync

A Claude Code skill that syncs meeting notes from [Granola](https://granola.ai) into local Markdown files, organized by month.

## What it does

- Reads your Granola access token from the macOS app data
- Fetches all meeting documents from the Granola API
- Converts ProseMirror content to Markdown with frontmatter
- Includes meeting transcripts
- Writes files as `YYYY-MM/YYYY-MM-DD - Meeting Title.md`
- Tracks sync state to avoid re-downloading unchanged notes

## Requirements

- macOS with [Granola](https://granola.ai) desktop app installed and logged in
- Python 3.8+
- No external dependencies (stdlib only)

## Usage

### Standalone

```bash
python3 sync_granola.py [--vault-dir PATH] [--days N] [--force]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--vault-dir PATH` | Output directory for meeting notes | `~/granola-notes` |
| `--days N` | Look back N days for documents | `7` |
| `--force` | Re-sync all documents, ignoring last-synced state | — |

### As a Claude Code skill

Copy `SKILL.md` and `sync_granola.py` into your project's `.claude/skills/sync-granola/` directory. Then invoke with `/sync-granola` or ask Claude to "sync granola notes".

## How it works

The script reads the Granola access token from `~/Library/Application Support/Granola/supabase.json` (standard macOS location), refreshes it if expired, and fetches documents via the Granola API. Each meeting is converted to a Markdown file with YAML frontmatter containing metadata (title, date, attendees) and optionally includes the full transcript.

Sync state is tracked in `.granola-sync-state.json` alongside the script, so subsequent runs only fetch new or updated meetings.
