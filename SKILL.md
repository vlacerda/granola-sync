---
name: sync-granola
description: Use when asked to sync, fetch, or pull meeting notes from Granola into the Obsidian vault. Runs the Python sync script that downloads new/updated meetings from the Granola API.
user_invocable: true
---

# Sync Granola

## Overview

Fetches new/updated meeting notes from the Granola API and writes them as Markdown files into monthly folders at `~/granola-notes/YYYY-MM/`. Also migrates any existing flat files into their monthly folders.

## When to Use

- User says "sync granola", "fetch meetings", "pull notes", "download meetings"
- Before summarizing meetings, to ensure notes are up to date

## Workflow

Run the sync script:

```bash
python3 ".claude/skills/sync-granola/sync_granola.py"
```

Options:

- `--vault-dir PATH` — Output directory for meeting notes (default: `~/granola-notes`)
- `--days N` — Look back N days (default: 7)
- `--force` — Re-sync all documents, ignoring last-synced state

Report the output to the user: how many documents were synced, any failures.

The script:

- Reads the Granola access token from `~/Library/Application Support/Granola/supabase.json`
- Refreshes the token if expired
- Fetches all documents from Granola API (paginated)
- Filters for new/updated docs using state file at `~/.granola-sync-state.json`
- Converts ProseMirror content to Markdown and fetches transcripts
- Writes `.md` files to `~/granola-notes/`
- Tracks sync state in `.granola-sync-state.json` inside this skill folder
