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
 * ハンバーガーメニューからスケジューラー画面へ遷移できる。
 */
test("設定メニューにスケジューラー導線を追加する", () => {
  const source = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");

  assert.match(source, /type PageView = "search" \| "indexed-targets" \| "search-targets" \| "scheduler"/);
  assert.match(source, /スケジューラー/);
  assert.match(source, /handleOpenSchedulerPage/);
  assert.match(source, /pageView === "scheduler"/);
  assert.match(clientSource, /fetchSchedulerSettings/);
  assert.match(clientSource, /startScheduler/);
  assert.match(styleSource, /\.scheduler-panel\s*\{/);
});

/**
 * スケジューラー画面では複数パスと開始日時を指定し、ログを確認できる。
 */
test("スケジューラー画面に複数パス設定と開始ログ表示を追加する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /schedulerPaths/);
  assert.match(source, /schedulerStartAt/);
  assert.match(source, /handleAddSchedulerPath/);
  assert.match(source, /handleStartScheduler/);
  assert.match(source, /type="datetime-local"/);
  assert.match(source, /フォルダを追加/);
  assert.match(source, /開始日時/);
  assert.match(source, /スケジュール開始/);
  assert.match(source, /schedulerState\.logs\.map/);
  assert.match(source, /ログ/);
});

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
 * 除外キーワードは自動保存せず、保存ボタンで明示的に確定できるようにする。
 */
