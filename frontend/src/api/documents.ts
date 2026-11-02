import type {
  DocumentDetail,
  DocumentSummary,
  FieldChange,
  FieldKey,
} from "../domain/types";

const BASE = "/api/v1";

/** The server answered with an error. `code` is the stable machine-readable error code. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The request did not complete. A write may or may not have reached the server. */
export class NetworkError extends Error {
  constructor(message = "The server could not be reached.") {
    super(message);
    this.name = "NetworkError";
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new NetworkError();
  }
  if (response.ok) return response;
  throw await toApiError(response);
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } };
    if (body.error?.code && body.error.message) {
      return new ApiError(response.status, body.error.code, body.error.message, body.error.details ?? {});
    }
  } catch {
    /* fall through */
  }
  return new ApiError(
    response.status,
    "UNEXPECTED_RESPONSE",
    `The server returned an unexpected response (HTTP ${response.status}).`,
  );
}

function jsonRequest(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status, "UNEXPECTED_RESPONSE", "The server sent a response that could not be read.");
  }
}

export interface UpdateFieldsInput {
  expectedVersion: number;
  changes: FieldChange[];
  reason: string;
}

export interface VerifyFieldInput {
  expectedVersion: number;
  fieldKey: FieldKey;
  verified: boolean;
}

export interface ExportResult {
  blob: Blob;
  filename: string;
  sha256: string | null;
}

function filenameFrom(header: string | null, fallback: string): string {
  const match = header ? /filename="?([^";]+)"?/i.exec(header) : null;
  const name = match?.[1]?.trim();
  // Never trust a path from a header: keep only a plain file name.
  return name && !/[\\/]/.test(name) ? name : fallback;
}

export const documentApi = {
  async list(): Promise<DocumentSummary[]> {
    return readJson(await send("/documents"));
  },

  async upload(file: File): Promise<DocumentDetail> {
    const form = new FormData();
    form.append("file", file);
    return readJson(await send("/documents", { method: "POST", body: form }));
  },

  async get(id: string): Promise<DocumentDetail> {
    return readJson(await send(`/documents/${encodeURIComponent(id)}`));
  },

  async getFile(id: string): Promise<Blob> {
    return (await send(`/documents/${encodeURIComponent(id)}/file`)).blob();
  },

  async updateFields(id: string, input: UpdateFieldsInput): Promise<DocumentDetail> {
    return readJson(
      await send(
        `/documents/${encodeURIComponent(id)}/fields`,
        jsonRequest("PATCH", {
          expected_version: input.expectedVersion,
          changes: input.changes,
          reason: input.reason,
        }),
      ),
    );
  },

  async verifyField(id: string, input: VerifyFieldInput): Promise<DocumentDetail> {
    return readJson(
      await send(
        `/documents/${encodeURIComponent(id)}/verify`,
        jsonRequest("POST", {
          expected_version: input.expectedVersion,
          field_key: input.fieldKey,
          verified: input.verified,
        }),
      ),
    );
  },

  async confirm(id: string, expectedVersion: number): Promise<DocumentDetail> {
    return readJson(
      await send(
        `/documents/${encodeURIComponent(id)}/confirm`,
        jsonRequest("POST", { expected_version: expectedVersion }),
      ),
    );
  },

  /** The server builds the file from its own stored record, never from page state. */
  async export(id: string, expectedVersion: number): Promise<ExportResult> {
    const response = await send(
      `/documents/${encodeURIComponent(id)}/exports`,
      jsonRequest("POST", { expected_version: expectedVersion, format: "json" }),
    );
    return {
      blob: await response.blob(),
      filename: filenameFrom(
        response.headers.get("content-disposition"),
        `tracereview-${id}-v${expectedVersion}.json`,
      ),
      sha256: response.headers.get("x-export-sha256"),
    };
  },
};
