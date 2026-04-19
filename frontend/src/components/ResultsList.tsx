import { useEffect, useState } from "react";
import type { SearchResult } from "../types";

type ResultsListProps = {
  items: SearchResult[];
  dateField: "created" | "modified";
  onResultOpen: (fileId: number) => void;
  onResultDelete: (fileId: number, fullPath: string) => void;
};

/**
 * 検索結果のフルパスから親フォルダの絶対パスを取り出す。
 */
function getFolderPath(fullPath: string): string {
  const lastSeparatorIndex = Math.max(fullPath.lastIndexOf("/"), fullPath.lastIndexOf("\\"));
  if (lastSeparatorIndex < 0) {
    return fullPath;
  }
  if (lastSeparatorIndex === 0) {
    return fullPath.slice(0, 1);
  }

  const parentPath = fullPath.slice(0, lastSeparatorIndex);
  if (/^[A-Za-z]:$/.test(parentPath)) {
    return `${parentPath}${fullPath[lastSeparatorIndex]}`;
  }

  return parentPath;
}

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

export function ResultsList({ items, dateField, onResultOpen, onResultDelete }: ResultsListProps) {
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
        const folderPath = getFolderPath(item.full_path);
        const fullPathUrl = `http://localhost:8001/api/fullpath?path=${encodeURIComponent(item.full_path)}`;
        const folderUrl = `http://localhost:8001/?path=${encodeURIComponent(folderPath)}`;

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
                <a
                  className="result-folder-link"
                  href={folderUrl}
                  target="_blank"
                  rel="noreferrer"
                  title="親フォルダを開く"
                >
                  フォルダを開く
                </a>
                <button
                  type="button"
                  className="result-delete-button"
                  onClick={() => onResultDelete(item.file_id, item.full_path)}
                  title="ファイルを完全に削除"
                >
                  削除
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
                  onClick={() => onResultOpen(item.file_id)}
                >
                  {item.file_name}
                </a>
              </h3>
              <div className="result-meta">
                <span>{dateField === "created" ? "作成" : "編集"}: {new Date(dateField === "created" ? item.created_at : item.mtime).toLocaleString()}</span>
                <span>アクセス: {item.click_count}</span>
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
