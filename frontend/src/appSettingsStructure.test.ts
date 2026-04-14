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
 * 検索バー横にインデックス状態表示と中止ボタンを置き、操作状態を見やすくする。
 */
test("検索バー横にインデックス状態表示と中止ボタンを表示する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /インデックス取得中/);
  assert.match(source, /インデックス取得を中止中/);
  assert.match(source, /インデックス待機中/);
  assert.match(source, /取得を中止/);
  assert.match(source, /handleCancelIndexing/);
  assert.match(source, /indexStatusLabel/);
});

/**
 * フォルダ指定欄の左側に全データベース検索ボタンを置き、未指定でも検索できるモードを用意する。
 */
test("検索バーに全データベース検索ボタンを表示する", () => {
  const source = readFileSync(appPath, "utf-8");
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");

  assert.match(searchBarSource, /全データベース/);
  assert.match(searchBarSource, /isSearchAllEnabled/);
  assert.match(searchBarSource, /onSearchAllToggle/);
  assert.match(source, /setIsSearchAllEnabled/);
});

/**
 * 全データベース検索中でもフォルダ入力と選択から通常検索へ戻せるよう、入力欄は無効化しない。
 */
test("全データベース検索中でもフォルダ入力欄と選択ボタンを操作できる", () => {
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");

  assert.doesNotMatch(searchBarSource, /placeholder=\{isSearchAllEnabled \? "全データベース検索中" : "フルパス"\}\s+disabled=\{isSearchAllEnabled\}/);
  assert.doesNotMatch(searchBarSource, /<button[\s\S]*onClick=\{onPickFolder\}[\s\S]*disabled=\{isSearchAllEnabled\}/);
});

/**
 * フォルダの入力や選択を始めたら、全データベース検索は自動で解除してフォルダ検索へ移る。
 */
test("フォルダ入力と選択で全データベース検索を自動解除する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /setIsSearchAllEnabled\(false\);\s*setFullPath\(payload\.full_path \?\? ""\);/);
  assert.match(source, /function handleFullPathChange\(value: string\): void \{\s*setIsSearchAllEnabled\(false\);/);
  assert.match(source, /onFullPathChange=\{handleFullPathChange\}/);
});

/**
 * 対象拡張子メニューに XLSM と作図系テキスト拡張子を含め、検索・インデックス対象へ加える。
 */
test("対象拡張子に XLSM と Excalidraw / DIO を含める", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /"\.xlsm"/);
  assert.match(source, /"\.excalidraw"/);
  assert.match(source, /"\.dio"/);
});

/**
 * 検索バーの拡張子フィルタは手入力で操作し、空欄なら全拡張子対象のままにする。
 */
test("検索バーに独立した検索拡張子の手入力フィルタを追加する", () => {
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");
  const appSource = readFileSync(appPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");

  assert.match(searchBarSource, /extension-filter-input/);
  assert.match(searchBarSource, /検索拡張子フィルタ/);
  assert.match(searchBarSource, /placeholder="md excalidraw"/);
  assert.match(searchBarSource, /onSearchFilterTextChange/);
  assert.match(appSource, /selectedIndexExtensions/);
  assert.match(appSource, /searchFilterText/);
  assert.match(appSource, /index_types: selectedIndexExtensions\.join\(" "\)/);
  assert.match(appSource, /types: searchFilterText/);
  assert.match(appSource, /search_filter_extensions/);
  assert.match(appSource, /index_selected_extensions/);
  assert.match(appSource, /const DEFAULT_SEARCH_FILTER_TEXT = ""/);
  assert.match(searchBarSource, /top-filters-status/);
  assert.match(styleSource, /\.top-filters-status\s*\{/);
  assert.match(styleSource, /\.extension-filter-input\s*\{/);
});

/**
 * ハンバーガーメニュー内のインデックス対象拡張子はチェックボックスで選べる。
 */
test("設定メニューのインデックス拡張子はチェックボックスで選択する", () => {
  const appSource = readFileSync(appPath, "utf-8");

  assert.match(appSource, /isIndexExtensionMenuOpen/);
  assert.match(appSource, /toggleIndexExtension/);
  assert.match(appSource, /setAllIndexExtensions/);
  assert.match(appSource, /selectedIndexExtensions\.includes\(extension\)/);
  assert.match(appSource, /インデックス作成対象です。検索フィルタ側の拡張子選択とは独立しています。/);
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
 * フロントエンド API クライアントはインデックス中止用の POST /api/index/cancel を呼べる。
 */
test("API クライアントにインデックス中止リクエストを用意する", () => {
  const source = readFileSync(clientPath, "utf-8");

  assert.match(source, /export async function cancelIndexing/);
  assert.match(source, /"\/api\/index\/cancel"/);
});

/**
 * インデックス済みフォルダ管理ページを用意し、絞り込み・全選択・削除をまとめて扱えるようにする。
 */
test("インデックス済みフォルダ管理ページの UI を表示する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /インデックス済みフォルダ/);
  assert.match(source, /キーワードで絞り込み/);
  assert.match(source, /すべて選択/);
  assert.match(source, /選択したフォルダのインデックスを削除/);
  assert.match(source, /handleDeleteIndexedTargets/);
});

/**
 * フロントエンド API クライアントはインデックス済みフォルダ一覧取得と削除を呼べる。
 */
test("API クライアントにインデックス済みフォルダ一覧取得と削除リクエストを用意する", () => {
  const source = readFileSync(clientPath, "utf-8");

  assert.match(source, /export async function fetchIndexedTargets/);
  assert.match(source, /export async function deleteIndexedTargets/);
  assert.match(source, /"\/api\/index\/targets"/);
  assert.match(source, /method:\s*"DELETE"/);
});

/**
 * 成功通知はエラー表示と分けて青系の notice banner で描画する。
 */
test("DB 初期化の成功通知用スタイルを定義する", () => {
  const source = readFileSync(appStylesPath, "utf-8");

  assert.match(source, /\.notice-banner\s*\{/);
  assert.match(source, /\.index-status-pill\s*\{/);
  assert.match(source, /\.index-cancel-button\s*\{/);
  assert.match(source, /\.indexed-targets-panel\s*\{/);
  assert.match(source, /\.target-list-item\s*\{/);
});
