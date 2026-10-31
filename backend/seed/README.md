# Demo dataset (Operating Systems)

`os_dataset.json` (committed) holds the subject/topic structure, the five Gate Smashers video IDs, and the 31 user-supplied timestamp segments
(all marked `unverified`, source: collected with YouTube Ask Gemini, pending independent verification).

Two folders are **git-ignored** because they hold third-party content:

- `pdfs/` — the five course PDFs, with these exact filenames:
  `Process-Management.pdf`, `CPU-Scheduling-and-Algorithm-.pdf`, `synchronization.pdf`, `Deadlocks.pdf`, `Memory-management-.pdf`
- `transcripts/` — YouTube caption JSON, created by `python scripts/fetch_transcripts.py`

On startup the backend seeds the default tenant from these files. Anything missing is skipped and logged (never fabricated); add the file and restart to top up.
Tests that need the PDFs are skipped when `pdfs/` is empty; the agent-flow tests expect the full dataset.
