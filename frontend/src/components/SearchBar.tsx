type SearchBarProps = {
  query: string;
  fullPath: string;
  indexDepth: string;
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
  onQueryChange,
  onFullPathChange,
  onIndexDepthChange,
  onPickFolder,
  onSubmit,
  onToggleMenu,
}: SearchBarProps) {
  return (
    <div className="search-panel">
      <div className="toolbar-row">
        <button className="menu-button" onClick={onToggleMenu} type="button" aria-label="設定">
          ☰
        </button>
      </div>
      <div className="search-bar">
        <input
          className="search-input"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              onSubmit();
            }
          }}
          placeholder="検索語を入力"
        />
        <button className="primary-button" onClick={onSubmit} type="button">
          Search
        </button>
      </div>
      <div className="filters">
        <div className="path-picker-row">
          <input
            value={fullPath}
            onChange={(event) => onFullPathChange(event.target.value)}
            placeholder="検索対象フォルダのフルパス"
          />
          <button className="secondary-button" onClick={onPickFolder} type="button">
            フォルダ選択
          </button>
        </div>
        <input
          value={indexDepth}
          onChange={(event) => onIndexDepthChange(event.target.value)}
          placeholder="階層数"
          type="number"
          min={0}
        />
      </div>
    </div>
  );
}
