# TraceReview: case study

**The problem.** Data pulled out of a financial PDF is only useful if someone can see where each
number came from and trust that a person looked at it. A capital call notice is a good small
example: six fields, one arithmetic relationship, real consequences if a digit is wrong.

**What I built.** A local review workbench for one fixed capital call template. Upload a PDF,
get six fields with their source text and page position, see three rule results, click a field
to see its value framed in the real PDF, fix and check each field, confirm the record, and export
the confirmed version as JSON. Backend: FastAPI, SQLite, pdfplumber. Frontend: React, TypeScript,
PDF.js.

## Decisions worth explaining

**Money is a string, arithmetic is integer cents.** `"0.10" + "0.20"` is exactly `"0.30"`.
Inputs with a third decimal, an exponent or a stray comma are rejected instead of being
rounded into agreement. A blank value means "unknown", never zero.

**Passing rules is not a review.** The rule that total = investment + fee still passes when all
three amounts are ten times too large. So rules and human checks are separate states:
confirmation needs every rule to pass *and* an explicit "checked against PDF" on all six
fields, enforced on the server. There is no confidence score, because nothing here is
calibrated to produce one.

**Nothing is overwritten.** Each field keeps its source text and position, its initial
extraction, and its current value, in three places only one of which can change. Edits carry a
reason and appear in a history with before and after. Editing a confirmed field withdraws the
confirmation and clears the checks, and the old confirmation stays in the history.

**Concurrent edits are refused, not merged.** Every write states the version it saw. Two
windows editing the same record: the first save wins, the second is rejected with the draft
kept, and the user chooses when to reload. Export is built from one consistent read of the
confirmed version, so a late edit cannot leak into the file.

**The extraction faults are labelled as faults.** The parser is a deterministic template reader.
Three bundled samples carry a deliberately injected wrong candidate (a total ten times too
large, a missing due date) so the correction flow has something to correct. They are keyed to
the exact bytes of the bundled files and shown in the UI as "Preset extraction error (demo
fault)". This project does not claim a model made those mistakes.

## How it was checked

Backend tests cover exact money handling, each rule, parsing of the four samples against
hand-written expectations, import failures and cleanup, concurrent identical uploads, a hung
parser being killed, version conflicts across two sessions, a locked database, rollback when
writing history fails, and the export-versus-edit interleavings. Component tests cover drafts,
serial writes, conflicts and the unknown-outcome case. Browser tests drive a real Chrome
against the real backend and measure the rendered PDF canvas to prove the highlight box sits
on the printed value at three zoom levels, two window sizes and a device pixel ratio of 2.

## What it does not do

One template, USD only, single-page text PDFs, no OCR, no login, no multi-user permissions.
The reviewer name is a fixed label. The history is an application log, not tamper-proof. It
has not been evaluated on real documents and makes no accuracy claim.
