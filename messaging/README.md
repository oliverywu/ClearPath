# Cleared for Takeoff

A pharmaceutical regulatory AI agent (v1) for international clinical-trial drug shipments.
It extracts labeling requirements from raw regulatory source text into a structured JSON
database, then answers questions about them through an interactive command-line chatbot that
only cites retrieved passages -- it never invents a regulation, and explicitly says when a
jurisdiction has no matching data.

This v1 is plain Python + the Anthropic API, plus an optional Photon messaging bridge so the
same agent can be reached over iMessage. It does **not** integrate Chalk, and does not build a
full shipment planner yet.

## What's in here

- `data/*.txt` -- raw regulatory source text per jurisdiction (`us.txt`, `eu.txt`, `japan.txt`,
  `canada.txt`). You provide/paste the real source text here; the agent never fabricates it.
- `models.py` -- the `Regulation` record schema (jurisdiction, article, verbatim text, source
  URL, effective date, source type, topic, notes) and the JSON schema used for extraction.
- `extract_regulations.py` -- reads `data/*.txt` and writes `regulations.json`, using Claude
  with structured outputs to pull out only labeling-related provisions. Never invents a
  citation, URL, or date that isn't literally in the source.
- `regulations.json` -- the generated structured database (output of the step above).
- `retrieval.py` -- simple, dependency-free keyword-overlap search over `regulations.json`,
  usable per-jurisdiction or across all jurisdictions.
- `compare.py` -- cross-jurisdiction comparison: retrieves per jurisdiction independently and
  asks Claude to compare only what was actually retrieved, flagging any jurisdiction with no
  match.
- `change_detector.py` -- simulated regulation-change detection: diffs `regulations.json`
  against a saved `regulations_snapshot.json` baseline (added / removed / modified records).
- `agent.py` -- the interactive CLI chatbot that ties retrieval + Claude together.
- `photon_bridge.py` -- polls the Photon Platform (Beta) for new inbound iMessage questions,
  answers each with `agent.answer_question()` (unchanged, reused as-is), and replies in the same
  thread. Persists its poll cursor and a set of already-answered message ids to
  `.photon_bridge_state.json` so restarting never re-answers a message.
- `tests/` -- pytest unit tests for retrieval, comparison, change detection, extraction, and the
  Photon bridge (all external calls -- Claude and Photon -- are mocked, so the full suite runs
  without any API key or network access).

## Install

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Set your API key via a local `.env` file (loaded automatically with `python-dotenv`; `.env` is
gitignored and never committed):

```bash
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=your-actual-key
```

Alternatively, export it directly in your shell (`export ANTHROPIC_API_KEY=...`), or run
`ant auth login` and skip this step entirely -- the SDK picks up the active profile
automatically.

## Run it

1. **Extract regulations from the raw source text:**

   ```bash
   python extract_regulations.py
   ```

   This writes `regulations.json`. A jurisdiction whose `data/<name>.txt` is empty (e.g.
   `canada.txt` by default) simply yields zero records for that jurisdiction -- it shows up as
   "no data available" everywhere downstream, rather than being skipped silently or faked.

2. **Save a baseline snapshot** (needed once, so later runs have something to diff against):

   ```bash
   python change_detector.py --snapshot
   ```

3. **Chat with the agent:**

   ```bash
   python agent.py
   ```

   Inside the REPL:
   - Ask a plain question, e.g. `What must appear on the label of an investigational drug in the US?`
   - `jurisdiction Japan <question>` -- scope a question to one jurisdiction
   - `compare <topic>` -- e.g. `compare storage conditions on the label`
   - `check updates` -- run the simulated change-detection report against the last snapshot
   - `exit` / `quit`

4. **Simulate a regulation change** (demo of requirement #6): edit one of the `data/*.txt`
   files (e.g. tweak the EU storage-conditions wording), re-run `python extract_regulations.py`,
   then run `check updates` inside the chatbot (or `python change_detector.py` directly) to see
   the added/removed/modified report against the saved snapshot.

5. **(Optional) Talk to the agent over iMessage via Photon:**

   Add to `.env`: `PHOTON_PROJECT_ID`, `PHOTON_API_KEY` (needs `project:read` + `project:write`
   permissions). See "Photon setup" below for where these come from.

   **Start the bridge:**

   ```bash
   python photon_bridge.py
   ```

   It polls every few seconds for new inbound iMessage text, answers each one with the same
   `agent.answer_question()` logic as the CLI chatbot, and replies in the same thread. Leave it
   running in a terminal while you test from your phone.

   **Stop the bridge:** `Ctrl+C`. It persists its poll cursor and the set of already-answered
   message ids to `.photon_bridge_state.json` before exiting, so restarting it later does not
   re-answer anything already handled.

## Photon setup (for the optional iMessage bridge)

1. Create a project in the Photon Beta dashboard (`app.beta.photon.codes`) and copy its
   **Project ID** (`pho_prj_...`) from Settings.
2. Create an **API key** for that project with both `project:read` and `project:write`
   permissions, and copy it immediately (it's shown only once).
3. In the project's **iMessage** section, add your own phone number or Apple email as the
   sender identity, then assign a **shared line** -- this gives you the agent's number.
4. Add `PHOTON_PROJECT_ID` and `PHOTON_API_KEY` to `.env`. Never paste these into a chat,
   commit, or print them -- `.env` is already gitignored.
5. Text the assigned agent number from your own phone with a regulatory question. The bridge
   picks it up on its next poll and replies in the same thread with jurisdiction-cited answers
   and the same missing-data/unverified-source warnings as the CLI chatbot.

## Run the tests

```bash
pytest
```

Tests mock the Anthropic and Photon clients, so they run without any API key set and without
network access.

## Design notes

- **No fabrication.** Extraction is instructed to return `null` for any article number, URL,
  or effective date not literally present in the source text, and to return an empty list
  rather than invent content for a jurisdiction with no labeling-relevant text.
- **Source provenance is tracked.** Each record carries a `source_type`
  (`verbatim_regulation` / `secondary_summary` / `translation`) and `notes` field, so the
  chatbot can flag when a passage is a summary or translation that should be verified against
  the official text, rather than presenting everything as equally authoritative.
- **Retrieval is deliberately simple.** Keyword-overlap scoring, no embeddings/vector DB --
  easy to unit test and reason about for a v1.
- **Change detection is simulated**, not a live regulatory feed -- see `change_detector.py`.
- **The Photon bridge never touches regulation logic.** It only extracts text from inbound
  messages and calls `agent.answer_question()` unchanged -- citations, missing-data notices,
  and secondary-source/translation warnings all come through exactly as in the CLI chatbot.
- **Duplicate-safe by construction, including across restarts.** Already-answered message ids
  are persisted to `.photon_bridge_state.json`, and every reply also carries a Photon
  idempotency key derived from the source message id -- so even if the bridge crashes right
  after a reply actually went out but before it recorded that locally, retrying is safe.
- **A failure never silently drops a message.** If listing, answering, or sending fails, that
  message is simply left unprocessed and is retried on the next poll -- nothing is marked done
  until a reply has actually been sent.
