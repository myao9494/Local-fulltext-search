import { useEffect, useState } from "react";

import {
  cancelIndexing,
  fetchAppSettings,
  deleteIndexedTargets,
  fetchFailedFiles,
  fetchIndexedTargets,
  fetchIndexStatus,
  pickFolder,
  resetDatabase,
  search,
  updateAppSettings,
} from "./api/client";
import { ResultsList } from "./components/ResultsList";
import { SearchBar } from "./components/SearchBar";
import { parseLaunchParams, shouldAutoSearch } from "./launchParams";
import type { FailedFile, IndexedTarget, IndexStatus, SearchResult } from "./types";

const SUPPORTED_EXTENSIONS = [
  ".md",
  ".json",
  ".txt",
  ".excalidraw",
  ".dio",
  ".pdf",
  ".docx",
  ".xlsx",
  ".xlsm",
  ".pptx",
  ".msg",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".heic",
  ".svg",
  ".bmp",
  ".tif",
  ".tiff",
  ".mp3",
  ".m4a",
  ".aac",
  ".wav",
  ".flac",
  ".aif",
  ".aiff",
  ".alac",
  ".m4p",
] as const;
const DEFAULT_INDEX_EXTENSIONS = [...SUPPORTED_EXTENSIONS];
const LEGACY_ALL_EXTENSIONS_VALUE = SUPPORTED_EXTENSIONS.join(",");
const DEFAULT_EXCLUDE_KEYWORDS = [
  "node_modules",
  ".git",
  "old",
  "旧",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".tox",
  ".venv",
  "venv",
  "env",
  "dist",
  "build",
  "coverage",
  ".next",
  ".turbo",
  ".parcel-cache",
].join("\n");
const DEFAULT_SEARCH_FILTER_TEXT = "";
const DEFAULT_SEARCH_PATH = "";

type PageView = "search" | "indexed-targets";

/**
 * React Strict Mode の開発時二重実行でも初回 URL 検索を重複発火させない。
 */
let lastAutoSearchKey = "";

/**
 * 除外キーワードは空行除去・前後空白除去・重複排除を行い、保存形式を安定化する。
 */
function normalizeExcludeKeywords(value: string): string {
  return [...new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))].join("\n");
}

/**
 * 既定検索フォルダは前後空白だけ落として保存し、空文字なら未設定として扱う。
 */
function normalizeDefaultSearchPath(value: string): string {
  return value.trim();
}

/**
 * 拡張子選択は対応順のまま一意化し、保存値と画面表示の順序を安定させる。
 */
function normalizeIndexExtensions(extensions: readonly string[]): string[] {
  const selected = new Set(extensions);
  return SUPPORTED_EXTENSIONS.filter((extension) => selected.has(extension));
}

