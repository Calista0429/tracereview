# TraceReview: Capital Call Notice Review Workbench

A working full-stack portfolio demo for a data-quality reviewer: turn a fund's capital call notice PDF into six structured fields, trace every value back to its place in the original PDF, correct what is wrong, and export only what a person has checked and confirmed.

Built with **React + TypeScript, FastAPI, and SQLite**, rendering the real PDF with PDF.js. All application code and interface copy use English.

This is an independent project with fictional funds and fictional documents. It is not affiliated with any company and does not describe any company's internal systems.

![A preset extraction error: the total rule fails and the printed value is highlighted in the original PDF](docs/screenshots/03-error-caught.png)

[Clean notice](docs/screenshots/02-clean-notice.png) · [Confirmed record](docs/screenshots/06-confirmed.png) · [Two-window conflict](docs/screenshots/12-version-conflict.png) · [Document list](docs/screenshots/13-document-list.png) · [Phone view](docs/screenshots/17-mobile-highlight.png)

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/architecture-dark.svg">
  <img alt="TraceReview architecture: the reviewer uses the React UI, which calls the FastAPI API; the API hands review and export requests to a versioned service backed by SQLite and the original PDF store, and hands uploads to an import service that runs a time-limited PDF worker process" src="docs/architecture/architecture-light.svg">
</picture>

Read it left to right: the reviewer works in the browser, the UI talks to one API, and the API splits into two paths. The **review path** (up) edits, checks, confirms and exports through version-checked transactions, calls the pure rule functions, and re-hashes the original PDF before it trusts it. The **import path** (down) hashes and de-duplicates an upload, parses it in a separate time-limited process, then writes the rows and the original together. Only the two stores sit in the local `./data` folder.

