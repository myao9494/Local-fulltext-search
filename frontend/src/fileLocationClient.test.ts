import assert from "node:assert/strict";
import test from "node:test";

import { openFileLocation } from "./api/client.ts";

/**
 * ファイル位置オープン API はパスをそのまま backend へ POST する。
 */
test("openFileLocation は対象パスを API へ送る", async () => {
  const originalFetch = globalThis.fetch;
  let capturedInput: RequestInfo | URL | undefined;
  let capturedBody: string | undefined;

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    capturedInput = input;
    capturedBody = String(init?.body ?? "");
    return new Response(JSON.stringify({ status: "success" }));
  }) as typeof fetch;

  try {
    const response = await openFileLocation("/tmp/docs/file.txt");

    assert.equal(capturedInput, "/api/files/open-location");
    assert.deepEqual(JSON.parse(capturedBody ?? "{}"), { path: "/tmp/docs/file.txt" });
    assert.deepEqual(response, { status: "success" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
