import { useEffect, useRef, useState } from "react";
import { openFileLocation } from "../api/client";
import type { SearchResult } from "../types";

type ResultsListProps = {
  items: SearchResult[];
  dateField: "created" | "modified";
  onResultOpen: (fileId: number) => void;
  onResultDelete: (fileId: number, fullPath: string) => void;
  onResultIgnore: (fileId: number, fullPath: string) => void;
  ignoringResultPath: string | null;
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

/**
 * 検索結果クリック時に使う Web アプリ側のベース URL を返す。
 * 検索結果の遷移先は OS や起動元にかかわらず Web フロントの 8001 番を正とする。
 */
function getWebAppBaseUrl(): string {
  return "http://localhost:8001";
}

type ResultCardProps = {
  item: SearchResult;
  dateField: "created" | "modified";
  openLocationLabel: string;
  copiedFileId: number | null;
  openingLocationFileId: number | null;
  onCopyFullPath: (fileId: number, fullPath: string) => Promise<void>;
  onOpenLocation: (fileId: number, fullPath: string) => Promise<void>;
  onResultOpen: (fileId: number) => void;
  onResultDelete: (fileId: number, fullPath: string) => void;
  onResultIgnore: (fileId: number, fullPath: string) => void;
  ignoringResultPath: string | null;
};

/**
 * スニペットが5行を超える場合のみ、展開・折りたたみ操作を表示する。
 */
function ResultCard({
  item,
  dateField,
  openLocationLabel,
  copiedFileId,
  openingLocationFileId,
  onCopyFullPath,
  onOpenLocation,
  onResultOpen,
  onResultDelete,
  onResultIgnore,
  ignoringResultPath,
}: ResultCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isSnippetExpandable, setIsSnippetExpandable] = useState(false);
  const snippetRef = useRef<HTMLParagraphElement | null>(null);
  const folderPath = getFolderPath(item.full_path);
  const webAppBaseUrl = getWebAppBaseUrl();
  const fullPathUrl = `${webAppBaseUrl}/api/fullpath?path=${encodeURIComponent(item.full_path)}`;
  const folderUrl = `${webAppBaseUrl}/?path=${encodeURIComponent(item.result_kind === "folder" ? item.full_path : folderPath)}`;
  const primaryUrl = item.result_kind === "folder" ? folderUrl : fullPathUrl;

  useEffect(() => {
    const snippetElement = snippetRef.current;
    if (!snippetElement) {
      return undefined;
    }

    const updateSnippetExpandable = () => {
      setIsSnippetExpandable(snippetElement.scrollHeight > snippetElement.clientHeight);
    };

    updateSnippetExpandable();

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateSnippetExpandable);

      return () => window.removeEventListener("resize", updateSnippetExpandable);
    }

    const resizeObserver = new ResizeObserver(() => {
      updateSnippetExpandable();
    });
    resizeObserver.observe(snippetElement);

    return () => resizeObserver.disconnect();
  }, [item.snippet, isExpanded]);

  return (
    <article className="result-card">
      <div className="result-path">
        <code className="result-path-text" title="ドラッグして部分選択できます">
          {item.full_path}
        </code>
        <div className="result-path-actions">
          <button
            type="button"
            className="result-copy-button"
            onClick={() => void onCopyFullPath(item.file_id, item.full_path)}
            title="フルパスをコピー"
          >
            パスをコピー
          </button>
          <button
            type="button"
            className="result-open-location-button"
            onClick={() => void onOpenLocation(item.file_id, item.result_kind === "folder" ? item.full_path : folderPath)}
            title={item.result_kind === "folder" ? openLocationLabel : `${openLocationLabel}（親フォルダ）`}
            disabled={openingLocationFileId === item.file_id}
          >
            {openingLocationFileId === item.file_id ? "開いています..." : openLocationLabel}
          </button>
          <a
            className="result-folder-link"
            href={folderUrl}
            target="_blank"
            rel="noreferrer"
            title={item.result_kind === "folder" ? "フォルダを開く" : "親フォルダを開く"}
          >
            フォルダを開く
          </a>
          {item.result_kind === "file" ? (
            <button
              type="button"
              className="result-ignore-button"
              onClick={() => onResultIgnore(item.file_id, item.full_path)}
              title="このファイルを無視リストへ追加"
              disabled={ignoringResultPath === item.full_path}
            >
              {ignoringResultPath === item.full_path ? "無視中..." : "無視"}
            </button>
          ) : null}
          {item.result_kind === "file" ? (
            <button
              type="button"
              className="result-delete-button"
              onClick={() => onResultDelete(item.file_id, item.full_path)}
              title="ファイルを完全に削除"
            >
              削除
            </button>
          ) : null}
          {copiedFileId === item.file_id ? (
            <span className="result-path-status">コピーしました</span>
          ) : null}
        </div>
      </div>
      <div className="result-header">
        <h3>
          <a
            className="result-file-link"
            href={primaryUrl}
            target="_blank"
            rel="noreferrer"
            onClick={() => {
              if (item.result_kind === "file") {
                onResultOpen(item.file_id);
              }
            }}
          >
            {item.file_name}
          </a>
        </h3>
        <div className="result-meta">
          <span>{dateField === "created" ? "作成" : "編集"}: {new Date(dateField === "created" ? item.created_at : item.mtime).toLocaleString()}</span>
          {item.result_kind === "file" ? <span>アクセス: {item.click_count}</span> : <span>種別: フォルダ</span>}
        </div>
      </div>
      <div className="result-snippet-wrapper">
        <p
          ref={snippetRef}
          className={`result-snippet ${isExpanded ? "" : "result-snippet-clamped"}`.trim()}
          dangerouslySetInnerHTML={{ __html: item.snippet }}
        />
        {isSnippetExpandable ? (
          <button
            type="button"
            className="result-snippet-toggle"
            onClick={() => setIsExpanded((current) => !current)}
            aria-expanded={isExpanded}
          >
            {isExpanded ? "折りたたむ" : "もっと見る"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function ResultsList({ items, dateField, onResultOpen, onResultDelete, onResultIgnore, ignoringResultPath }: ResultsListProps) {
  const [copiedFileId, setCopiedFileId] = useState<number | null>(null);
  const [openingLocationFileId, setOpeningLocationFileId] = useState<number | null>(null);

  const openLocationLabel =
    typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("windows")
      ? "Explorerで開く"
      : "Finderで開く";

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

  const handleOpenLocation = async (fileId: number, fullPath: string) => {
    setOpeningLocationFileId(fileId);
    try {
      await openFileLocation(fullPath);
    } catch (error) {
      console.error("Failed to open file location.", error);
    } finally {
      setOpeningLocationFileId((currentFileId) => (currentFileId === fileId ? null : currentFileId));
    }
  };

  if (items.length === 0) {
    return <div className="empty-panel">一致する結果はありません。</div>;
  }

  return (
    <div className="results-list">
      {items.map((item) => (
        <ResultCard
          key={item.file_id}
          item={item}
          dateField={dateField}
          openLocationLabel={openLocationLabel}
          copiedFileId={copiedFileId}
          openingLocationFileId={openingLocationFileId}
          onCopyFullPath={handleCopyFullPath}
          onOpenLocation={handleOpenLocation}
          onResultOpen={onResultOpen}
          onResultDelete={onResultDelete}
          onResultIgnore={onResultIgnore}
          ignoringResultPath={ignoringResultPath}
        />
      ))}
    </div>
  );
}
