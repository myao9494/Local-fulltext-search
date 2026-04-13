import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const appPath = path.join(currentDirectory, "App.tsx");
const clientPath = path.join(currentDirectory, "api", "client.ts");
const appStylesPath = path.join(currentDirectory, "styles", "app.css");

/**
 * ハンバーガーメニュー内に、確認付きで DB 初期化を呼べる危険操作ボタンを置く。
 */
test("設定メニューにデータベース初期化ボタンを表示する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /データベースを初期化/);
  assert.match(source, /window\.confirm/);
  assert.match(source, /className="secondary-button danger"/);
});

/**
 * フロントエンド API クライアントは DB 初期化用の POST /api/index/reset を呼べる。
 */
test("API クライアントにデータベース初期化リクエストを用意する", () => {
  const source = readFileSync(clientPath, "utf-8");

  assert.match(source, /export async function resetDatabase/);
  assert.match(source, /"\/api\/index\/reset"/);
});

/**
 * 成功通知はエラー表示と分けて青系の notice banner で描画する。
 */
test("DB 初期化の成功通知用スタイルを定義する", () => {
  const source = readFileSync(appStylesPath, "utf-8");

  assert.match(source, /\.notice-banner\s*\{/);
});
