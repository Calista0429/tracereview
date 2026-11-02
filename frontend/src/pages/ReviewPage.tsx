import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router-dom";

import { ApiError, NetworkError, documentApi } from "../api/documents";
import { computeDraft, isDirty, type Drafts } from "../domain/fieldInput";
import {
  FIELD_KEYS,
  FIELD_LABELS,
  type DocumentDetail,
  type FieldKey,
} from "../domain/types";
import { AuditHistory } from "../features/review/AuditHistory";
import { FieldEditor } from "../features/review/FieldEditor";
import { PdfEvidenceViewer } from "../features/review/PdfEvidenceViewer";
import { ValidationResults } from "../features/review/ValidationResults";
import { downloadBlob } from "../lib/download";
import { formatUtc, isPresetFault, profileLabel, STATUS_TEXT } from "../lib/format";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean }
  | { status: "ready"; doc: DocumentDetail };

type FileState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; blob: Blob };

type Busy = null | "save" | "verify" | "confirm" | "reload" | "export";

interface Notice {
  kind: "error" | "conflict" | "unknown";
  message: string;
}

const REASON_MAX = 200;

const CONFLICT_MESSAGE =
  "This document was changed in another window or tab. Your draft is still here. Reload the latest version, check it, then save again.";
const UNKNOWN_MESSAGE =
  "We could not confirm whether this change was saved. Your draft is still here. Reload the latest version to check before trying again.";

function describe(error: unknown, action: string): string {
  if (error instanceof NetworkError) return `The server could not be reached while ${action}.`;
  if (error instanceof ApiError) return error.message;
  return `Something went wrong while ${action}.`;
}

