import type { SearchResult } from "./types";

/**
 * 拡張子入力を `.md` 形式へ正規化し、空値は捨てる。
 */
export function normalizeExtensionToken(value: string): string {
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) {
    return "";
  }
  return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
}

/**
 * 空白区切りの拡張子入力を UI フィルター用の一意な一覧へ変換する。
 */
export function parseSearchFilterExtensions(value: string): string[] {
  return [...new Set(value.split(/\s+/).map(normalizeExtensionToken).filter(Boolean))];
}

/**
 * 検索結果を file_ext の完全一致で絞り込む。
 * `.md` と `.excalidraw.md` は別拡張子として扱う。
 */
export function filterSearchResultsByExtensions(items: readonly SearchResult[], value: string): SearchResult[] {
  const extensions = parseSearchFilterExtensions(value);
  if (extensions.length === 0) {
    return [...items];
  }

  const extensionSet = new Set(extensions);
  return items.filter((item) => extensionSet.has(item.file_ext.toLowerCase()));
}
