import assert from "node:assert/strict";
import test from "node:test";

import { fetchSearchPage, search } from "./api/client.ts";

/**
 * 検索クライアントは先頭ページ取得直後に途中結果を通知し、画面の初回表示を待たせない。
 */
test("search は先頭ページ取得直後に途中結果を通知する", async () => {
  const progressCalls: Array<{ total: number; items: number }> = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const payload = JSON.parse(String(init?.body)) as { limit: number; offset: number };

    if (payload.offset === 0) {
      return new Response(
        JSON.stringify({
          total: 1002,
          items: Array.from({ length: 50 }, (_, index) => ({
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
          has_more: true,
          next_offset: 50,
          used_existing_index: true,
          background_refresh_scheduled: true,
        }),
      );
    }
    throw new Error("unexpected additional fetch");
  }) as typeof fetch;

  try {
    await search(
      {
        q: "明和",
        full_path: "/tmp/docs",
        index_depth: 5,
        refresh_window_minutes: 60,
      },
      {
        onProgress: (response) => {
          progressCalls.push({ total: response.total, items: response.items.length });
        },
      },
    );

    assert.deepEqual(progressCalls, [{ total: 1002, items: 50 }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("search は 1 ページだけ取得して has_more を返す", async () => {
  const calls: Array<{ limit: number; offset: number }> = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    const payload = JSON.parse(String(init?.body)) as { limit: number; offset: number };
    calls.push({ limit: payload.limit, offset: payload.offset });

    if (payload.offset === 0) {
      return new Response(
        JSON.stringify({
          total: 1002,
          items: Array.from({ length: 50 }, (_, index) => ({
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
          has_more: true,
          next_offset: 50,
          used_existing_index: true,
          background_refresh_scheduled: true,
        }),
      );
    }
    throw new Error("unexpected additional fetch");
  }) as typeof fetch;

  try {
    const response = await search({
      q: "明和",
      full_path: "/tmp/docs",
      index_depth: 5,
      refresh_window_minutes: 60,
    });

    assert.equal(response.total, 1002);
    assert.equal(response.items.length, 50);
    assert.equal(response.has_more, true);
    assert.equal(response.next_offset, 50);
    assert.equal(response.used_existing_index, true);
    assert.equal(response.background_refresh_scheduled, true);
    assert.deepEqual(calls, [{ limit: 50, offset: 0 }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("search は検索種別フィルタをそのまま API へ渡す", async () => {
  let capturedBody: Record<string, unknown> | null = null;
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    capturedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        total: 0,
        items: [],
        has_more: false,
        next_offset: null,
        used_existing_index: false,
        background_refresh_scheduled: false,
      }),
    );
  }) as typeof fetch;

  try {
    await search({
      q: "alpha",
      full_path: "/tmp/docs",
      index_depth: 5,
      refresh_window_minutes: 60,
      search_target: "folder",
    });

    assert.equal(capturedBody?.search_target, "folder");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchSearchPage は 50 件とスニペット有無をそのまま API へ渡す", async () => {
  let capturedBody: Record<string, unknown> | null = null;
  const originalFetch = globalThis.fetch;

  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    capturedBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(
      JSON.stringify({
        total: 1,
        items: [],
        has_more: false,
        next_offset: null,
        used_existing_index: false,
        background_refresh_scheduled: false,
      }),
    );
  }) as typeof fetch;

  try {
    await fetchSearchPage({
      q: "alpha",
      full_path: "/tmp/docs",
      index_depth: 5,
      refresh_window_minutes: 60,
      limit: 50,
      offset: 50,
      include_snippets: false,
    });

    assert.equal(capturedBody?.limit, 50);
    assert.equal(capturedBody?.offset, 50);
    assert.equal(capturedBody?.include_snippets, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
