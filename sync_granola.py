#!/usr/bin/env python3
"""Granola to Obsidian Sync — fetches meeting notes from Granola API and writes
them as Markdown files into an Obsidian vault directory.

Usage:
    python3 sync_granola.py [--vault-dir PATH] [--days N] [--force]

Options:
    --vault-dir PATH  Output directory for meeting notes (default: ~/granola-notes)
    --days N          Look back N days for documents (default: 7)
    --force           Re-sync all documents, ignoring last-synced state
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- Configuration -----------------------------------------------------------
TOKEN_PATH = Path.home() / "Library" / "Application Support" / "Granola" / "supabase.json"
VAULT_DIR = Path.home() / "granola-notes"
STATE_FILE = Path(__file__).parent / ".granola-sync-state.json"
DAYS_BACK = 7

# --- HTTP helpers ------------------------------------------------------------

def _post(url: str, headers: dict, body: dict) -> dict | str:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **headers,
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        text = raw.decode("utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


# --- Token management --------------------------------------------------------

def get_access_token() -> str:
    raw = TOKEN_PATH.read_text()
    data = json.loads(raw)
    tokens = json.loads(data["workos_tokens"])
    access_token = tokens["access_token"]

    # Refresh if expired or within 5 min of expiry
    expires_at = tokens["obtained_at"] + tokens["expires_in"] * 1000
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    if now_ms >= expires_at - 5 * 60 * 1000:
        refreshed = _post(
            "https://api.granola.ai/v1/refresh-access-token",
            {"Authorization": f"Bearer {access_token}"},
            {"refresh_token": tokens["refresh_token"], "provider": "workos"},
        )
        access_token = refreshed["access_token"]

    return access_token


# --- Granola API -------------------------------------------------------------

def fetch_all_documents(headers: dict) -> list[dict]:
    all_docs = []
    offset = 0
    limit = 100
    while True:
        result = _post(
            "https://api.granola.ai/v2/get-documents",
            headers,
            {"limit": limit, "offset": offset, "include_last_viewed_panel": True},
        )
        docs = result.get("docs", [])
        all_docs.extend(docs)
        if len(docs) < limit:
            break
        offset += limit
    return all_docs


def fetch_transcript(headers: dict, doc_id: str) -> list[dict] | None:
    try:
        result = _post(
            "https://api.granola.ai/v1/get-document-transcript",
            headers,
            {"document_id": doc_id},
        )
        return result if isinstance(result, list) else None
    except Exception:
        return None


# --- ProseMirror to Markdown -------------------------------------------------

def pm2md(node: dict, indent: str = "") -> str:
    if not node:
        return ""
    if node.get("type") == "text":
        return node.get("text", "")

    children = node.get("content", [])
    ntype = node.get("type", "")

    if ntype == "doc":
        return "".join(pm2md(c, "") for c in children)

    if ntype == "heading":
        level = (node.get("attrs") or {}).get("level", 1)
        text = "".join(pm2md(c, indent) for c in children)
        return "#" * level + " " + text + "\n\n"

    if ntype == "paragraph":
        text = "".join(pm2md(c, indent) for c in children)
        return text if indent else text + "\n\n"

    if ntype == "bulletList":
        return "".join(pm2md(c, indent) for c in children)

    if ntype == "orderedList":
        tab = "\t"
        parts = []
        for i, c in enumerate(children):
            if c.get("type") != "listItem":
                parts.append(pm2md(c, indent))
                continue
            inner = c.get("content", [])
            for j, x in enumerate(inner):
                if j == 0:
                    parts.append(f"{indent}{i + 1}. {pm2md(x, indent + tab)}\n")
                else:
                    parts.append(pm2md(x, indent + tab))
        return "".join(parts)

    if ntype == "listItem":
        tab = "\t"
        parts = []
        for i, c in enumerate(children):
            if i == 0:
                parts.append(f"{indent}- {pm2md(c, indent + tab)}\n")
            else:
                parts.append(pm2md(c, indent + tab))
        return "".join(parts)

    return "".join(pm2md(c, indent) for c in children)


# --- Transcript formatting ---------------------------------------------------

def format_transcript(entries: list[dict]) -> str:
    if not entries:
        return ""
    md = "\n---\n\n## Transcript\n\n"
    current_speaker = None
    for entry in entries:
        speaker = "You" if entry.get("source") == "microphone" else "Guest"
        if speaker != current_speaker:
            current_speaker = speaker
            md += f"\n**{speaker}** ({entry.get('start_timestamp', '')}):\n"
        md += entry.get("text", "") + " "
    return md.strip() + "\n"


# --- File writing ------------------------------------------------------------

def safe_filename(title: str, created: str) -> tuple[str, str]:
    """Return (month_folder, filename) for a meeting note.

    month_folder is YYYY-MM derived from the created date.
    """
    date_str = created[:10]  # YYYY-MM-DD from ISO string
    month_folder = date_str[:7]  # YYYY-MM
    safe_title = re.sub(r'[/\\?%*:|"<>]', "-", title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip()
    return month_folder, f"{date_str} - {safe_title}.md"


def build_markdown(doc: dict, content_md: str, transcript_md: str) -> str:
    title = doc.get("title") or "Untitled Meeting"
    created = doc.get("created_at") or datetime.now(timezone.utc).isoformat()
    updated = doc.get("updated_at") or datetime.now(timezone.utc).isoformat()
    attendees = [
        a.get("name") or a.get("email")
        for a in (doc.get("people", {}).get("attendees") or [])
        if a.get("name") or a.get("email")
    ]

    fm = "---\n"
    fm += f'granola_id: "{doc["id"]}"\n'
    fm += f'title: "{title.replace(chr(34), chr(92) + chr(34))}"\n'
    fm += f"created: {created}\n"
    fm += f"updated: {updated}\n"
    if attendees:
        fm += "attendees:\n"
        for name in attendees:
            fm += f'  - "{name.replace(chr(34), chr(92) + chr(34))}"\n'
    fm += "type: granola-note\n"
    fm += "---\n\n"

    full = fm + f"# {title}\n\n"
    if content_md:
        full += content_md + "\n"
    if doc.get("notes_markdown"):
        full += "\n---\n\n## Personal Notes\n\n" + doc["notes_markdown"] + "\n"
    if transcript_md:
        full += transcript_md
    return full


# --- Migration ---------------------------------------------------------------

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2})-\d{2} - .+\.md$")


def migrate_to_monthly_folders(vault: Path) -> int:
    """Move any date-prefixed .md files from the vault root into YYYY-MM/ subfolders."""
    moved = 0
    for f in vault.iterdir():
        if not f.is_file():
            continue
        m = _DATE_PREFIX_RE.match(f.name)
        if not m:
            continue
        month_dir = vault / m.group(1)
        month_dir.mkdir(exist_ok=True)
        dest = month_dir / f.name
        f.rename(dest)
        moved += 1
    if moved:
        print(f"Migrated {moved} file(s) into monthly folders")
    return moved


# --- Main sync logic ---------------------------------------------------------

def sync(days_back: int = DAYS_BACK, force: bool = False, vault_dir: Path = VAULT_DIR) -> list[dict]:
    access_token = get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    # Fetch all documents
    all_docs = fetch_all_documents(headers)

    # Load sync state
    sync_state: dict[str, str] = {}
    if not force:
        try:
            sync_state = json.loads(STATE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # Filter for new/updated documents within the lookback window
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    docs_to_sync = []
    for doc in all_docs:
        doc_date = datetime.fromisoformat(
            (doc.get("created_at") or doc.get("updated_at") or datetime.now(timezone.utc).isoformat())
            .replace("Z", "+00:00")
        )
        if doc_date < cutoff:
            continue
        last_synced = sync_state.get(doc["id"])
        if last_synced and not force:
            updated = doc.get("updated_at", "")
            if updated and datetime.fromisoformat(updated.replace("Z", "+00:00")) <= datetime.fromisoformat(last_synced.replace("Z", "+00:00")):
                continue
        docs_to_sync.append(doc)

    # Ensure output directory exists
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Migrate any flat files from vault root into monthly folders
    migrate_to_monthly_folders(vault_dir)

    results = []
    for doc in docs_to_sync:
        try:
            # Convert ProseMirror content
            content_md = ""
            panel = doc.get("last_viewed_panel")
            if panel and isinstance(panel.get("content"), dict) and panel["content"].get("type") == "doc":
                content_md = re.sub(r"\n{3,}", "\n\n", pm2md(panel["content"])).strip()

            # Fetch transcript
            transcript_md = ""
            transcript = fetch_transcript(headers, doc["id"])
            if transcript:
                transcript_md = format_transcript(transcript)

            # Build and write markdown
            full_md = build_markdown(doc, content_md, transcript_md)
            title = doc.get("title") or "Untitled Meeting"
            created = doc.get("created_at") or datetime.now(timezone.utc).isoformat()
            month_folder, filename = safe_filename(title, created)
            out_dir = vault_dir / month_folder
            out_dir.mkdir(parents=True, exist_ok=True)
            filepath = out_dir / filename
            filepath.write_text(full_md, encoding="utf-8")

            sync_state[doc["id"]] = doc.get("updated_at", datetime.now(timezone.utc).isoformat())
            results.append({"synced": True, "title": title, "filename": f"{month_folder}/{filename}"})
        except Exception as e:
            results.append({"synced": False, "title": doc.get("title", "Unknown"), "error": str(e)})

    # Persist state
    STATE_FILE.write_text(json.dumps(sync_state, indent=2))

    if not results:
        print(f"No new or updated documents to sync (checked {len(all_docs)} docs)")
    else:
        synced = sum(1 for r in results if r["synced"])
        failed = len(results) - synced
        print(f"Synced {synced} document(s), {failed} failed (checked {len(all_docs)} total)")
        for r in results:
            status = "OK" if r["synced"] else f"FAIL: {r.get('error', '?')}"
            print(f"  [{status}] {r['title']}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Granola meeting notes to Obsidian")
    parser.add_argument("--vault-dir", type=Path, default=VAULT_DIR, help="Output directory for meeting notes (default: ~/granola-notes)")
    parser.add_argument("--days", type=int, default=DAYS_BACK, help="Look back N days (default: 7)")
    parser.add_argument("--force", action="store_true", help="Re-sync all documents ignoring state")
    args = parser.parse_args()
    sync(days_back=args.days, force=args.force, vault_dir=args.vault_dir)
