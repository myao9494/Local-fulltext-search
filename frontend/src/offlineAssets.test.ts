import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const sourceStylesPath = path.join(currentDirectory, "styles", "app.css");
const distAssetsPath = path.join(currentDirectory, "..", "dist", "assets");

/**
 * 配布済み画面は完全オフラインでも外部フォント CDN へアクセスしない。
 */
test("フロントエンド CSS は外部フォントを読み込まない", () => {
  const sourceStyles = readFileSync(sourceStylesPath, "utf-8");
  const distStyles = readdirSync(distAssetsPath)
    .filter((name) => name.endsWith(".css"))
    .map((name) => readFileSync(path.join(distAssetsPath, name), "utf-8"))
    .join("\n");

  assert.doesNotMatch(sourceStyles, /fonts\.googleapis|gstatic|https:\/\/fonts/);
  assert.doesNotMatch(distStyles, /fonts\.googleapis|gstatic|https:\/\/fonts/);
});