The diagram is generated with [Archify](https://github.com/tt-a1i/archify) from [`docs/architecture/architecture.json`](docs/architecture/architecture.json), and every component cites the source lines that support it, pinned to commit [`bf3390e`](https://github.com/Calista0429/tracereview/tree/bf3390ea2466e5c5bf11f612ec0552b5184615ab). Download [`architecture.html`](docs/architecture/architecture.html) and open it in a browser for the interactive version (find a node, trace a route between two components, see each component's cited sources). A high-resolution [PNG](docs/architecture/architecture.png) is also included.

| Layer | Implementation |
| --- | --- |
| Web | React 19, TypeScript, Vite, React Router, PDF.js; locally bundled IBM Plex Sans and Newsreader fonts, no CDN at runtime |
| API | Python 3.12, FastAPI, Pydantic; one error shape for every failure |
| Parsing | pdfplumber in a separate process with a 10 second limit; word boxes converted to page fractions with a top-left origin |
| Database | SQLite via SQLAlchemy 2.0 with WAL, enforced foreign keys and a version column on every record |
| Storage | Originals stored under their SHA-256, never under the upload name; written with an atomic create-if-absent |
| Tests | pytest, Vitest and Testing Library, Playwright in real Chrome |

Key design points:

- **Exact money.** `"0.10" + "0.20"` is exactly `"0.30"`. Bad input is rejected, not rounded into agreement.
- **Server-side gates.** Confirmation and export re-check the version, all rules, the six checks and the stored original's hash on the server. The disabled buttons are only hints.
- **No silent overwrites.** Stale writes return 409. The page keeps the draft and waits for an explicit reload, and it never retries a write whose outcome is unknown.
- **One consistent export.** The server reads one snapshot of the confirmed version, builds the bytes, then records the export. A concurrent edit yields either the complete older confirmed file or a version conflict, never a mixture.
- **Isolated parsing.** Uploads are hashed, de-duplicated, size-limited and parsed in a time-limited worker process that is killed on timeout. Failures leave no record and no stray files.

### API

All routes are under `/api/v1`.

| Method and path | Purpose |
| --- | --- |
| `GET /documents` | List documents, newest first |
| `POST /documents` | Upload a PDF (`multipart/form-data`, field `file`) |
| `GET /documents/{id}` | Fields, rules, history and current version |
| `GET /documents/{id}/file` | The stored original PDF |
| `PATCH /documents/{id}/fields` | Save changes (`expected_version`, `changes`, `reason`) |
| `POST /documents/{id}/verify` | Check or un-check one field |
| `POST /documents/{id}/confirm` | Confirm the record |
| `POST /documents/{id}/exports` | Download the confirmed version as JSON |

## Business workflow

**Upload a notice → read six extracted fields next to their PDF text → see three rule results → click a field to find its value in the PDF → correct it with a reason → check each field against the PDF → confirm → export JSON.**

| Screen | Working capabilities |
| --- | --- |
| Document list | Upload by choosing or dropping a PDF, import one of four bundled samples, duplicate detection with a link to the existing record, clear errors for unsupported files, rule outcome, review state and version per document |
| Review page | Original PDF rendered with PDF.js (fit width, 100%, 150%), a highlight box on the selected value, six editable fields showing the extracted value and the PDF text side by side, three rule results, per-field "Checked against PDF" boxes, save with a required reason, confirm, export, and a full history |
| Safety dialogs | Unsaved-changes prompt when leaving, version-conflict notice that keeps your draft, unknown-outcome notice when the connection drops mid-save |

The four bundled samples are fictional, and three of them carry a **deliberately injected extraction fault** so there is something to catch. The extractor itself is a deterministic template reader; it does not make these mistakes. See [Fault injection](#fault-injection).

## Use cases

Every screenshot below was captured by a scripted user (real Chrome, real backend, fresh database) clicking and typing through the product: [`frontend/e2e/usecases.spec.ts`](frontend/e2e/usecases.spec.ts).

### 1. First visit

With nothing imported, the page offers an upload area and four samples. Samples that carry a demo fault say so.

![Empty document list with the upload area and four samples](docs/screenshots/01-home-empty.png)

### 2. A clean notice still needs a human

All six fields were extracted correctly and all three rules pass. The counter still reads **0 of 6 fields checked** and **Confirm review** stays disabled, with the reason listed under the buttons. Passing rules means "no problem found", never "reviewed".

![Normal notice: three rules pass, zero fields checked, confirm disabled](docs/screenshots/02-clean-notice.png)

### 3. Catch a mistake and trace it to the PDF

In the preset-error sample the extractor recorded `500000.00` for the total while the PDF prints `50,000.00`. The **Total matches line items** rule fails and states the exact difference. Clicking a field frames its value in the PDF with a highlight and a label; the row shows the extracted value and the PDF text side by side.

![Total rule failing with the highlighted 50,000.00 in the PDF](docs/screenshots/03-error-caught.png)

### 4. Correct it, with a reason, and keep the history

Edits stay a draft until you press **Save changes**, and a reason is required. While a draft exists, confirmation and the check boxes are unavailable and the rules say they describe the saved version.

![Draft correction with a reason and the unsaved-changes notice](docs/screenshots/04-correct-with-reason.png)

After saving, the rule passes, the field is tagged **Edited**, the original extraction is still shown, and the history records the old and new value, the reason, who and when.

![After saving: rule passes, extracted value kept, history shows 500000.00 to 50000.00](docs/screenshots/05-history-before-after.png)

### 5. Check every field, then confirm

Each field has its own **Checked against PDF** box. Confirmation unlocks only when all rules pass and all six boxes are ticked, and the server enforces the same gates. A confirmed record is read-only.

![Confirmed record: six of six fields checked, read-only fields, Edit and Export available](docs/screenshots/06-confirmed.png)

### 6. Export the confirmed version

**Export JSON** downloads a file built by the server from its stored record: exact string amounts, the extracted value and the PDF text for every field, the box on the page, the rule results, who confirmed and when, and the business history. The export itself is logged. A complete example is in [`docs/examples/amount-error-confirmed-export.json`](docs/examples/amount-error-confirmed-export.json).

![Export status line and the history including the generated export](docs/screenshots/07-export-json.png)

```json
{
  "schema_version": "1.0",
  "document": { "filename": "amount-error.pdf", "version": 9, "status": "CONFIRMED", "extraction_profile": "total_extra_zero" },
  "fields": [
    {
      "key": "total_due",
      "current_value": "50000.00",
      "initial_extracted_value": "500000.00",
      "source_text": "50,000.00",
      "source_parse_status": "valid",
      "evidence": { "page": 1, "bbox": { "x": 0.504, "y": 0.536, "width": 0.082, "height": 0.013 } },
      "verified": true,
      "verified_by": "local-reviewer"
    }
  ],
  "rules": { "ruleset_version": "v1", "results": [ { "id": "R002_TOTAL", "status": "PASS" } ] },
  "history": [ "IMPORTED", "FIELDS_UPDATED", "FIELD_VERIFICATION_CHANGED (×6)", "CONFIRMED" ]
}
```

*(Abbreviated; the history entries in the real file carry the full payloads.)*

### 7. Editing a confirmed record withdraws the confirmation

**Edit fields** unlocks the record and warns that saving a change withdraws the confirmation.

![Editing a confirmed record: warning that saving withdraws the confirmation](docs/screenshots/08-edit-confirmed-record.png)

Saving a real change clears all six checks and returns the record to **Needs review**. Here the fee edit makes the total fail (`50100.00` against `50000.00`), so the reviewer has to resolve it and check everything again. The earlier confirmation stays in the history.

![After the edit: needs review, zero checked, total rule failing with a negative difference](docs/screenshots/09-confirmation-withdrawn.png)

### 8. A value the extractor missed is still in the PDF

In this sample the due date was left empty by the (injected) extraction fault, but the value is printed in the PDF and can be located. The row says **Nothing extracted** and shows the PDF text; the highlight sits on the printed date. The reviewer types it in, saves, and can then check it.

![Due date: nothing extracted, PDF text 2026-11-24, highlighted in the PDF](docs/screenshots/10-missing-extraction.png)

### 9. A value with no source cannot be checked or confirmed

Here the due-date label is printed but its value is blank. There is no location to show, so the viewer says nothing is highlighted, the row is tagged **No source location**, its check box is disabled, and two rules fail. Typing a value in does not invent a location, so this record cannot be confirmed until a corrected original is supplied.

![Missing source: no location, check box disabled, two rules failing, confirm disabled](docs/screenshots/11-missing-source-blocked.png)

### 10. Two windows, one record

Window one ticks a field, moving the record to a newer version. Window two still holds the old version and tries to save a rename. The save is refused, the draft stays exactly as typed, and the user decides when to reload. Nothing is overwritten and nothing is retried automatically.

![Version conflict notice in the stale window with the draft preserved and a Reload latest button](docs/screenshots/12-version-conflict.png)

### 11. The document list, duplicates and unsupported files

The list shows each record's rule outcome, review state and version.

![Document list with four records in different states](docs/screenshots/13-document-list.png)

Importing the same bytes again does not create or overwrite anything. It explains and links to the existing record.

![Duplicate upload: already imported, with a link to the existing record](docs/screenshots/14-duplicate-upload.png)

Unsupported files are refused with a specific reason and leave no record behind. This one is a scanned page with no text layer.

![Rejected upload: file name, reason, nothing imported](docs/screenshots/15-rejected-file.png)

### 12. Leaving with unsaved changes

Navigating away with a draft asks first. The draft is never stored anywhere else, and reloading the page discards it.

![Leave this page? dialog over a record with a half-typed name](docs/screenshots/16-unsaved-changes.png)

### 13. On a phone

At phone width the PDF stacks above the fields, selecting a field scrolls to its highlight, and every control stays reachable.

| Highlight in the PDF | Fields below |
| --- | --- |
| ![Phone: highlighted due date in the PDF](docs/screenshots/17-mobile-highlight.png) | ![Phone: fields with extracted and PDF text](docs/screenshots/18-mobile-fields.png) |

## Rules and definitions

| Item | Definition |
| --- | --- |
| Fields | Fund name, currency (USD only), payment due date, investment contribution, management fee, total amount due. Each is read by its printed label on one fixed template (`capital_call_v1`). |
| Money | A decimal string end to end, for example `"50000.00"`. Arithmetic uses integer cents. Up to two decimals, `0.00` to `999,999,999.99`, no exponents, no floats, no rounding to make a sum fit. Blank means unknown, never zero. |
| `R001_REQUIRED` | All six current values are present and valid. |
| `R002_TOTAL` | Investment contribution + management fee equals total amount due, exactly, in cents. Not evaluated while an amount is missing or invalid. |
| `R003_EVIDENCE` | Each field has source text and a valid box on page 1 that belongs to this file. |
| Needs review / Confirmed | A record is confirmed only when all rules pass **and** all six fields are checked **and** the stored original still matches its SHA-256. Any real edit clears the checks and withdraws a confirmation. |
| Version | Starts at 1. Every real change (edit, check, confirmation) adds exactly one. Repeating a no-op adds nothing. Every write names the version it saw; a stale write is refused with 409. |
| Three values per field | **Source** (PDF text, parsed value, box; never edited), **initial extraction** (never edited), **current value** (changes only through Save). |
| Time | Timestamps are UTC and labelled as such. |

### Fault injection

| Sample | PDF says | Injected candidate | Shows |
| --- | --- | --- | --- |
| Normal notice | all correct | none | rules passing is not review |
| Preset total error | total `50,000.00` | total `500000.00` | a failing rule, a correction, the history |
| Preset missing due date | due date present | due date empty | filling a value from the PDF |
| Missing source value | blank due date | none (nothing to extract) | a record that cannot be confirmed |

Faults are keyed to the SHA-256 of the bundled files in [`fixtures/manifest.json`](fixtures/manifest.json). Uploads can never request one, and the UI labels them **Preset extraction error (demo fault)**.

## Data model

- `documents`: file hash (unique), display name, page size, template and parser version, extraction profile, status, version, timestamps, confirmation.
- `document_fields`: six rows per document; source text, parsed value and box (never edited), initial extraction (never edited), current value, check state.
- `audit_events`: append-only history with a global increasing id, the document version, event type, actor, UTC time and payload. Rule results are not stored; they are recomputed from the saved values, and confirmation and export events keep the snapshot they used.

## Run locally

Use **Python 3.12** and **Node.js 22.12 or newer** (developed on 3.12.1 and Node 24). Run commands from the repository root.

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r backend/requirements.txt
```

```bash
cd frontend && npm ci
```

Then start two terminals. The backend binds to `127.0.0.1` only and runs a single worker.

```bash
cd backend && ../.venv/bin/python -m app
```

```bash
cd frontend && npm run dev
```

Open <http://localhost:5173>. Data is written under `./data` (git-ignored); set `TRACEREVIEW_DATA_DIR` to use another folder. The samples are copied from `fixtures/` into the frontend automatically (`npm run sync-samples`). To regenerate them byte for byte: `.venv/bin/python scripts/generate_fixtures.py`.

A 90-second path: import **Preset total error**, click *Total amount due* to see the highlight, read why the rule fails, correct to `50,000` with a reason, save, tick the six boxes, confirm, export, then edit a field and watch the confirmation withdraw. The script is in [`docs/demo-script.md`](docs/demo-script.md).

## Verify

```bash
cd backend && ../.venv/bin/python -m pytest
```

```bash
cd frontend && npm run test -- --run && npm run build
```

```bash
cd frontend && npx playwright test
```

Last run: **235** backend tests, **95** component and unit tests, a clean type-check and production build, and **12** browser tests. The browser tests start the backend on a fresh temporary data folder and the dev server themselves, then drive a real Chrome. They measure ink in the rendered PDF canvas under the highlight box at fit width, 100% and 150%, at 1440 px and 390 px, with a device pixel ratio of 2, and check that a box shifted off the row finds no ink. To use Playwright's bundled browser instead: `npx playwright install chromium`, then `PW_CHANNEL= npx playwright test`.

[`docs/acceptance.md`](docs/acceptance.md) maps each acceptance item (A01 to A20) to the tests that check it.

To regenerate the screenshots in this README (13 more scripted user steps, skipped by default):

```bash
cd frontend && SCREENSHOTS=1 npx playwright test e2e/usecases.spec.ts
```

## Repository layout

```text
backend/app/    FastAPI app, domain rules, PDF parser, services
backend/tests/  pytest suite
frontend/src/   React + TypeScript + Vite
frontend/e2e/   Playwright: behaviour specs and the screenshot journey
fixtures/       fictional PDFs, manifest, hand-written expected values
scripts/        fixture generator
docs/           acceptance map, case study, demo script, screenshots, example export
```

A one-page write-up of the design decisions is in [`docs/case-study.md`](docs/case-study.md).

## Scope and limitations

This demo supports one template, USD only, single-page English PDFs with a text layer, up to 5 MiB. It has no OCR, no other templates or currencies, no login, no multi-user permissions and no external model or network service. It runs locally for one person: the reviewer name `local-reviewer` is a label, not an authenticated identity.

The history is an application log, not tamper-proof storage. The API has no authentication, rate limiting or Origin check, so do not expose the backend to a network. The demo recording is not part of the repository yet. This project demonstrates a review workflow on fictional data; it makes no accuracy claim about real documents and is not a compliance product.
