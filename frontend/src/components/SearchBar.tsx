type SearchBarProps = {
  query: string;
  fullPath: string;
  indexDepth: string;
  isSearching: boolean;
  onQueryChange: (value: string) => void;
  onFullPathChange: (value: string) => void;
  onIndexDepthChange: (value: string) => void;
  onPickFolder: () => void;
  onSubmit: () => void;
  onToggleMenu: () => void;
};

export function SearchBar({
  query,
  fullPath,
  indexDepth,
  isSearching,
  onQueryChange,
  onFullPathChange,
  onIndexDepthChange,
  onPickFolder,
  onSubmit,
  onToggleMenu,
}: SearchBarProps) {
  return (
    <div className="search-panel">
      <div className="top-filters">
        <div className="filter-group path-group">
          <label className="filter-label">フォルダ:</label>
          <div className="path-picker-row top-path-picker">
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
        <button className="primary-button" disabled={isSearching} onClick={onSubmit} type="button">
          {isSearching ? "Searching..." : "Search"}
        </button>
        <button className="menu-button" onClick={onToggleMenu} type="button" aria-label="設定">
          <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
             <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
          </svg>
        </button>
      </div>
    </div>
  );
}
