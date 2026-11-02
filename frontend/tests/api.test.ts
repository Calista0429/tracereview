import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, documentApi, NetworkError } from "../src/api/documents";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1)!;
  return { url: url as string, init: (init ?? {}) as RequestInit };
}

describe("documentApi", () => {
  it("sends the version and snake_case body when saving fields", async () => {
    fetchMock.mockResolvedValue(json({ id: "d1", version: 3 }));
    const result = await documentApi.updateFields("d1", {
      expectedVersion: 2,
      changes: [{ key: "total_due", value: "50000.00" }],
      reason: "Checked against the PDF.",
    });
    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/documents/d1/fields");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({
      expected_version: 2,
      changes: [{ key: "total_due", value: "50000.00" }],
      reason: "Checked against the PDF.",
    });
    expect(result.version).toBe(3);
  });

  it("posts verification and confirmation with their expected versions", async () => {
    fetchMock.mockImplementation(async () => json({ id: "d1", version: 4 }));
    await documentApi.verifyField("d1", { expectedVersion: 3, fieldKey: "total_due", verified: true });
    expect(lastCall().url).toBe("/api/v1/documents/d1/verify");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({
      expected_version: 3, field_key: "total_due", verified: true,
    });
    await documentApi.confirm("d1", 4);
    expect(lastCall().url).toBe("/api/v1/documents/d1/confirm");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ expected_version: 4 });
  });

  it("uploads the file as multipart form data", async () => {
    fetchMock.mockResolvedValue(json({ id: "d1" }, 201));
    await documentApi.upload(new File(["%PDF-"], "a.pdf", { type: "application/pdf" }));
    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/documents");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("returns the original as a Blob", async () => {
    fetchMock.mockResolvedValue(new Response(new Uint8Array([37, 80, 68, 70]), { status: 200 }));
    const blob = await documentApi.getFile("d1");
    expect(blob.size).toBe(4);
  });

  it("turns the server's error body into an ApiError", async () => {
    fetchMock.mockResolvedValue(
      json({ error: { code: "VERSION_CONFLICT", message: "This document has changed.", details: { actual_version: 5 } } }, 409),
    );
    const error = await documentApi.get("d1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409, code: "VERSION_CONFLICT", message: "This document has changed.", details: { actual_version: 5 },
    });
  });

  it("keeps duplicate details so the page can open the existing record", async () => {
    fetchMock.mockResolvedValue(
      json({ error: { code: "DOCUMENT_DUPLICATE", message: "This file has already been imported.", details: { existing_document_id: "abc" } } }, 409),
    );
    const error = (await documentApi.upload(new File(["x"], "a.pdf")).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("DOCUMENT_DUPLICATE");
    expect(error.details.existing_document_id).toBe("abc");
  });

  it("treats a non-API error body (for example a proxy 502) as an unexpected response", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 }));
    const error = (await documentApi.list().catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("UNEXPECTED_RESPONSE");
    expect(error.status).toBe(502);
  });

  it("raises NetworkError when the request itself fails, so callers can treat the outcome as unknown", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await documentApi.confirm("d1", 1).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(NetworkError);
  });

  it("requests a JSON export for an exact version and reads the file name and hash from the headers", async () => {
    fetchMock.mockImplementation(async () =>
      new Response('{"schema_version":"1.0"}', {
        status: 200,
        headers: {
          "content-type": "application/json",
          "content-disposition": 'attachment; filename="tracereview-d1-v8.json"',
          "x-export-sha256": "abc123",
        },
      }),
    );
    const result = await documentApi.export("d1", 8);
    const { url, init } = lastCall();
    expect(url).toBe("/api/v1/documents/d1/exports");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ expected_version: 8, format: "json" });
    expect(result.filename).toBe("tracereview-d1-v8.json");
    expect(result.sha256).toBe("abc123");
    expect(await result.blob.text()).toBe('{"schema_version":"1.0"}');
  });

  it("falls back to a safe file name and surfaces export refusals as ApiError", async () => {
    fetchMock.mockImplementationOnce(async () => new Response("{}", { status: 200 }));
    expect((await documentApi.export("d1", 2)).filename).toBe("tracereview-d1-v2.json");

    fetchMock.mockImplementationOnce(async () =>
      json({ error: { code: "DOCUMENT_NOT_CONFIRMED", message: "Only a confirmed review can be exported.", details: {} } }, 409),
    );
    const error = (await documentApi.export("d1", 2).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe("DOCUMENT_NOT_CONFIRMED");
  });
});
