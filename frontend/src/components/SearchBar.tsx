type IndexUiStatus = "idle" | "running" | "cancelling";

type SearchBarProps = {
  query: string;
  fullPath: string;
  indexDepth: string;
  searchFilterText: string;
  searchTarget: "all" | "body" | "filename" | "folder" | "filename_and_folder";
  dateField: "created" | "modified";
  sortBy: "created" | "modified" | "click_count";
  sortOrder: "asc" | "desc";
  createdFrom: string;
  createdTo: string;
  isSearching: boolean;
  isRegexEnabled: boolean;
  isSearchAllEnabled: boolean;
  indexStatusLabel: string;
  indexStatusTone: IndexUiStatus;
  isCancelDisabled: boolean;
  isCancellingIndex: boolean;
  onQueryChange: (value: string) => void;
  onFullPathChange: (value: string) => void;
  onIndexDepthChange: (value: string) => void;
  onSearchFilterTextChange: (value: string) => void;
  onSearchTargetChange: (value: "all" | "body" | "filename" | "folder" | "filename_and_folder") => void;
  onDateFieldChange: (value: "created" | "modified") => void;
  onSortByChange: (value: "created" | "modified" | "click_count") => void;
  onSortOrderChange: (value: "asc" | "desc") => void;
  onCreatedFromChange: (value: string) => void;
  onCreatedToChange: (value: string) => void;
  onClearCreatedDateFilter: () => void;
  onCancelIndexing: () => void;
  onRegexToggle: () => void;
  onSearchAllToggle: () => void;
  onPickFolder: () => void;
  onSubmit: () => void;
  onToggleMenu: () => void;
};

