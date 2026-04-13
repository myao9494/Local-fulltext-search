import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const resultsListPath = path.join(currentDirectory, "components", "ResultsList.tsx");
const appStylesPath = path.join(currentDirectory, "styles", "app.css");

/**
 * 検索結果のフルパスは、部分選択しやすい独立テキストとコピー専用ボタンに分けて表示する。
 */
test("検索結果のフルパスは選択可能なテキスト表示とコピー専用ボタンを分離する", () => {
  const source = readFileSync(resultsListPath, "utf-8");

  assert.match(source, /className="result-path-text"/);
  assert.match(source, /className="result-copy-button"/);
  assert.doesNotMatch(source, /className="result-path result-path-button"/);
});

/**
 * フルパス表示には user-select: text を付けて、ブラウザ上で部分コピーできるようにする。
 */
test("検索結果のフルパス表示にはテキスト選択を許可するスタイルを付ける", () => {
  const source = readFileSync(appStylesPath, "utf-8");

  assert.match(source, /\.result-path-text\s*\{[\s\S]*user-select:\s*text;/);
});
