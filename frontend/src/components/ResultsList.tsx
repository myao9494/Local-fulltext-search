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
          <div className="result-meta">
            <span>{item.target_path}</span>
            <span>{item.file_ext}</span>
            <span>{new Date(item.mtime).toLocaleString()}</span>
          </div>
          <h3>{item.file_name}</h3>
          <p
            className="result-snippet"
            dangerouslySetInnerHTML={{ __html: item.snippet }}
          />
          <p className="result-path">{item.full_path}</p>
        </article>
      ))}
    </div>
  );
}