export function SearchBar({
  query,
  fullPath,
  indexDepth,
  searchFilterText,
  searchTarget,
  dateField,
  sortBy,
  sortOrder,
  createdFrom,
  createdTo,
  isSearching,
  isRegexEnabled,
  isSearchAllEnabled,
  indexStatusLabel,
  indexStatusTone,
  isCancelDisabled,
  isCancellingIndex,
  onQueryChange,
  onFullPathChange,
  onIndexDepthChange,
  onSearchFilterTextChange,
  onSearchTargetChange,
  onDateFieldChange,
  onSortByChange,
  onSortOrderChange,
  onCreatedFromChange,
  onCreatedToChange,
  onClearCreatedDateFilter,
  onCancelIndexing,
  onRegexToggle,
  onSearchAllToggle,
  onPickFolder,
  onSubmit,
  onToggleMenu,
}: SearchBarProps) {
  return (
    <div className="search-panel">
      <div className="top-filters">
        <div className="top-filters-main">
          <div className="filter-group path-group">
            <label className="filter-label">フォルダ:</label>
            <div className="path-picker-row top-path-picker">
              <button
                className={`secondary-button small-btn search-all-button ${isSearchAllEnabled ? "active" : ""}`}
                onClick={onSearchAllToggle}
                type="button"
                aria-pressed={isSearchAllEnabled}
              >
                全データベース
              </button>
              <input
                className="small-input path-input"
                value={fullPath}
                onChange={(event) => onFullPathChange(event.target.value)}
                placeholder="フルパス"
              />
              <button className="secondary-button small-btn" onClick={onPickFolder} type="button">
                選択
              </button>
            </div>
          </div>

          <div className="filter-group depth-group">
            <label className="filter-label">階層:</label>
            <div className="depth-field">
              <input
                className="small-input depth-input"
                value={indexDepth}
                onChange={(event) => onIndexDepthChange(event.target.value)}
                placeholder="0"
                type="number"
                min={0}
              />
              <span className="filter-hint">0=直下のみ</span>
            </div>
          </div>
        </div>

        <div className="top-filters-status">
          <div className={`index-status-pill ${indexStatusTone}`} aria-live="polite">
            <span className="index-status-dot" />
            <span>{indexStatusLabel}</span>
          </div>
          <button
            className="secondary-button index-cancel-button"
            disabled={isCancelDisabled}
            onClick={onCancelIndexing}
            type="button"
          >
            {isCancellingIndex ? "中止中..." : "取得を中止"}
          </button>
        </div>
      </div>

      <div className="search-nav">
        <input
          className="search-input"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing && !isSearching) {
              onSubmit();
            }
          }}
          placeholder="検索語を入力してください..."
          autoFocus
        />
        <button
          className={`regex-toggle-button ${isRegexEnabled ? "active" : ""}`}
          onClick={onRegexToggle}
          type="button"
          aria-pressed={isRegexEnabled}
          aria-label="正規表現検索"
          title="正規表現検索"
        >
          .*
        </button>
        <input
          className="small-input extension-filter-input"
          value={searchFilterText}
          onChange={(event) => onSearchFilterTextChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing && !isSearching) {
              onSubmit();
            }
          }}
          placeholder="md excalidraw"
          aria-label="検索拡張子フィルタ"
        />
        <button className="primary-button" disabled={isSearching} onClick={onSubmit} type="button">
          {isSearching ? "Searching..." : "Search"}
        </button>
        <button className="menu-button" onClick={onToggleMenu} type="button" aria-label="設定">
          <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
            <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
          </svg>
        </button>
      </div>

      <div className="search-subfilters">
        <div className="date-filter-panel">
          <div className="date-filter-group">
            <label className="date-filter-label" htmlFor="search-target-select">検索種別</label>
            <select
              id="search-target-select"
              className="small-input date-field-select"
              value={searchTarget}
              onChange={(event) => onSearchTargetChange(event.target.value as "all" | "body" | "filename" | "folder" | "filename_and_folder")}
              aria-label="検索種別"
            >
              <option value="all">すべて</option>
              <option value="body">中身のみ</option>
              <option value="filename">ファイル名</option>
              <option value="folder">フォルダ名</option>
              <option value="filename_and_folder">ファイル名+フォルダ名</option>
            </select>
            <div className="date-filter-hint">本文・ファイル名・親フォルダ名のどこを検索対象にするか切り替えます。</div>
          </div>
          <div className="date-filter-group">
            <label className="date-filter-label" htmlFor="date-field-select">日付種別</label>
            <select
              id="date-field-select"
              className="small-input date-field-select"
              value={dateField}
              onChange={(event) => onDateFieldChange(event.target.value as "created" | "modified")}
              aria-label="日付種別"
            >
              <option value="created">ファイル作成日</option>
              <option value="modified">ファイル編集日</option>
            </select>
            <label className="visually-hidden" htmlFor="created-from-input">
              {dateField === "created" ? "作成日以降" : "編集日以降"}
            </label>
            <input
              id="created-from-input"
              className="small-input date-filter-input"
              value={createdFrom}
              onChange={(event) => onCreatedFromChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing && !isSearching) {
                  onSubmit();
                }
              }}
              type="date"
              aria-label={dateField === "created" ? "作成日以降" : "編集日以降"}
            />
            <span className="date-filter-separator">-</span>
            <label className="visually-hidden" htmlFor="created-to-input">
              {dateField === "created" ? "作成日以前" : "編集日以前"}
            </label>
            <input
              id="created-to-input"
              className="small-input date-filter-input"
              value={createdTo}
              onChange={(event) => onCreatedToChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing && !isSearching) {
                  onSubmit();
                }
              }}
              type="date"
              aria-label={dateField === "created" ? "作成日以前" : "編集日以前"}
            />
            <button className="secondary-button date-filter-cancel-button" onClick={onClearCreatedDateFilter} type="button">
              日付指定をキャンセル
            </button>
            <div className="date-filter-hint">未入力は指定なし。片側だけ指定すると、選択した日付種別の「以降」「以前」として扱います。</div>
          </div>
          <div className="date-filter-group">
            <label className="date-filter-label" htmlFor="sort-by-select">並び替え</label>
            <select
              id="sort-by-select"
              className="small-input date-field-select"
              value={sortBy}
              onChange={(event) => onSortByChange(event.target.value as "created" | "modified" | "click_count")}
              aria-label="並び替え"
            >
              <option value="modified">編集日順</option>
              <option value="created">作成日順</option>
              <option value="click_count">アクセス数順</option>
            </select>
            <select
              className="small-input date-field-select"
              value={sortOrder}
              onChange={(event) => onSortOrderChange(event.target.value as "asc" | "desc")}
              aria-label="並び順"
            >
              <option value="desc">新しい順 / 多い順</option>
              <option value="asc">古い順 / 少ない順</option>
            </select>
            <div className="date-filter-hint">一致品質を保ったまま、同順位内を指定条件で並び替えます。</div>
          </div>
        </div>
      </div>
    </div>
  );
}
