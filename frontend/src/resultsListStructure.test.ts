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

/**
 * 検索結果にはアクセス数表示とクリック記録フックを持たせる。
 */
test("検索結果にはアクセス数表示とクリック記録フックを含める", () => {
  const source = readFileSync(resultsListPath, "utf-8");

  assert.match(source, /アクセス:/);
  assert.match(source, /onResultOpen/);
  assert.match(source, /item\.click_count/);
});

/**
 * 検索結果には親フォルダを Web アプリケーションで開くリンクを含める。
 */
test("検索結果には親フォルダを開くリンクを含める", () => {
  const source = readFileSync(resultsListPath, "utf-8");

  assert.match(source, /getFolderPath\(item\.full_path\)/);
  assert.match(source, /http:\/\/localhost:8001\/\?path=\$\{encodeURIComponent\(item\.result_kind === "folder" \? item\.full_path : folderPath\)\}/);
  assert.match(source, /result-folder-link/);
  assert.match(source, /フォルダを開く/);
  assert.match(source, /openFileLocation/);
  assert.match(source, /result-open-location-button/);
  assert.match(source, /Finderで開く|Explorerで開く/);
});

/**
 * フォルダ結果では削除やクリック記録を行わず、フォルダ自体を開く導線を使う。
 */
test("フォルダ結果はフォルダ種別として表示を切り替える", () => {
  const source = readFileSync(resultsListPath, "utf-8");

  assert.match(source, /item\.result_kind === "folder"/);
  assert.match(source, /種別: フォルダ/);
  assert.match(source, /if \(item\.result_kind === "file"\) \{/);
});
