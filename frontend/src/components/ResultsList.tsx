import { useEffect, useState } from "react";
import type { SearchResult } from "../types";

type ResultsListProps = {
  items: SearchResult[];
};

function fallbackCopyTextToClipboard(text: string): boolean {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";

  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  let didCopy = false;

  try {
    didCopy = document.execCommand("copy");
  } catch (error) {
    console.error("Fallback copy failed.", error);
  } finally {
    document.body.removeChild(textarea);
  }

  return didCopy;
}

export function ResultsList({ items }: ResultsListProps) {
  const [copiedFileId, setCopiedFileId] = useState<number | null>(null);

  useEffect(() => {
    if (copiedFileId === null) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setCopiedFileId(null);
    }, 1500);

    return () => window.clearTimeout(timeoutId);
  }, [copiedFileId]);

  const handleCopyFullPath = async (fileId: number, fullPath: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(fullPath);
      } else if (!fallbackCopyTextToClipboard(fullPath)) {
        throw new Error("Clipboard API is unavailable.");
      }

      setCopiedFileId(fileId);
    } catch (error) {
      if (fallbackCopyTextToClipboard(fullPath)) {
        setCopiedFileId(fileId);
        return;
      }

      console.error("Failed to copy full path.", error);
    }
  };

  if (items.length === 0) {
    return <div className="empty-panel">一致する結果はありません。</div>;
  }

  return (
    <div className="results-list">
      {items.map((item) => {
        const fullPathUrl = `http://localhost:8001/api/fullpath?path=${encodeURIComponent(item.full_path)}`;

        return (
          <article className="result-card" key={item.file_id}>
            <div className="result-path">
              <code className="result-path-text" title="ドラッグして部分選択できます">
                {item.full_path}
              </code>
              <div className="result-path-actions">
                <button
                  type="button"
                  className="result-copy-button"
                  onClick={() => void handleCopyFullPath(item.file_id, item.full_path)}
                  title="フルパスをコピー"
                >
                  パスをコピー
                </button>
                {copiedFileId === item.file_id ? (
                  <span className="result-path-status">コピーしました</span>
                ) : null}
              </div>
            </div>
            <div className="result-header">
              <h3>
                <a
                  className="result-file-link"
                  href={fullPathUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.file_name}
                </a>
              </h3>
              <div className="result-meta">
                <span>{new Date(item.mtime).toLocaleString()}</span>
              </div>
            </div>
            <p
              className="result-snippet"
              dangerouslySetInnerHTML={{ __html: item.snippet }}
            />
          </article>
        );
      })}
    </div>
  );
}
