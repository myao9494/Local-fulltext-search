import assert from "node:assert/strict";
import test from "node:test";

import { search } from "./api/client.ts";

test("search は全件取得のため複数ページを順に取得する", async () => {
  const calls: Array<{ limit: number; offset: number }> = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const payload = JSON.parse(String(init?.body)) as { limit: number; offset: number };
    calls.push({ limit: payload.limit, offset: payload.offset });

    if (payload.offset === 0) {
      return new Response(
        JSON.stringify({
          total: 1002,
          items: Array.from({ length: 1000 }, (_, index) => ({
            file_id: index + 1,
            target_path: "/tmp/docs",
            file_name: `item-${index + 1}.xml`,
            full_path: `/tmp/docs/item-${index + 1}.xml`,
            file_ext: ".xml",
            created_at: "2026-04-18T00:00:00+09:00",
            mtime: "2026-04-18T00:00:00+09:00",
            click_count: 0,
            snippet: "xml",
          })),
        }),
      );
    }

    return new Response(
      JSON.stringify({
        total: 1002,
        items: [
          {
            file_id: 1001,
            target_path: "/tmp/docs",
            file_name: "item-1001.xml",
            full_path: "/tmp/docs/item-1001.xml",
            file_ext: ".xml",
            created_at: "2026-04-18T00:00:00+09:00",
            mtime: "2026-04-18T00:00:00+09:00",
            click_count: 0,
            snippet: "xml",
          },
          {
            file_id: 1002,
            target_path: "/tmp/docs",
            file_name: "item-1002.xml",
            full_path: "/tmp/docs/item-1002.xml",
            file_ext: ".xml",
            created_at: "2026-04-18T00:00:00+09:00",
            mtime: "2026-04-18T00:00:00+09:00",
            click_count: 0,
            snippet: "xml",
          },
        ],
      }),
    );
  }) as typeof fetch;

  try {
    const response = await search({
      q: "明和",
      full_path: "/tmp/docs",
      index_depth: 5,
      refresh_window_minutes: 60,
    });

    assert.equal(response.total, 1002);
    assert.equal(response.items.length, 1002);
    assert.deepEqual(calls, [
      { limit: 1000, offset: 0 },
      { limit: 1000, offset: 1000 },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
