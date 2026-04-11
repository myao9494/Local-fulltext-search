import type { SearchResult } from "../types";

type ResultsListProps = {
  items: SearchResult[];
};

export function ResultsList({ items }: ResultsListProps) {
  if (items.length === 0) {
    return <div className="empty-panel">一致する結果はありません。</div>;
  }

  return (
    <div className="results-list">
      {items.map((item) => (
        <article className="result-card" key={item.file_id}>
          <p className="result-path">{item.full_path}</p>
          <div className="result-header">
            <h3>{item.file_name}</h3>
            <div className="result-meta">
              <span>{new Date(item.mtime).toLocaleString()}</span>
            </div>
          </div>
          <p
            className="result-snippet"
            dangerouslySetInnerHTML={{ __html: item.snippet }}
          />
        </article>
      ))}
    </div>
  );
}
