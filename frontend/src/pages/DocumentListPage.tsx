import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, NetworkError, documentApi } from "../api/documents";
import type { DocumentSummary, SampleInfo } from "../domain/types";
import { formatUtc, isPresetFault, ruleSummary, STATUS_TEXT } from "../lib/format";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; documents: DocumentSummary[] };

interface UploadProblem {
  message: string;
  existingId?: string;
}

function describeError(error: unknown, whileDoing: string): string {
  if (error instanceof NetworkError) {
    return `The server could not be reached while ${whileDoing}. Check that the backend is running.`;
  }
  if (error instanceof ApiError) return error.message;
  return `Something went wrong while ${whileDoing}.`;
}

export function DocumentListPage() {
  const navigate = useNavigate();
  const [list, setList] = useState<ListState>({ status: "loading" });
  const [samples, setSamples] = useState<SampleInfo[]>([]);
  const [uploading, setUploading] = useState<string | null>(null);
  const [problem, setProblem] = useState<UploadProblem | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setList({ status: "loading" });
    try {
      setList({ status: "ready", documents: await documentApi.list() });
    } catch (error) {
      setList({ status: "error", message: describeError(error, "loading documents") });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch("/samples/manifest.json");
        if (!response.ok) return;
        const manifest = (await response.json()) as { samples: SampleInfo[] };
        if (!cancelled) setSamples(manifest.samples);
      } catch {
        /* samples are optional */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function upload(file: File) {
    if (uploading) return;
    setProblem(null);
    setUploading(file.name);
    try {
      const created = await documentApi.upload(file);
      navigate(`/documents/${created.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.code === "DOCUMENT_DUPLICATE") {
        setProblem({ message: error.message, existingId: String(error.details.existing_document_id ?? "") });
      } else {
        setProblem({ message: `${file.name} was not imported. ${describeError(error, "uploading the file")}` });
      }
    } finally {
      setUploading(null);
    }
  }

  async function importSample(sample: SampleInfo) {
    try {
      const response = await fetch(`/samples/${sample.file}`);
      if (!response.ok) throw new Error("sample missing");
      const blob = await response.blob();
      await upload(new File([blob], sample.file, { type: "application/pdf" }));
    } catch {
      setProblem({ message: "The sample file could not be loaded. Run npm run sync-samples and reload." });
    }
  }

  return (
    <div className="list-page">
      <h1>Capital call notices</h1>

      <div className="intake">
        <section className="intake__upload" aria-labelledby="upload-heading">
          <h2 id="upload-heading">Upload a notice</h2>
          <label
            className="dropzone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              const file = event.dataTransfer.files[0];
              if (file) void upload(file);
            }}
          >
            <span className="dropzone__title">Choose a PDF</span>
            <span className="dropzone__hint">
              or drop it here. Single page, text layer, up to 5 MiB, USD only.
            </span>
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf,.pdf"
              disabled={uploading !== null}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
          </label>
          <p className="intake__status" role="status">
            {uploading ? `Uploading ${uploading}…` : ""}
          </p>
          {problem && (
            <div className="notice notice--error" role="alert">
              <p>{problem.message}</p>
              {problem.existingId && (
                <p>
                  <Link to={`/documents/${problem.existingId}`}>Open the existing record</Link>
                </p>
              )}
            </div>
          )}
        </section>

        {samples.length > 0 && (
          <section className="intake__samples" aria-labelledby="samples-heading">
            <h2 id="samples-heading">Try a sample</h2>
            <ul className="samples">
              {samples.map((sample) => (
                <li key={sample.id} className="sample">
                  <div>
                    <p className="sample__title">{sample.title}</p>
                    <p className="sample__text">{sample.description}</p>
                    {isPresetFault(sample.profile) && (
                      <p className="tag tag--demo">Preset extraction error (demo fault)</p>
                    )}
                  </div>
                  <button type="button" className="btn" disabled={uploading !== null} onClick={() => void importSample(sample)}>
                    Import sample
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <section aria-labelledby="documents-heading" className="documents">
        <h2 id="documents-heading">Documents</h2>
        {list.status === "loading" && <p role="status">Loading documents…</p>}
        {list.status === "error" && (
          <div className="notice notice--error" role="alert">
            <p>{list.message}</p>
            <button type="button" className="btn" onClick={() => void load()}>
              Try again
            </button>
          </div>
        )}
        {list.status === "ready" && list.documents.length === 0 && (
          <p className="empty">No documents yet. Upload a PDF or import a sample to start a review.</p>
        )}
        {list.status === "ready" && list.documents.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Imported</th>
                <th scope="col">Rules</th>
                <th scope="col">Review</th>
                <th scope="col">Version</th>
              </tr>
            </thead>
            <tbody>
              {list.documents.map((doc) => (
                <tr key={doc.id}>
                  <th scope="row">
                    <Link to={`/documents/${doc.id}`}>{doc.filename}</Link>
                  </th>
                  <td>{formatUtc(doc.created_at)}</td>
                  <td>{ruleSummary(doc.rules)}</td>
                  <td>
                    <span className={`status status--${doc.status.toLowerCase()}`}>{STATUS_TEXT[doc.status]}</span>
                  </td>
                  <td className="num">v{doc.version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
