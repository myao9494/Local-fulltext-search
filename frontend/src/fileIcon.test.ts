import assert from "node:assert/strict";
import test from "node:test";
import { catppuccinIconForResult } from "./fileIcon.ts";

test("ファイル種別に対応する Catppuccin アイコンを選ぶ", () => {
  assert.equal(catppuccinIconForResult({ file_name: "notes.md", result_kind: "file", source_type: "local" }), "markdown.svg");
  assert.equal(catppuccinIconForResult({ file_name: "report.pdf", result_kind: "file", source_type: "local" }), "pdf.svg");
  assert.equal(catppuccinIconForResult({ file_name: "diagram.excalidraw", result_kind: "file", source_type: "local" }), "excalidraw.svg");
  assert.equal(catppuccinIconForResult({ file_name: "records", result_kind: "folder", source_type: "local" }), "folder.svg");
  assert.equal(catppuccinIconForResult({ file_name: "task", result_kind: "file", source_type: "gantt" }), "task.svg");
  assert.equal(catppuccinIconForResult({ file_name: "page", result_kind: "file", source_type: "web" }), "html.svg");
});
