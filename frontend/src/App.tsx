import { useEffect, useState } from "react";

import { fetchFailedFiles, fetchIndexStatus, pickFolder, search } from "./api/client";
import { ResultsList } from "./components/ResultsList";
import { SearchBar } from "./components/SearchBar";
import { parseLaunchParams, shouldAutoSearch } from "./launchParams";
import type { FailedFile, IndexStatus, SearchResult } from "./types";

const SUPPORTED_EXTENSIONS = [
  ".md",
  ".json",
  ".txt",
  ".pdf",
  ".docx",
  ".xlsx",
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
] as const;
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

/**
 * React Strict Mode の開発時二重実行でも初回 URL 検索を重複発火させない。
 */
let lastAutoSearchKey = "";

function App() {
  const [launchParams] = useState(() => parseLaunchParams(window.location.search));
  const [query, setQuery] = useState(() => launchParams.q);
  const [fullPath, setFullPath] = useState(() => launchParams.fullPath);
  const [indexDepth, setIndexDepth] = useState(() => launchParams.indexDepth);
  const [isRegexEnabled, setIsRegexEnabled] = useState(() => localStorage.getItem("regex_enabled") === "true");
  const [refreshWindowMinutes, setRefreshWindowMinutes] = useState(() => localStorage.getItem("refresh_window_minutes") ?? "60");
  const [excludeKeywords, setExcludeKeywords] = useState(
    () => localStorage.getItem("exclude_keywords") ?? DEFAULT_EXCLUDE_KEYWORDS,
  );
  const [selectedExtensions, setSelectedExtensions] = useState<string[]>(() => {
    const stored = localStorage.getItem("selected_extensions");
    if (!stored) {
      return [...SUPPORTED_EXTENSIONS];
    }
    const parsed = stored.split(",").filter((item) => SUPPORTED_EXTENSIONS.includes(item as (typeof SUPPORTED_EXTENSIONS)[number]));
    return parsed.length > 0 ? parsed : [...SUPPORTED_EXTENSIONS];
  });
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isExtensionMenuOpen, setIsExtensionMenuOpen] = useState(false);
  const [isFailedFilesOpen, setIsFailedFilesOpen] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [failedFiles, setFailedFiles] = useState<FailedFile[]>([]);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSearching, setIsSearching] = useState(false);

  async function loadInitialData(): Promise<void> {
    try {
      setIndexStatus(await fetchIndexStatus());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "初期データ取得に失敗しました。");
    }
  }

  useEffect(() => {
    void loadInitialData();
  }, []);

  useEffect(() => {
    localStorage.setItem("regex_enabled", String(isRegexEnabled));
  }, [isRegexEnabled]);

  useEffect(() => {
    if (!shouldAutoSearch(launchParams)) {
      return;
    }

    const autoSearchKey = `${launchParams.q}\n${launchParams.fullPath}\n${launchParams.indexDepth}`;
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
    if (!query.trim()) {
      setErrorMessage("検索語を入力してください。");
      return;
    }
    if (!fullPath.trim()) {
      setErrorMessage("検索対象フォルダのフルパスを入力してください。（※上の検索バーで設定可能です）");
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
    if (selectedExtensions.length === 0) {
      setErrorMessage("対象拡張子を 1 つ以上選択してください。");
      setIsMenuOpen(true);
      return;
    }
    try {
      setIsSearching(true);
      setErrorMessage("");
      const response = await search({
        q: query,
        full_path: fullPath,
        index_depth: parsedDepth,
        refresh_window_minutes: parsedWindow,
        regex_enabled: isRegexEnabled,
        types: selectedExtensions.join(","),
        exclude_keywords: excludeKeywords,
      });
      setResults(response.items);
      setIndexStatus(await fetchIndexStatus());
      if (isFailedFilesOpen) {
        const failedResponse = await fetchFailedFiles();
        setFailedFiles(failedResponse.items);
      }
      localStorage.setItem("refresh_window_minutes", String(parsedWindow));
      localStorage.setItem("selected_extensions", selectedExtensions.join(","));
      localStorage.setItem("exclude_keywords", excludeKeywords);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "検索に失敗しました。");
    } finally {
      setIsSearching(false);
    }
  }

  async function handlePickFolder(): Promise<void> {
    try {
      const payload = await pickFolder();
      setFullPath(payload.full_path ?? "");
      setErrorMessage("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "フォルダ選択に失敗しました。");
    }
  }

  function toggleExtension(extension: string): void {
    setSelectedExtensions((current) =>
      current.includes(extension) ? current.filter((item) => item !== extension) : [...current, extension],
    );
  }

  function setAllExtensions(): void {
    setSelectedExtensions([...SUPPORTED_EXTENSIONS]);
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
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "失敗したファイル一覧の取得に失敗しました。");
    }
  }

  return (
    <div className="page-shell">
      <header className="top-nav">
        <SearchBar
          query={query}
          fullPath={fullPath}
          indexDepth={indexDepth}
          isSearching={isSearching}
          isRegexEnabled={isRegexEnabled}
          onQueryChange={setQuery}
          onFullPathChange={setFullPath}
          onIndexDepthChange={setIndexDepth}
          onRegexToggle={() => setIsRegexEnabled((value) => !value)}
          onPickFolder={() => void handlePickFolder()}
          onSubmit={() => void handleSearch()}
          onToggleMenu={() => setIsMenuOpen((value) => !value)}
        />
      </header>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}

      <main className="content-grid">
        <section>
          <div className="section-header">
            <h2>Search Results</h2>
            <span>{results.length}件</span>
          </div>
          <ResultsList items={results} />
        </section>

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

              <div className="extension-panel">
                <button
                  className="secondary-button"
                  onClick={() => setIsExtensionMenuOpen((value) => !value)}
                  type="button"
                >
                  対象拡張子
                </button>
                {isExtensionMenuOpen ? (
                  <div className="extension-menu">
                    <button className="secondary-button" onClick={setAllExtensions} type="button">
                      すべて選択
                    </button>
                    {SUPPORTED_EXTENSIONS.map((extension) => (
                      <label className="extension-option" key={extension}>
                        <input
                          checked={selectedExtensions.includes(extension)}
                          onChange={() => toggleExtension(extension)}
                          type="checkbox"
                        />
                        <span>{extension}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
                <div className="form-help">現在: {selectedExtensions.join(", ") || "未選択"}</div>
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
                value={excludeKeywords}
                onChange={(event) => setExcludeKeywords(event.target.value)}
                placeholder=".git&#10;node_modules&#10;old"
                rows={12}
              />
              <div className="form-help">
                1行1キーワードで入力します。`.git` や `node_modules`、`old`、`旧`、Python / React 開発で不要になりやすい
                キャッシュやビルド成果物を既定で除外します。
              </div>

              <hr className="divider" />

              <div className="status-card">
                <div>最終完了: {indexStatus?.last_finished_at ? new Date(indexStatus.last_finished_at).toLocaleString() : "-"}</div>
                <div>総ファイル数: {indexStatus?.total_files ?? 0}</div>
                <div>エラー件数: {indexStatus?.error_count ?? 0}</div>
                <div>実行中: {indexStatus?.is_running ? "Yes" : "No"}</div>
              </div>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}

export default App;
