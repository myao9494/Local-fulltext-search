import assert from "node:assert/strict";
import test from "node:test";

import { filterSearchResultsByExtensions, parseSearchFilterExtensions } from "./extensionFilter.ts";

test("拡張子フィルターは空白区切り入力を正規化しつつ重複を除く", () => {
  assert.deepEqual(parseSearchFilterExtensions(" MD   .pdf  md "), [".md", ".pdf"]);
});

test("拡張子フィルターは複合拡張子を完全一致で扱う", () => {
  const items = [
    {
      file_id: 1,
      target_path: "/tmp/docs",
      file_name: "memo.md",
      full_path: "/tmp/docs/memo.md",
      file_ext: ".md",
      created_at: "2026-04-18T00:00:00+09:00",
      mtime: "2026-04-18T00:00:00+09:00",
      click_count: 0,
      snippet: "memo",
    },
    {
      file_id: 2,
      target_path: "/tmp/docs",
      file_name: "board.excalidraw.md",
      full_path: "/tmp/docs/board.excalidraw.md",
      file_ext: ".excalidraw.md",
      created_at: "2026-04-18T00:00:00+09:00",
      mtime: "2026-04-18T00:00:00+09:00",
      click_count: 0,
      snippet: "board",
    },
  ];

  assert.deepEqual(
    filterSearchResultsByExtensions(items, "md").map((item) => item.file_name),
    ["memo.md"],
  );
  assert.deepEqual(
    filterSearchResultsByExtensions(items, "excalidraw.md").map((item) => item.file_name),
    ["board.excalidraw.md"],
  );
});