test("設定メニューの除外キーワードに保存ボタンと保存状態表示を置く", () => {
  const source = readFileSync(appPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(source, /savedExcludeKeywords/);
  assert.match(source, /excludeKeywordsDraft/);
  assert.match(source, /handleSaveExcludeKeywords/);
  assert.match(source, /className="secondary-button settings-save-button"/);
  assert.match(source, /未保存の変更があります/);
  assert.match(source, /保存済み/);
  assert.match(source, /fetchAppSettings/);
  assert.match(source, /updateAppSettings/);
  assert.doesNotMatch(source, /localStorage\.setItem\("exclude_keywords"/);
  assert.doesNotMatch(source, /localStorage\.getItem\("exclude_keywords"/);
  assert.doesNotMatch(source, /exclude_keywords: savedExcludeKeywords/);
  assert.match(clientSource, /export async function fetchAppSettings/);
  assert.match(clientSource, /export async function updateAppSettings/);
  assert.match(clientSource, /"\/api\/index\/settings"/);
  assert.match(styleSource, /\.settings-action-row\s*\{/);
  assert.match(styleSource, /\.settings-save-status\.dirty\s*\{/);
});

/**
 * 同義語リストは設定メニューから保存でき、バックエンドのテキストファイル設定を使う。
 */
test("設定メニューに同義語リスト入力と保存導線を表示する", () => {
  const source = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(source, /savedSynonymGroups/);
  assert.match(source, /synonymGroupsDraft/);
  assert.match(source, /handleSaveSynonymGroups/);
  assert.match(source, /同義語リスト/);
  assert.match(source, /スマートフォン,スマホ,モバイル/);
  assert.match(source, /1行を1グループとして、カンマ区切りで入力します。/);
  assert.match(source, /synonym_groups: normalized/);
  assert.match(clientSource, /synonym_groups\?: string/);
});

/**
 * 既定検索フォルダ設定は廃止し、検索対象フォルダ管理へ統合する。
 */
test("設定メニューから既定の検索フォルダ入力を廃止する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.doesNotMatch(source, /savedDefaultSearchPath/);
  assert.doesNotMatch(source, /defaultSearchPathDraft/);
  assert.doesNotMatch(source, /default_search_path/);
  assert.doesNotMatch(source, /検索既定フォルダ/);
});

/**
 * 検索欄のパスが空なら、検索時にエラーを表示して入力を促す。
 */
test("検索時は入力パスが空ならフォルダ入力エラーを表示する", () => {
  const source = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(source, /const normalizedInputPath = fullPath\.trim\(\);/);
  assert.match(source, /const resolvedSearchPath = normalizedInputPath;/);
  assert.match(source, /if \(!isSearchAllEnabled && !resolvedSearchPath\) \{/);
  assert.match(source, /full_path: resolvedSearchPath,/);
  assert.match(source, /search_all_enabled: isSearchAllEnabled,/);
  assert.match(source, /onProgress: \(partialResponse\) => \{/);
  assert.match(source, /setResults\(partialResponse\.items\);/);
  assert.match(source, /response\.background_refresh_scheduled/);
  assert.match(source, /response\.used_existing_index/);
  assert.match(clientSource, /used_existing_index: usedExistingIndex,/);
  assert.match(clientSource, /background_refresh_scheduled: backgroundRefreshScheduled,/);
});

/**
 * 全 DB 検索中に入力欄が空なら、全階層を検索する。
 */
test("全データベース検索かつフォルダ未指定なら既定フォルダへフォールバックしない", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /const resolvedSearchPath = normalizedInputPath;/);
  assert.doesNotMatch(source, /savedDefaultSearchPath/);
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
 * 全データベース検索中でもフォルダ入力や選択は保持し、検索モードは自動で切り替えない。
 */
test("フォルダ入力と選択で全データベース検索を自動解除しない", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.doesNotMatch(source, /setIsSearchAllEnabled\(false\);\s*setFullPath\(payload\.full_path \?\? ""\);/);
  assert.doesNotMatch(source, /function handleFullPathChange\(value: string\): void \{\s*setIsSearchAllEnabled\(false\);/);
  assert.match(source, /setFullPath\(payload\.full_path \?\? ""\);/);
  assert.match(source, /function handleFullPathChange\(value: string\): void \{\s*setFullPath\(value\);/);
  assert.match(source, /onFullPathChange=\{handleFullPathChange\}/);
});

/**
 * クライアント API は、全 DB 検索フラグと保持中のパスを同時にバックエンドへ渡せる。
 */
test("検索 API に全データベースフラグを追加する", () => {
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(clientSource, /search_all_enabled\?: boolean/);
  assert.match(clientSource, /body: JSON\.stringify\(\{/);
});

/**
 * 対象拡張子メニューに XLSM と作図系テキスト拡張子を含め、検索・インデックス対象へ加える。
 */
test("対象拡張子に XLSM と Excalidraw / DIO を含める", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /"\.xlsm"/);
  assert.match(source, /"\.excalidraw"/);
  assert.match(source, /"\.dio"/);
  assert.match(source, /"\.xml"/);
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
  assert.match(appSource, /const visibleResults = filterSearchResultsByExtensions\(sortedResults, searchFilterText\);/);
  assert.match(appSource, /search_filter_extensions/);
  assert.match(appSource, /index_selected_extensions/);
  assert.match(appSource, /const DEFAULT_SEARCH_FILTER_TEXT = ""/);
  assert.match(searchBarSource, /top-filters-status/);
  assert.match(styleSource, /\.top-filters-status\s*\{/);
  assert.match(styleSource, /\.extension-filter-input\s*\{/);
});

/**
 * 検索バーに検索種別フィルタを置き、本文・ファイル名・フォルダ名の対象範囲を切り替えられる。
 */
test("検索バーに検索種別フィルタを追加する", () => {
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");
  const appSource = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(searchBarSource, /検索種別/);
  assert.match(searchBarSource, /<option value="all">すべて<\/option>/);
  assert.match(searchBarSource, /<option value="body">中身のみ<\/option>/);
  assert.match(searchBarSource, /<option value="filename">ファイル名<\/option>/);
  assert.match(searchBarSource, /<option value="folder">フォルダ名<\/option>/);
  assert.match(searchBarSource, /<option value="filename_and_folder">ファイル名\+フォルダ名<\/option>/);
  assert.match(searchBarSource, /onSearchTargetChange/);
  assert.match(appSource, /const \[searchTarget, setSearchTarget\]/);
  assert.match(appSource, /search_target: searchTarget,/);
  assert.match(clientSource, /search_target\?: "all" \| "body" \| "filename" \| "folder" \| "filename_and_folder"/);
});

/**
 * 検索バーにファイル作成日の開始・終了フィルタを置き、検索 API へそのまま渡せる。
 */
test("検索バーに作成日フィルタを追加する", () => {
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");
  const appSource = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");

  assert.match(searchBarSource, /日付種別/);
  assert.match(searchBarSource, /<option value="created">ファイル作成日<\/option>/);
  assert.match(searchBarSource, /<option value="modified">ファイル編集日<\/option>/);
  assert.match(searchBarSource, /aria-label=\{dateField === "created" \? "作成日以降" : "編集日以降"\}/);
  assert.match(searchBarSource, /aria-label=\{dateField === "created" \? "作成日以前" : "編集日以前"\}/);
  assert.match(searchBarSource, /日付指定をキャンセル/);
  assert.match(searchBarSource, /選択した日付種別の「以降」「以前」として扱います。/);
  assert.match(searchBarSource, /className="search-subfilters"/);
  assert.match(searchBarSource, /className="secondary-button date-filter-cancel-button"/);
  assert.match(searchBarSource, /3日以内/);
  assert.match(searchBarSource, /1週間以内/);
  assert.match(searchBarSource, /1ヶ月以内/);
  assert.match(searchBarSource, /date-filter-shortcut-button/);
  assert.match(searchBarSource, /onApplyDateShortcut/);
  assert.match(searchBarSource, /className="small-input date-filter-input"/);
  assert.match(searchBarSource, /className="small-input date-field-select"/);
  assert.match(appSource, /const \[dateField, setDateField\] = useState<"created" \| "modified">\("modified"\)/);
  assert.match(appSource, /const \[createdFrom, setCreatedFrom\] = useState\(""\)/);
  assert.match(appSource, /const \[createdTo, setCreatedTo\] = useState\(""\)/);
  assert.match(appSource, /function handleApplyDateShortcut\(days: number\): void \{/);
  assert.match(appSource, /setCreatedFrom\(resolveRelativeDateInputValue\(days\)\);/);
  assert.match(appSource, /setCreatedTo\(resolveTodayDateInputValue\(\)\);/);
  assert.match(appSource, /function handleClearCreatedDateFilter\(\): void \{/);
  assert.match(appSource, /setCreatedFrom\(""\);/);
  assert.match(appSource, /setCreatedTo\(""\);/);
  assert.match(appSource, /date_field: dateField,/);
  assert.match(appSource, /onApplyDateShortcut=\{handleApplyDateShortcut\}/);
  assert.match(appSource, /onDateFieldChange=\{setDateField\}/);
  assert.match(appSource, /onClearCreatedDateFilter=\{handleClearCreatedDateFilter\}/);
  assert.match(appSource, /created_from: createdFrom \|\| undefined/);
  assert.match(appSource, /created_to: createdTo \|\| undefined/);
  assert.match(appSource, /作成日の終了日は開始日以降で入力してください。/);
  assert.match(clientSource, /date_field\?: "created" \| "modified"/);
  assert.match(clientSource, /created_from\?: string/);
  assert.match(clientSource, /created_to\?: string/);
  assert.match(styleSource, /\.date-filter-panel\s*\{/);
  assert.match(styleSource, /\.date-filter-group\s*\{/);
  assert.match(styleSource, /\.search-subfilters\s*\{/);
  assert.match(styleSource, /\.date-field-select\s*\{/);
  assert.match(styleSource, /\.date-filter-shortcuts\s*\{/);
  assert.match(styleSource, /\.date-filter-shortcut-button\s*\{/);
  assert.match(styleSource, /\.date-filter-input\s*\{/);
  assert.match(styleSource, /\.date-filter-cancel-button\s*\{/);
  assert.match(styleSource, /\.date-filter-hint\s*\{/);
});

/**
 * 検索バーに並び替え条件を置き、検索 API へそのまま渡せる。
 */
test("検索バーに並び替え条件を追加する", () => {
  const searchBarSource = readFileSync(path.join(currentDirectory, "components", "SearchBar.tsx"), "utf-8");
  const appSource = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(searchBarSource, /並び替え/);
  assert.match(searchBarSource, /<option value="modified">編集日順<\/option>/);
  assert.match(searchBarSource, /<option value="created">作成日順<\/option>/);
  assert.match(searchBarSource, /<option value="click_count">アクセス数順<\/option>/);
  assert.match(searchBarSource, /<option value="desc">新しい順 \/ 多い順<\/option>/);
  assert.match(searchBarSource, /<option value="asc">古い順 \/ 少ない順<\/option>/);
  assert.match(appSource, /const \[sortBy, setSortBy\] = useState<"created" \| "modified" \| "click_count">\("modified"\)/);
  assert.match(appSource, /const \[sortOrder, setSortOrder\] = useState<"asc" \| "desc">\("desc"\)/);
  assert.match(appSource, /const sortedResults = sortSearchResults\(results, \{ sortBy, sortOrder \}\);/);
  assert.match(appSource, /<ResultsList items=\{visibleResults\} dateField=\{dateField\} onResultOpen=\{handleResultOpen\} onResultDelete=\{handleResultDelete\} \/>/);
  assert.match(appSource, /sort_by: sortBy,/);
  assert.match(appSource, /sort_order: sortOrder,/);
  assert.match(clientSource, /sort_by\?: "created" \| "modified" \| "click_count"/);
  assert.match(clientSource, /sort_order\?: "asc" \| "desc"/);
});

/**
 * ハンバーガーメニュー内のインデックス対象拡張子はチェックボックスで選べる。
 */
test("設定メニューのインデックス拡張子はチェックボックスで選択する", () => {
  const appSource = readFileSync(appPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(appSource, /isIndexExtensionMenuOpen/);
  assert.match(appSource, /toggleIndexExtension/);
  assert.match(appSource, /setAllIndexExtensions/);
  assert.match(appSource, /clearAllIndexExtensions/);
  assert.match(appSource, /handleSaveIndexExtensions/);
  assert.match(appSource, /handleAddCustomExtension/);
  assert.match(appSource, /handleRemoveCustomExtension/);
  assert.match(appSource, /本文を index 化する追加拡張子/);
  assert.match(appSource, /ファイル名だけを index 化する追加拡張子/);
  assert.match(appSource, /customContentExtensions/);
  assert.match(appSource, /customFilenameExtensions/);
  assert.match(appSource, /savedIndexExtensions/);
  assert.match(appSource, /hasUnsavedIndexExtensions/);
  assert.match(appSource, /selectedIndexExtensions\.includes\(extension\)/);
  assert.match(appSource, /全解除/);
  assert.match(appSource, /保存/);
  assert.match(clientSource, /index_selected_extensions\?: string/);
  assert.match(clientSource, /custom_content_extensions\?: string/);
  assert.match(clientSource, /custom_filename_extensions\?: string/);
  assert.match(appSource, /updateAppSettings\(\{/);
  assert.match(appSource, /index_selected_extensions: normalizedSelectedIndexExtensions\.join\("\\n"\)/);
  assert.match(appSource, /custom_content_extensions: normalizedCustomContentExtensions\.join\("\\n"\)/);
  assert.match(appSource, /custom_filename_extensions: normalizedCustomFilenameExtensions\.join\("\\n"\)/);
  assert.match(appSource, /backend のテキストファイルへ保存され/);
  assert.match(styleSource, /\.extension-menu-actions\s*\{/);
  assert.match(styleSource, /\.extension-add-grid\s*\{/);
  assert.match(styleSource, /\.extension-add-row\s*\{/);
  assert.match(styleSource, /\.extension-custom-row\s*\{/);
  assert.match(styleSource, /\.extension-remove-button\s*\{/);
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
 * トップタブに検索対象フォルダページを追加し、対象ON/OFF管理と追加導線を表示する。
 */
test("トップタブに検索対象フォルダページを表示する", () => {
  const source = readFileSync(appPath, "utf-8");
  const clientSource = readFileSync(clientPath, "utf-8");

  assert.match(source, /onClick=\{\(\) => void handleChangePage\("search-targets"\)\}/);
  assert.match(source, /検索対象フォルダ/);
  assert.match(source, /fetchSearchTargets/);
  assert.match(source, /setSearchTargetEnabled/);
  assert.match(source, /addSearchTarget/);
  assert.match(source, /deleteSearchTargets/);
  assert.match(source, /checked=\{item\.is_enabled\}/);
  assert.match(source, /handleToggleSearchTarget\(item\.full_path, event\.target\.checked\)/);
  assert.match(source, /削除/);
  assert.match(source, /インデックス削除/);
  assert.match(source, /インデックス再取得/);
  assert.match(source, /インデックス取得/);
  assert.match(source, /最終取得:/);
  assert.match(clientSource, /export async function fetchSearchTargets/);
  assert.match(clientSource, /export async function setSearchTargetEnabled/);
  assert.match(clientSource, /export async function addSearchTarget/);
  assert.match(clientSource, /export async function deleteSearchTargets/);
  assert.match(clientSource, /"\/api\/index\/search-targets"/);
});

/**
 * フォルダ入力値が検索対象外なら、検索対象へ追加するボタンを表示する。
 */
test("フォルダ入力値が検索対象外なら追加ボタンを表示する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /const candidateSearchTargetPath = fullPath\.trim\(\);/);
  assert.match(source, /isPathCoveredByTarget\(candidateSearchTargetPath, searchTargets\)/);
  assert.match(source, /検索対象に追加/);
  assert.match(source, /handleAddCurrentPathToSearchTarget/);
});

/**
 * インデックス済みフォルダ画面でも設定ドロワーを開けるよう、同じハンバーガーメニュー導線を置く。
 */
test("インデックス済みフォルダ画面にもハンバーガーメニューを表示する", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(source, /pageView === "indexed-targets" \|\| pageView === "search-targets"[\s\S]*className="menu-button"/);
  assert.match(source, /<aside className=\{`settings-drawer \$\{isMenuOpen \? "open" : ""\}`\} aria-hidden=\{!isMenuOpen\}>/);
});

/**
 * インデックス済みフォルダ画面では、操作ヘッダーを固定したまま一覧だけをスクロールできる。
 */
test("インデックス済みフォルダ画面は操作エリアを固定し一覧だけスクロールする", () => {
  const appSource = readFileSync(appPath, "utf-8");
  const styleSource = readFileSync(appStylesPath, "utf-8");

  assert.match(appSource, /className="indexed-targets-panel-header"/);
  assert.match(appSource, /className="form-help indexed-targets-selection-status"/);
  assert.match(styleSource, /\.indexed-targets-panel\s*\{/);
  assert.match(styleSource, /\.indexed-targets-panel-header\s*\{/);
  assert.match(styleSource, /\.indexed-targets-list\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(styleSource, /\.indexed-targets-list\s*\{[\s\S]*min-height:\s*0/);
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

/**
 * 検索結果の並び替え関数は、TypeScript で解釈できるオブジェクト引数として定義する。
 */
test("検索結果並び替え関数は TypeScript のオブジェクト引数記法を使う", () => {
  const source = readFileSync(appPath, "utf-8");

  assert.match(
    source,
    /function sortSearchResults\(\s*items: readonly SearchResult\[],\s*\{\s*sortBy,\s*sortOrder,\s*\}: \{\s*sortBy: "created" \| "modified" \| "click_count",\s*sortOrder: "asc" \| "desc",\s*\},\s*\): SearchResult\[] \{/,
  );
  assert.doesNotMatch(source, /items: readonly SearchResult\[],\s*\*/);
});