export function ReviewPage() {
  const { id = "" } = useParams();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [file, setFile] = useState<FileState>({ status: "loading" });
  const [drafts, setDrafts] = useState<Drafts>({});
  const [reason, setReason] = useState("");
  const [serverErrors, setServerErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [selectedKey, setSelectedKey] = useState<FieldKey | null>(null);
  const [unlocked, setUnlocked] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const busyRef = useRef(false);
  const aliveRef = useRef(true);
  const restoreFocusId = useRef<string | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const loadDocument = useCallback(async () => {
    try {
      const doc = await documentApi.get(id);
      return { status: "ready", doc } as const;
    } catch (error) {
      return {
        status: "error",
        message: describe(error, "opening the document"),
        notFound: error instanceof ApiError && error.code === "DOCUMENT_NOT_FOUND",
      } as const;
    }
  }, [id]);

  // Load the record and its original whenever the route changes; a late answer for an
  // earlier id is dropped so it can never overwrite the document now on screen.
  useEffect(() => {
    let cancelled = false;
    setLoad({ status: "loading" });
    setFile({ status: "loading" });
    setDrafts({});
    setReason("");
    setServerErrors({});
    setSelectedKey(null);
    setUnlocked(false);
    setNotice(null);
    void loadDocument().then((result) => {
      if (!cancelled) setLoad(result);
    });
    documentApi
      .getFile(id)
      .then((blob) => {
        if (!cancelled) setFile({ status: "ready", blob });
      })
      .catch((error: unknown) => {
        if (!cancelled) setFile({ status: "error", message: describe(error, "loading the original PDF") });
      });
    return () => {
      cancelled = true;
    };
  }, [id, loadDocument]);

  const doc = load.status === "ready" ? load.doc : null;
  const fields = doc?.fields ?? [];
  const draft = useMemo(() => computeDraft(fields, drafts), [fields, drafts]);
  const dirty = useMemo(() => isDirty(fields, drafts), [fields, drafts]);
  const reasonText = reason.trim();
  const reasonValid = reasonText.length > 0 && [...reasonText].length <= REASON_MAX;
  const hasFormatErrors = Object.keys(draft.errors).length > 0;

  const isConfirmed = doc?.status === "CONFIRMED";
  const inputsLocked = busy !== null || (isConfirmed && !unlocked);
  const checkedCount = fields.filter((f) => f.verified).length;
  const rulesPass = doc?.rules.every((r) => r.status === "PASS") ?? false;
  const fileReady = file.status === "ready";

  const confirmBlockers: string[] = [];
  if (dirty) confirmBlockers.push("Save or discard your edits first.");
  if (!rulesPass) confirmBlockers.push("Resolve the failing rule checks.");
  if (checkedCount < FIELD_KEYS.length) confirmBlockers.push("Check all six fields against the PDF.");
  if (!fileReady) confirmBlockers.push("The original PDF must load before you can confirm.");
  const canConfirm = doc?.status === "REVIEW_REQUIRED" && busy === null && confirmBlockers.length === 0;
  const canExport = isConfirmed && !dirty && busy === null;
  const canSave = doc !== null && busy === null && draft.changes.length > 0 && !hasFormatErrors && reasonValid;

  // A check box is disabled while its write is in flight, which drops keyboard focus.
  // Put focus back when the request ends so Tab continues from the same place.
  useEffect(() => {
    if (busy !== null || restoreFocusId.current === null) return;
    document.getElementById(restoreFocusId.current)?.focus();
    restoreFocusId.current = null;
  }, [busy]);

  // Closing or reloading the tab with a draft asks the browser to confirm first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname,
  );

  /** One write at a time: a second request never starts while another is in flight. */
  async function run(kind: Exclude<Busy, null>, work: () => Promise<DocumentDetail>, onDone?: () => void) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(kind);
    setNotice(null);
    setInfo(null);
    setServerErrors({});
    try {
      const next = await work();
      if (!aliveRef.current) return;
      setLoad({ status: "ready", doc: next });
      onDone?.();
    } catch (error) {
      if (aliveRef.current) handleWriteError(error, kind);
    } finally {
      busyRef.current = false;
      if (aliveRef.current) setBusy(null);
    }
  }

  function handleWriteError(error: unknown, kind: Exclude<Busy, null>) {
    if (error instanceof NetworkError) {
      setNotice({ kind: "unknown", message: kind === "reload" ? describe(error, "reloading") : UNKNOWN_MESSAGE });
      return;
    }
    if (error instanceof ApiError) {
      if (error.code === "VERSION_CONFLICT" || error.code === "WRITE_CONFLICT") {
        setNotice({ kind: "conflict", message: CONFLICT_MESSAGE });
        return;
      }
      if (error.code === "INVALID_FIELD_VALUE" && Array.isArray(error.details.errors)) {
        const byKey: Partial<Record<FieldKey, string>> = {};
        for (const item of error.details.errors as { key: FieldKey; message: string }[]) {
          byKey[item.key] = item.message;
        }
        setServerErrors(byKey);
      }
      setNotice({ kind: "error", message: error.message });
      return;
    }
    setNotice({ kind: "error", message: "Something went wrong. Reload the latest version and try again." });
  }

  if (!doc || !id) {
    return <LoadingOrError load={load} onRetry={() => void loadDocument().then(setLoad)} />;
  }

  const selectedField = selectedKey ? fields.find((f) => f.key === selectedKey) : undefined;
  const selection =
    selectedKey && selectedField
      ? { key: selectedKey, label: FIELD_LABELS[selectedKey], evidence: selectedField.evidence }
      : null;

  const formErrors = { ...serverErrors, ...draft.errors };

  function save() {
    if (!doc || !canSave) return;
    void run(
      "save",
      () => documentApi.updateFields(doc.id, { expectedVersion: doc.version, changes: draft.changes, reason: reasonText }),
      () => {
        setDrafts({});
        setReason("");
        setUnlocked(false);
      },
    );
  }

  function toggleChecked(key: FieldKey, checked: boolean) {
    if (!doc) return;
    restoreFocusId.current = `check-${key}`;
    void run("verify", () =>
      documentApi.verifyField(doc.id, { expectedVersion: doc.version, fieldKey: key, verified: checked }),
    );
  }

  function confirmReview() {
    if (!doc || !canConfirm) return;
    void run("confirm", () => documentApi.confirm(doc.id, doc.version));
  }

  async function exportJson() {
    if (!doc || !canExport || busyRef.current) return;
    busyRef.current = true;
    setBusy("export");
    setNotice(null);
    setInfo(null);
    try {
      const result = await documentApi.export(doc.id, doc.version);
      downloadBlob(result.blob, result.filename);
      if (!aliveRef.current) return;
      setInfo(`Downloaded ${result.filename}`);
      // The server logged the export; fetch the record so the history shows it. A failure
      // here only leaves the history one entry behind, so it is not reported as an export error.
      void documentApi
        .get(doc.id)
        .then((fresh) => {
          if (aliveRef.current && fresh.version === doc.version) setLoad({ status: "ready", doc: fresh });
        })
        .catch(() => undefined);
    } catch (error) {
      if (!aliveRef.current) return;
      if (error instanceof NetworkError) {
        setNotice({ kind: "error", message: "The export did not reach this browser. Try again." });
      } else {
        handleWriteError(error, "export");
      }
    } finally {
      busyRef.current = false;
      if (aliveRef.current) setBusy(null);
    }
  }

  function reload() {
    void run("reload", () => documentApi.get(id));
  }

  function discard() {
    setDrafts({});
    setReason("");
    setServerErrors({});
    setNotice(null);
  }

  return (
    <div className="review">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">All documents</Link>
      </nav>

      <header className="review__head">
        <div>
          <h1>{doc.filename}</h1>
          <p className="review__meta">
            <span className={`status status--${doc.status.toLowerCase()}`}>{STATUS_TEXT[doc.status]}</span>
            <span className="num">Version {doc.version}</span>
            <span className={isPresetFault(doc.extraction_profile) ? "tag tag--demo" : "tag"}>
              {profileLabel(doc.extraction_profile)}
            </span>
          </p>
        </div>
        {doc.confirmation && (
          <p className="review__confirmed">
            {`Confirmed by ${doc.confirmation.confirmed_by} on ${formatUtc(doc.confirmation.confirmed_at)}`}
          </p>
        )}
      </header>

      {notice && (
        <div className={`notice notice--${notice.kind}`} role="alert">
          <p>{notice.message}</p>
          {(notice.kind === "conflict" || notice.kind === "unknown") && (
            <button type="button" className="btn" disabled={busy !== null} onClick={reload}>
              Reload latest
            </button>
          )}
        </div>
      )}

      <div className="review__grid">
        <section className="review__pdf" aria-label="Original PDF">
          {file.status === "error" && (
            <p className="notice notice--error" role="alert">
              {file.message}
            </p>
          )}
          <PdfEvidenceViewer
            file={file.status === "ready" ? file.blob : null}
            fileProblem={file.status === "error" ? file.message : null}
            page={doc.page}
            caption={`${doc.filename}, SHA-256 ${doc.sha256.slice(0, 10)}`}
            selection={selection}
          />
        </section>

        <div className="review__side">
          <ValidationResults rules={doc.rules} describesSavedVersion={dirty} />

          <FieldEditor
            fields={fields}
            drafts={drafts}
            errors={formErrors}
            selectedKey={selectedKey}
            inputsDisabled={inputsLocked}
            checksDisabled={busy !== null || dirty || isConfirmed}
            onSelect={setSelectedKey}
            onChange={(key, text) => {
              setDrafts((current) => ({ ...current, [key]: text }));
              setServerErrors(({ [key]: _removed, ...rest }) => rest);
            }}
            onToggleChecked={toggleChecked}
          />

          <section className="actions" aria-label="Review actions">
            <p className="actions__progress" role="status">
              {checkedCount} of {FIELD_KEYS.length} fields checked
            </p>
            {dirty && <p className="actions__draft">You have unsaved changes.</p>}

            {draft.changes.length > 0 && (
              <div className="reason">
                <label htmlFor="reason">Reason for change</label>
                <textarea
                  id="reason"
                  rows={2}
                  maxLength={REASON_MAX}
                  value={reason}
                  disabled={busy !== null}
                  onChange={(event) => setReason(event.target.value)}
                />
                <p className="note">Recorded in the history with the old and new values.</p>
              </div>
            )}

            <div className="actions__buttons">
              {(!isConfirmed || unlocked) && (
                <button type="button" className="btn btn--primary" disabled={!canSave} onClick={save}>
                  Save changes
                </button>
              )}
              {dirty && (
                <button type="button" className="btn" disabled={busy !== null} onClick={discard}>
                  Discard changes
                </button>
              )}
              {isConfirmed && !unlocked && (
                <button type="button" className="btn" disabled={busy !== null} onClick={() => setUnlocked(true)}>
                  Edit fields
                </button>
              )}
              {isConfirmed && unlocked && !dirty && (
                <button type="button" className="btn" onClick={() => setUnlocked(false)}>
                  Cancel editing
                </button>
              )}
              {doc.status === "REVIEW_REQUIRED" && (
                <button type="button" className="btn btn--primary" disabled={!canConfirm} onClick={confirmReview}>
                  Confirm review
                </button>
              )}
              <button type="button" className="btn" disabled={!canExport} onClick={() => void exportJson()}>
                Export JSON
              </button>
            </div>

            {doc.status === "REVIEW_REQUIRED" && confirmBlockers.length > 0 && (
              <ul className="actions__blockers">
                {confirmBlockers.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            )}
            {info && (
              <p className="note" role="status">
                {info}
              </p>
            )}
            {isConfirmed && unlocked && (
              <p className="note">Saving a change withdraws the confirmation. You will need to check all six fields and confirm again.</p>
            )}
          </section>

          <AuditHistory events={doc.audit_events} />
        </div>
      </div>

      {blocker.state === "blocked" && (
        <div className="dialog-backdrop">
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="leave-title" aria-describedby="leave-text">
            <h2 id="leave-title">Leave this page?</h2>
            <p id="leave-text">You have unsaved changes. They are not stored anywhere and will be lost.</p>
            <div className="dialog__buttons">
              <button type="button" className="btn btn--primary" onClick={() => blocker.reset()}>
                Keep editing
              </button>
              <button type="button" className="btn" onClick={() => blocker.proceed()}>
                Leave without saving
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingOrError({ load, onRetry }: { load: LoadState; onRetry: () => void }) {
  if (load.status === "error") {
    return (
      <div className="page-message" role="alert">
        <h1>{load.notFound ? "Document not found" : "Could not open this document"}</h1>
        <p>{load.message}</p>
        <p>
          <Link to="/">Back to all documents</Link>
          {!load.notFound && (
            <>
              {" "}
              <button type="button" className="btn" onClick={onRetry}>
                Try again
              </button>
            </>
          )}
        </p>
      </div>
    );
  }
  return (
    <p className="page-message" role="status">
      Loading document…
    </p>
  );
}