function App() {
  const [launchParams] = useState(() => parseLaunchParams(window.location.search));
  const [pageView, setPageView] = useState<PageView>("search");
  const [query, setQuery] = useState(() => launchParams.q);
  const [fullPath, setFullPath] = useState(() => launchParams.fullPath);
  const [lastFolderPath, setLastFolderPath] = useState(() => launchParams.fullPath);
  const [indexDepth, setIndexDepth] = useState(() => launchParams.indexDepth);
  const [isSearchAllEnabled, setIsSearchAllEnabled] = useState(() => launchParams.searchAll);
  const [isRegexEnabled, setIsRegexEnabled] = useState(() => localStorage.getItem("regex_enabled") === "true");
  const [refreshWindowMinutes, setRefreshWindowMinutes] = useState(() => localStorage.getItem("refresh_window_minutes") ?? "60");
  const [savedExcludeKeywords, setSavedExcludeKeywords] = useState(DEFAULT_EXCLUDE_KEYWORDS);
  const [excludeKeywordsDraft, setExcludeKeywordsDraft] = useState(DEFAULT_EXCLUDE_KEYWORDS);
  const [savedDefaultSearchPath, setSavedDefaultSearchPath] = useState(
    () => localStorage.getItem("default_search_path") ?? DEFAULT_SEARCH_PATH,
  );
  const [defaultSearchPathDraft, setDefaultSearchPathDraft] = useState(
    () => localStorage.getItem("default_search_path") ?? DEFAULT_SEARCH_PATH,
  );
  const [selectedIndexExtensions, setSelectedIndexExtensions] = useState<string[]>(() => {
    const stored = localStorage.getItem("index_selected_extensions") ?? localStorage.getItem("selected_extensions");
    if (!stored || stored === LEGACY_ALL_EXTENSIONS_VALUE) {
      return DEFAULT_INDEX_EXTENSIONS;
    }
    const parsed = normalizeIndexExtensions(
      stored.split(/[\s,]+/).filter((item) => SUPPORTED_EXTENSIONS.includes(item as (typeof SUPPORTED_EXTENSIONS)[number])),
    );
    return parsed.length > 0 ? parsed : DEFAULT_INDEX_EXTENSIONS;
  });
  const [savedIndexExtensions, setSavedIndexExtensions] = useState<string[]>(() => {
    const stored = localStorage.getItem("index_selected_extensions") ?? localStorage.getItem("selected_extensions");
    if (!stored || stored === LEGACY_ALL_EXTENSIONS_VALUE) {
      return DEFAULT_INDEX_EXTENSIONS;
    }
    const parsed = normalizeIndexExtensions(
      stored.split(/[\s,]+/).filter((item) => SUPPORTED_EXTENSIONS.includes(item as (typeof SUPPORTED_EXTENSIONS)[number])),
    );
    return parsed.length > 0 ? parsed : DEFAULT_INDEX_EXTENSIONS;
  });
  const [searchFilterText, setSearchFilterText] = useState(() => {
    const stored = localStorage.getItem("search_filter_extensions");
    if (!stored || stored === LEGACY_ALL_EXTENSIONS_VALUE) {
      return DEFAULT_SEARCH_FILTER_TEXT;
    }
    return stored;
  });
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isIndexExtensionMenuOpen, setIsIndexExtensionMenuOpen] = useState(false);
  const [isFailedFilesOpen, setIsFailedFilesOpen] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [failedFiles, setFailedFiles] = useState<FailedFile[]>([]);
  const [indexedTargets, setIndexedTargets] = useState<IndexedTarget[]>([]);
  const [selectedTargetPaths, setSelectedTargetPaths] = useState<string[]>([]);
  const [targetKeyword, setTargetKeyword] = useState("");
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [noticeMessage, setNoticeMessage] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [isResettingDatabase, setIsResettingDatabase] = useState(false);
  const [isCancellingIndex, setIsCancellingIndex] = useState(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState(false);
  const [isDeletingTargets, setIsDeletingTargets] = useState(false);
  const [isSavingExcludeKeywords, setIsSavingExcludeKeywords] = useState(false);
  const isIndexCancelling = Boolean(indexStatus?.is_running && indexStatus?.cancel_requested);
  const isIndexRunning = Boolean(indexStatus?.is_running && !indexStatus?.cancel_requested);
  const indexStatusLabel = isIndexCancelling ? "インデックス取得を中止中" : isIndexRunning ? "インデックス取得中" : "インデックス待機中";
  const indexStatusTone = isIndexCancelling ? "cancelling" : isIndexRunning ? "running" : "idle";

  const keyword = targetKeyword.trim().toLowerCase();
  const filteredTargets = !keyword
    ? indexedTargets
    : indexedTargets.filter((item) => {
        return item.full_path.toLowerCase().includes(keyword);
      });
  const filteredTargetPaths = filteredTargets.map((item) => item.full_path);
  const selectedTargetPathSet = new Set(selectedTargetPaths);
  const selectedFilteredCount = filteredTargetPaths.filter((path) => selectedTargetPathSet.has(path)).length;
  const isAllFilteredSelected = filteredTargetPaths.length > 0 && selectedFilteredCount === filteredTargetPaths.length;
  const normalizedExcludeKeywordsDraft = normalizeExcludeKeywords(excludeKeywordsDraft);
  const hasUnsavedExcludeKeywords = normalizedExcludeKeywordsDraft !== savedExcludeKeywords;
  const normalizedDefaultSearchPath = normalizeDefaultSearchPath(defaultSearchPathDraft);
  const hasUnsavedDefaultSearchPath = normalizedDefaultSearchPath !== savedDefaultSearchPath;
  const hasUnsavedIndexExtensions = selectedIndexExtensions.join(" ") !== savedIndexExtensions.join(" ");

  async function refreshIndexStatus(): Promise<void> {
    setIndexStatus(await fetchIndexStatus());
  }

  /**
   * インデックス済みフォルダ一覧を取得し、消えた選択状態は自動で外す。
   */
  async function refreshIndexedTargets(): Promise<void> {
    setIsLoadingTargets(true);
    try {
      const response = await fetchIndexedTargets();
      setIndexedTargets(response.items);
      setSelectedTargetPaths((current) => current.filter((path) => response.items.some((item) => item.full_path === path)));
    } finally {
      setIsLoadingTargets(false);
    }
  }

  async function loadInitialData(): Promise<void> {
    try {
      const appSettings = await fetchAppSettings();
      const normalizedExcludeKeywords = normalizeExcludeKeywords(appSettings.exclude_keywords);
      setSavedExcludeKeywords(normalizedExcludeKeywords);
      setExcludeKeywordsDraft(normalizedExcludeKeywords);
      await refreshIndexStatus();
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "初期データ取得に失敗しました。");
    }
  }

  useEffect(() => {
    void loadInitialData();
  }, []);

  useEffect(() => {
    localStorage.setItem("regex_enabled", String(isRegexEnabled));
  }, [isRegexEnabled]);

  /**
   * 検索中やインデックス実行中はステータスを定期取得し、中止ボタンの表示状態を追従させる。
   */
  useEffect(() => {
    if (!isSearching && !indexStatus?.is_running) {
      return;
    }

    const timerId = window.setInterval(() => {
      void refreshIndexStatus();
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, [isSearching, indexStatus?.is_running]);

  useEffect(() => {
    if (!shouldAutoSearch(launchParams)) {
      return;
    }

    const autoSearchKey = `${launchParams.q}\n${launchParams.fullPath}\n${launchParams.indexDepth}\n${launchParams.searchAll}`;
    if (lastAutoSearchKey === autoSearchKey) {
      return;
    }

    lastAutoSearchKey = autoSearchKey;
    void handleSearch();
  }, [launchParams]);

  async function handleSearch(): Promise<void> {
    if (isSearching) {
      return;
    }
    const resolvedSearchPath = fullPath.trim() || savedDefaultSearchPath;
    if (!query.trim()) {
      setErrorMessage("検索語を入力してください。");
      return;
    }
    if (!isSearchAllEnabled && !resolvedSearchPath) {
      setErrorMessage("検索対象フォルダのフルパスを入力してください。（※上の検索バーか設定メニューで指定可能です）");
      return;
    }
    if (!indexDepth.trim()) {
      setErrorMessage("階層数を入力してください。");
      return;
    }
    const parsedDepth = Number(indexDepth);
    const parsedWindow = Number(refreshWindowMinutes);
    if (Number.isNaN(parsedDepth) || parsedDepth < 0) {
      setErrorMessage("階層数は 0 以上で入力してください。");
      return;
    }
    if (Number.isNaN(parsedWindow) || parsedWindow < 0) {
      setErrorMessage("更新間隔は 0 以上の分で入力してください。");
      setIsMenuOpen(true);
      return;
    }
    if (selectedIndexExtensions.length === 0) {
      setErrorMessage("インデックス対象の拡張子を 1 つ以上選択してください。");
      setIsMenuOpen(true);
      return;
    }
    try {
      setIsSearching(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await search({
        q: query,
        full_path: isSearchAllEnabled ? "" : resolvedSearchPath,
        index_depth: parsedDepth,
        refresh_window_minutes: parsedWindow,
        regex_enabled: isRegexEnabled,
        index_types: selectedIndexExtensions.join(" "),
        types: searchFilterText,
      });
      setResults(response.items);
      await refreshIndexStatus();
      if (isFailedFilesOpen) {
        const failedResponse = await fetchFailedFiles();
        setFailedFiles(failedResponse.items);
      }
      localStorage.setItem("refresh_window_minutes", String(parsedWindow));
      localStorage.setItem("search_filter_extensions", searchFilterText);
      if (hasUnsavedExcludeKeywords) {
        setNoticeMessage("未保存の除外キーワードは今回の検索に反映していません。保存後に再検索してください。");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "検索に失敗しました。";
      if (message === "Indexing was cancelled.") {
        setNoticeMessage("インデックス作成を中止しました。必要になったら再検索で再開できます。");
        setErrorMessage("");
      } else {
        setErrorMessage(message);
      }
    } finally {
      await refreshIndexStatus().catch(() => undefined);
      setIsSearching(false);
    }
  }

  async function handlePickFolder(): Promise<void> {
    try {
      const payload = await pickFolder();
      setLastFolderPath(payload.full_path ?? "");
      setIsSearchAllEnabled(false);
      setFullPath(payload.full_path ?? "");
      setErrorMessage("");
      setNoticeMessage("");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "フォルダ選択に失敗しました。");
    }
  }

  /**
   * フォルダ指定検索と全 DB 検索を切り替え、最後に使ったフォルダ入力は戻せるよう保持する。
   */
  function handleToggleSearchAll(): void {
    setIsSearchAllEnabled((current) => {
      if (!current && fullPath.trim()) {
        setLastFolderPath(fullPath);
      }
      if (current) {
        setFullPath(lastFolderPath);
      } else {
        setFullPath("");
      }
      setErrorMessage("");
      setNoticeMessage("");
      return !current;
    });
  }

  /**
   * フォルダ入力を始めたら全 DB 検索を外し、通常のフォルダ指定検索へ自然に戻す。
   */
  function handleFullPathChange(value: string): void {
    setIsSearchAllEnabled(false);
    setFullPath(value);
    if (value.trim()) {
      setLastFolderPath(value);
    }
  }

  function toggleIndexExtension(extension: string): void {
    setSelectedIndexExtensions((current) =>
      current.includes(extension) ? current.filter((item) => item !== extension) : [...current, extension],
    );
  }

  function setAllIndexExtensions(): void {
    setSelectedIndexExtensions([...SUPPORTED_EXTENSIONS]);
  }

  function clearAllIndexExtensions(): void {
    setSelectedIndexExtensions([]);
  }

  /**
   * インデックス対象拡張子は localStorage へ明示保存し、次回起動時の初期値に使う。
   */
  function handleSaveIndexExtensions(): void {
    localStorage.setItem("index_selected_extensions", selectedIndexExtensions.join(" "));
    setSavedIndexExtensions([...selectedIndexExtensions]);
    setErrorMessage("");
    setNoticeMessage(
      selectedIndexExtensions.length > 0
        ? "インデックス対象の拡張子を保存しました。次回起動時もこの選択を使います。"
        : "インデックス対象の拡張子をすべて解除した状態で保存しました。",
    );
  }

  /**
   * 除外キーワードは明示的な保存ボタンでだけ確定し、次回検索から必ず同じ値を使う。
   */
  async function handleSaveExcludeKeywords(): Promise<void> {
    const normalized = normalizeExcludeKeywords(excludeKeywordsDraft);
    try {
      setIsSavingExcludeKeywords(true);
      const savedSettings = await updateAppSettings({ exclude_keywords: normalized });
      const savedValue = normalizeExcludeKeywords(savedSettings.exclude_keywords);
      setSavedExcludeKeywords(savedValue);
      setExcludeKeywordsDraft(savedValue);
      setErrorMessage("");
      setNoticeMessage("除外キーワードを保存しました。次回検索から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "除外キーワードの保存に失敗しました。");
    } finally {
      setIsSavingExcludeKeywords(false);
    }
  }

  /**
   * パス未入力検索で使う既定フォルダを localStorage に保存する。
   */
  function handleSaveDefaultSearchPath(): void {
    localStorage.setItem("default_search_path", normalizedDefaultSearchPath);
    setSavedDefaultSearchPath(normalizedDefaultSearchPath);
    setDefaultSearchPathDraft(normalizedDefaultSearchPath);
    setErrorMessage("");
    setNoticeMessage(
      normalizedDefaultSearchPath
        ? "検索既定フォルダを保存しました。パス未入力の検索で利用します。"
        : "検索既定フォルダをクリアしました。",
    );
  }

  async function handleToggleFailedFiles(): Promise<void> {
    const nextOpen = !isFailedFilesOpen;
    setIsFailedFilesOpen(nextOpen);
    if (!nextOpen) {
      return;
    }
    try {
      const response = await fetchFailedFiles();
      setFailedFiles(response.items);
      setErrorMessage("");
      setNoticeMessage("");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "失敗したファイル一覧の取得に失敗しました。");
    }
  }

  /**
   * 管理ページを開くときに最新一覧を読み込み、検索ページへもすぐ戻れるようにする。
   */
  async function handleChangePage(nextView: PageView): Promise<void> {
    setPageView(nextView);
    setErrorMessage("");
    setNoticeMessage("");
    if (nextView === "indexed-targets") {
      try {
        await refreshIndexedTargets();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "インデックス済みフォルダの取得に失敗しました。");
      }
    }
  }

  /**
   * キーワードで絞り込んだ範囲だけを全選択し、既存の選択は維持する。
   */
  function handleToggleAllIndexedTargets(): void {
    if (filteredTargetPaths.length === 0) {
      return;
    }
    setSelectedTargetPaths((current) => {
      const currentSet = new Set(current);
      if (filteredTargetPaths.every((path) => currentSet.has(path))) {
        return current.filter((path) => !filteredTargetPaths.includes(path));
      }
      const merged = new Set([...current, ...filteredTargetPaths]);
      return [...merged];
    });
  }

  function handleToggleIndexedTarget(folderPath: string): void {
    setSelectedTargetPaths((current) =>
      current.includes(folderPath) ? current.filter((item) => item !== folderPath) : [...current, folderPath],
    );
  }

  /**
   * 選択したフォルダのインデックスを削除し、一覧・検索結果・通知を更新する。
   */
  async function handleDeleteIndexedTargets(): Promise<void> {
    if (isDeletingTargets || selectedTargetPaths.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      "選択したフォルダのインデックスを削除します。\n対象フォルダ配下の検索インデックスと失敗履歴が消えます。続行しますか？",
    );
    if (!confirmed) {
      return;
    }

    try {
      setIsDeletingTargets(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await deleteIndexedTargets(selectedTargetPaths);
      setResults([]);
      setSelectedTargetPaths([]);
      await refreshIndexedTargets();
      await refreshIndexStatus().catch(() => undefined);
      setNoticeMessage(`${response.deleted_count}件のインデックス済みフォルダを削除しました。`);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス済みフォルダの削除に失敗しました。");
    } finally {
      setIsDeletingTargets(false);
    }
  }

  /**
   * 実行中のインデックスへ中止要求を送り、完了するまでステータス表示を追従させる。
   */
  async function handleCancelIndexing(): Promise<void> {
    if (isCancellingIndex || !indexStatus?.is_running) {
      return;
    }

    try {
      setIsCancellingIndex(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await cancelIndexing();
      setIndexStatus(response.status);
      setNoticeMessage("インデックス中止をリクエストしました。停止完了まで少し待つ場合があります。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス中止に失敗しました。");
    } finally {
      setIsCancellingIndex(false);
    }
  }

  /**
   * 利用者の確認後にインデックス DB を空へ戻し、画面の一覧とステータスも初期状態へそろえる。
   */
  async function handleResetDatabase(): Promise<void> {
    if (isResettingDatabase) {
      return;
    }

    const confirmed = window.confirm(
      "データベースを初期化します。\n検索インデックス、対象キャッシュ、失敗履歴がすべて消えます。続行しますか？",
    );
    if (!confirmed) {
      return;
    }

    try {
      setIsResettingDatabase(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await resetDatabase();
      setResults([]);
      setFailedFiles([]);
      setIndexedTargets([]);
      setSelectedTargetPaths([]);
      setIsFailedFilesOpen(false);
      setIndexStatus(response.status);
      setNoticeMessage("データベースを初期化しました。必要なら再検索すると再インデックスされます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "データベースの初期化に失敗しました。");
    } finally {
      setIsResettingDatabase(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="top-nav">
        <div className="view-switcher" role="tablist" aria-label="ページ切替">
          <button
            className={`secondary-button page-tab ${pageView === "search" ? "active" : ""}`}
            onClick={() => void handleChangePage("search")}
            type="button"
          >
            検索
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "indexed-targets" ? "active" : ""}`}
            onClick={() => void handleChangePage("indexed-targets")}
            type="button"
          >
            インデックス済みフォルダ
          </button>
        </div>

        {pageView === "search" ? (
          <SearchBar
            query={query}
            fullPath={fullPath}
            indexDepth={indexDepth}
            searchFilterText={searchFilterText}
            isSearching={isSearching}
            isRegexEnabled={isRegexEnabled}
            isSearchAllEnabled={isSearchAllEnabled}
            indexStatusLabel={indexStatusLabel}
            indexStatusTone={indexStatusTone}
            isCancelDisabled={!indexStatus?.is_running || isCancellingIndex}
            isCancellingIndex={isCancellingIndex || isIndexCancelling}
            onQueryChange={setQuery}
            onFullPathChange={handleFullPathChange}
            onIndexDepthChange={setIndexDepth}
            onSearchFilterTextChange={setSearchFilterText}
            onCancelIndexing={() => void handleCancelIndexing()}
            onRegexToggle={() => setIsRegexEnabled((value) => !value)}
            onSearchAllToggle={handleToggleSearchAll}
            onPickFolder={() => void handlePickFolder()}
            onSubmit={() => void handleSearch()}
            onToggleMenu={() => setIsMenuOpen((value) => !value)}
          />
        ) : null}
      </header>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}
      {noticeMessage ? <div className="notice-banner">{noticeMessage}</div> : null}

      <main className="content-grid">
        {pageView === "search" ? (
          <section>
            <div className="section-header">
              <h2>Search Results</h2>
              <span>{results.length}件</span>
            </div>
            <ResultsList items={results} />
          </section>
        ) : (
          <section className="indexed-targets-panel">
            <div className="indexed-targets-panel-header">
              <div className="section-header">
                <div>
                  <h2>インデックス済みフォルダ</h2>
                  <div className="form-help">どのフォルダがインデックスされているか確認し、選択して削除できます。</div>
                </div>
                <div className="section-header-actions">
                  <span>{filteredTargets.length}件</span>
                  <button className="menu-button" onClick={() => setIsMenuOpen((value) => !value)} type="button" aria-label="設定">
                    <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
                      <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
                    </svg>
                  </button>
                </div>
              </div>

              <div className="indexed-targets-toolbar">
                <input
                  className="search-input indexed-targets-search"
                  value={targetKeyword}
                  onChange={(event) => setTargetKeyword(event.target.value)}
                  placeholder="キーワードで絞り込み"
                />
                <button className="secondary-button" onClick={handleToggleAllIndexedTargets} type="button">
                  {isAllFilteredSelected ? "選択解除" : "すべて選択"}
                </button>
                <button className="secondary-button" onClick={() => void refreshIndexedTargets()} type="button" disabled={isLoadingTargets}>
                  {isLoadingTargets ? "再読込中..." : "再読込"}
                </button>
                <button
                  className="secondary-button danger"
                  onClick={() => void handleDeleteIndexedTargets()}
                  type="button"
                  disabled={selectedTargetPaths.length === 0 || isDeletingTargets}
                >
                  {isDeletingTargets ? "削除中..." : "選択したフォルダのインデックスを削除"}
                </button>
              </div>

              <div className="form-help indexed-targets-selection-status">選択中: {selectedTargetPaths.length}件</div>
            </div>

            <div className="indexed-targets-list">
              {filteredTargets.length === 0 ? (
                <div className="empty-panel">
                  <div>{indexedTargets.length === 0 ? "まだインデックス済みフォルダはありません。" : "条件に一致するフォルダはありません。"}</div>
                </div>
              ) : (
                filteredTargets.map((item) => (
                  <label className="target-list-item" key={item.full_path}>
                    <div className="target-list-main">
                      <input
                        checked={selectedTargetPathSet.has(item.full_path)}
                        onChange={() => handleToggleIndexedTarget(item.full_path)}
                        type="checkbox"
                      />
                      <div className="target-list-content">
                        <div className="target-list-path">{item.full_path}</div>
                        <div className="target-list-meta">
                          <span>ファイル数: {item.indexed_file_count}</span>
                          <span>
                            最終取得: {item.last_indexed_at ? new Date(item.last_indexed_at).toLocaleString() : "-"}
                          </span>
                        </div>
                      </div>
                    </div>
                  </label>
                ))
              )}
            </div>
          </section>
        )}

        <aside className={`settings-drawer ${isMenuOpen ? "open" : ""}`} aria-hidden={!isMenuOpen}>
          <div className="settings-panel">
            <div className="settings-header">
              <h2>設定</h2>
              <button className="secondary-button" onClick={() => setIsMenuOpen(false)} type="button">
                閉じる
              </button>
            </div>

            <div className="folder-form">
              <label className="form-help" htmlFor="refresh-window">
                インデックス更新間隔(分)
              </label>
              <input
                id="refresh-window"
                value={refreshWindowMinutes}
                onChange={(event) => setRefreshWindowMinutes(event.target.value)}
                type="number"
                min={0}
              />
              <div className="form-help">
                同じフルパスと階層数の組み合わせで、この分数以内に更新済みなら再走査しません。既定は 60 分です。
              </div>

              <label className="form-help" htmlFor="default-search-path">
                検索既定フォルダ
              </label>
              <input
                id="default-search-path"
                value={defaultSearchPathDraft}
                onChange={(event) => setDefaultSearchPathDraft(event.target.value)}
                placeholder="/Users/name/Documents"
              />
              <div className="settings-action-row">
                <button
                  className="secondary-button settings-save-button"
                  onClick={handleSaveDefaultSearchPath}
                  type="button"
                  disabled={!hasUnsavedDefaultSearchPath}
                >
                  保存
                </button>
                <div className={`settings-save-status ${hasUnsavedDefaultSearchPath ? "dirty" : "saved"}`}>
                  {hasUnsavedDefaultSearchPath ? "未保存の変更があります" : "保存済み"}
                </div>
              </div>
              <div className="form-help">パス未入力で検索したとき、このフォルダを使います。</div>

              <div className="extension-panel">
                <button
                  className="secondary-button"
                  onClick={() => setIsIndexExtensionMenuOpen((value) => !value)}
                  type="button"
                >
                  対象拡張子
                </button>
                {isIndexExtensionMenuOpen ? (
                  <div className="extension-menu">
                    <div className="extension-menu-actions">
                      <button className="secondary-button" onClick={setAllIndexExtensions} type="button">
                        すべて選択
                      </button>
                      <button className="secondary-button" onClick={clearAllIndexExtensions} type="button">
                        全解除
                      </button>
                      <button
                        className="secondary-button settings-save-button"
                        onClick={handleSaveIndexExtensions}
                        type="button"
                        disabled={!hasUnsavedIndexExtensions}
                      >
                        保存
                      </button>
                    </div>
                    {SUPPORTED_EXTENSIONS.map((extension) => (
                      <label className="extension-option" key={extension}>
                        <input
                          checked={selectedIndexExtensions.includes(extension)}
                          onChange={() => toggleIndexExtension(extension)}
                          type="checkbox"
                        />
                        <span>{extension}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
                <div className={`settings-save-status ${hasUnsavedIndexExtensions ? "dirty" : "saved"}`}>
                  {hasUnsavedIndexExtensions ? "未保存の変更があります" : "保存済み"}
                </div>
                <div className="form-help">
                  インデックス作成対象です。検索フィルタ側の拡張子選択とは独立しています。
                </div>
              </div>

              <div className="extension-panel">
                <button className="secondary-button" onClick={() => void handleToggleFailedFiles()} type="button">
                  失敗したファイル
                </button>
                {isFailedFilesOpen ? (
                  <div className="extension-menu">
                    {failedFiles.length === 0 ? (
                      <div className="form-help">現在、記録されている失敗ファイルはありません。</div>
                    ) : (
                      failedFiles.map((item) => (
                        <div className="failed-file-item" key={item.normalized_path}>
                          <div className="failed-file-name">{item.file_name}</div>
                          <div className="failed-file-path">{item.normalized_path}</div>
                          <div className="failed-file-error">{item.error_message}</div>
                          <div className="form-help">{new Date(item.last_failed_at).toLocaleString()}</div>
                        </div>
                      ))
                    )}
                  </div>
                ) : null}
              </div>

              <label className="form-help" htmlFor="exclude-keywords">
                除外キーワード
              </label>
              <textarea
                id="exclude-keywords"
                className="settings-textarea"
                value={excludeKeywordsDraft}
                onChange={(event) => setExcludeKeywordsDraft(event.target.value)}
                placeholder=".git&#10;node_modules&#10;old"
                rows={12}
              />
              <div className="settings-action-row">
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleSaveExcludeKeywords()}
                  type="button"
                  disabled={!hasUnsavedExcludeKeywords || isSavingExcludeKeywords}
                >
                  {isSavingExcludeKeywords ? "保存中..." : "保存"}
                </button>
                <div className={`settings-save-status ${hasUnsavedExcludeKeywords ? "dirty" : "saved"}`}>
                  {hasUnsavedExcludeKeywords ? "未保存の変更があります" : "保存済み"}
                </div>
              </div>
              <div className="form-help">
                1行1キーワードで入力します。`.git` や `node_modules`、`old`、`旧`、Python / React 開発で不要になりやすい
                キャッシュやビルド成果物を既定で除外します。
              </div>

              <div className="extension-panel">
                <button
                  className="secondary-button danger"
                  onClick={() => void handleResetDatabase()}
                  type="button"
                  disabled={isResettingDatabase}
                >
                  {isResettingDatabase ? "初期化中..." : "データベースを初期化"}
                </button>
                <div className="form-help">
                  検索インデックス、対象キャッシュ、失敗履歴を空に戻します。次回検索時に必要な範囲だけ再作成します。
                </div>
              </div>

              <hr className="divider" />

              <div className="status-card">
                <div>最終完了: {indexStatus?.last_finished_at ? new Date(indexStatus.last_finished_at).toLocaleString() : "-"}</div>
                <div>総ファイル数: {indexStatus?.total_files ?? 0}</div>
                <div>エラー件数: {indexStatus?.error_count ?? 0}</div>
                <div>状態: {indexStatusLabel}</div>
              </div>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}

export default App;
