/**
 * メインアプリケーションコンポーネント。
 * 各種検索機能、設定ドロワー、インデックス管理、スケジューラーのUI制御を担当する。
 * 階層指定（index_depth）は未入力時に無制限として処理するためオプショナルにする。
 **/
import { useEffect, useRef, useState } from "react";

import {
  cancelIndexing,
  deleteFile,
  deleteSearchTargets,
  fetchAppSettings,
  fetchSearchTargetCoverage,
  deleteIndexedTargets,
  fetchFailedFiles,
  fetchIndexedTargets,
  fetchLauncherStatus,
  fetchSearchTargets,
  fetchIndexStatus,
  fetchSchedulerSettings,
  addSearchTarget,
  pickFolder,
  reindexSearchTargets,
  restartLauncher,
  resetDatabase,
  startLauncher,
  recordSearchClick,
  openFileLocation,
  openGanttTaskInput,
  fetchSearchPage,
  setSearchTargetEnabled,
  startScheduler,
  stopLauncher,
  updateAppSettings,
} from "./api/client";
import { ResultsList } from "./components/ResultsList";
import { SearchBar } from "./components/SearchBar";
import { filterSearchResultsByExtensions, normalizeExtensionToken } from "./extensionFilter";
import { parseLaunchParams, shouldAutoSearch } from "./launchParams";
import type { FailedFile, IndexedTarget, IndexStatus, LauncherStatus, SchedulerSettings, SearchResult, SearchTargetFolder } from "./types";

const BASE_CONTENT_EXTENSIONS = [
  ".md",
  ".json",
  ".txt",
  ".xml",
  ".excalidraw",
  ".dio",
  ".excalidraw.md",
  ".dio.svg",
  ".pdf",
  ".docx",
  ".xlsx",
  ".xlsm",
  ".pptx",
  ".msg",
];
const BASE_FILENAME_ONLY_EXTENSIONS = [
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
  ".mp3",
  ".m4a",
  ".aac",
  ".wav",
  ".flac",
  ".aif",
  ".aiff",
  ".alac",
  ".m4p",
] as const;
const DEFAULT_INDEX_EXTENSIONS = [...BASE_CONTENT_EXTENSIONS, ...BASE_FILENAME_ONLY_EXTENSIONS];
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
const DEFAULT_SYNONYM_GROUPS = "";
const DEFAULT_SEARCH_FILTER_TEXT = "";

type PageView = "search" | "indexed-targets" | "search-targets" | "scheduler" | "launcher" | "indexed-web-targets" | "rule-management";
type SearchSource = "local" | "web";
type SearchTarget = "all" | "body" | "filename" | "folder" | "filename_and_folder";
type SearchExecutionParams = {
  q: string;
  full_path: string;
  search_all_enabled?: boolean;
  skip_refresh?: boolean;
  source_type?: SearchSource;
  index_depth: number;
  refresh_window_minutes: number;
  regex_enabled?: boolean;
  search_target?: SearchTarget;
  index_types?: string;
  date_field?: "created" | "modified";
  sort_by?: "default" | "created" | "modified" | "click_count";
  sort_order?: "asc" | "desc";
  created_from?: string;
  created_to?: string;
  include_gantt_tasks?: boolean;
};
type PendingAutoRefresh = {
  params: SearchExecutionParams;
  searchKey: string;
  baselineLastFinishedAt: string | null;
  hasObservedRunning: boolean;
};
type RuleSnapshot = {
  excludeKeywords: string;
  synonymGroups: string;
};
type RuleKind = "exclude" | "synonym";
type RuleContextMenu = { kind: RuleKind; item: string; x: number; y: number };

/**
 * datetime-local 入出力用に ISO 文字列をローカル日時へ丸める。
 */
function toLocalDateTimeInputValue(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  const offset = date.getTimezoneOffset();
  const localDate = new Date(date.getTime() - offset * 60_000);
  return localDate.toISOString().slice(0, 16);
}

/**
 * 画面入力のローカル日時を API 保存用の ISO 文字列へ変換する。
 */
function toSchedulerStartAtIso(value: string): string {
  return new Date(value).toISOString();
}

/**
 * 日付入力のショートカット用に、今日の日付を `YYYY-MM-DD` 形式で返す。
 */
function resolveTodayDateInputValue(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * 今日から指定日数ぶんさかのぼった日付を `YYYY-MM-DD` 形式で返す。
 */
function resolveRelativeDateInputValue(days: number): string {
  const baseDate = new Date();
  baseDate.setDate(baseDate.getDate() - days);
  return baseDate.toISOString().slice(0, 10);
}

/**
 * React Strict Mode の開発時二重実行でも初回 URL 検索を重複発火させない。
 */
let lastAutoSearchKey = "";

/**
 * 除外キーワードは空行除去・前後空白除去・重複排除を行い、保存形式を安定化する。
 */
function normalizeExcludeKeywords(value: string): string {
  return [...new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))].join("\n");
}

/**
 * 一覧から隠したい確認済みキーワードも改行区切りで正規化し、再起動後も同じ順序で扱えるようにする。
 */
function normalizeHiddenIndexedTargets(value: string): string {
  return [...new Set(value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))].join("\n");
}

/**
 * 同義語リストは 1 行を 1 グループとして扱い、カンマ区切りの語を整形して重複を除く。
 */
function normalizeSynonymGroups(value: string | null | undefined): string {
  return (value ?? "")
    .split(/\r?\n/)
    .map((line) => {
      const normalizedTokens = [...new Set(line.split(/[，,]/).map((item) => item.trim()).filter(Boolean).map((item) => item.toLowerCase()))];
      const originalTokens: string[] = [];
      for (const token of line.split(/[，,]/).map((item) => item.trim()).filter(Boolean)) {
        if (!normalizedTokens.includes(token.toLowerCase())) {
          continue;
        }
        if (originalTokens.some((item) => item.toLowerCase() === token.toLowerCase())) {
          continue;
        }
        originalTokens.push(token);
      }
      return originalTokens.join(",");
    })
    .filter(Boolean)
    .join("\n");
}

/**
 * gantt parent ID は 0 以上の整数だけを保存対象にする。
 */
function normalizeGanttParent(value: string | number | null | undefined): number {
  const rawValue = String(value ?? "").trim();
  if (!/^\d+$/.test(rawValue)) {
    return 0;
  }
  const parsed = Number.parseInt(rawValue, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

/**
 * 拡張子一覧は前後空白除去・ドット補完・重複排除を行う。
 */
function normalizeCustomExtensions(extensions: readonly string[]): string[] {
  const normalized = extensions.map(normalizeExtensionToken).filter(Boolean);
  return [...new Set(normalized)];
}

/**
 * 標準拡張子と利用者追加拡張子を結合し、表示順を安定させる。
 */
function buildAvailableExtensions(customContentExtensions: readonly string[], customFilenameExtensions: readonly string[]): string[] {
  return [
    ...BASE_CONTENT_EXTENSIONS,
    ...BASE_FILENAME_ONLY_EXTENSIONS,
    ...normalizeCustomExtensions(customContentExtensions),
    ...normalizeCustomExtensions(customFilenameExtensions),
  ].filter((extension, index, array) => array.indexOf(extension) === index);
}

/**
 * 拡張子選択は表示順のまま一意化し、保存値と画面表示の順序を安定させる。
 */
function normalizeIndexExtensions(extensions: readonly string[], availableExtensions: readonly string[]): string[] {
  const selected = new Set(extensions.map(normalizeExtensionToken).filter(Boolean));
  return availableExtensions.filter((extension) => selected.has(extension));
}

/**
 * テキストファイルとの往復用に、改行区切りの拡張子一覧を配列へ変換する。
 */
function parseExtensionText(value: string): string[] {
  return normalizeCustomExtensions(value.split(/[\s,]+/));
}

/**
 * 検索結果は再検索せずに、現在の UI 指定だけで安定した並び替えを行う。
 */
function sortSearchResults(
  items: readonly SearchResult[],
  {
    sortBy,
    sortOrder,
  }: {
    sortBy: "default" | "created" | "modified" | "click_count",
    sortOrder: "asc" | "desc",
  },
): SearchResult[] {
  if (sortBy === "default") {
    return [...items].sort((left, right) => {
      const filenameDifference = (right.filename_match_level ?? 0) - (left.filename_match_level ?? 0);
      if (filenameDifference !== 0) return filenameDifference;
      const topDifference = Number(Boolean(right.has_obsidian_top_tag)) - Number(Boolean(left.has_obsidian_top_tag));
      if (topDifference !== 0) return topDifference;
      const queryClickDifference = (right.query_click_score ?? 0) - (left.query_click_score ?? 0);
      if (queryClickDifference !== 0) return queryClickDifference;
      const relevanceDifference = (right.relevance_bucket ?? 0) - (left.relevance_bucket ?? 0);
      if (relevanceDifference !== 0) return relevanceDifference;
      const utilityDifference = (right.utility_score ?? 0) - (left.utility_score ?? 0);
      if (utilityDifference !== 0) return utilityDifference;
      const modifiedDifference = new Date(right.mtime).getTime() - new Date(left.mtime).getTime();
      return modifiedDifference !== 0 ? modifiedDifference : right.file_id - left.file_id;
    });
  }
  const direction = sortOrder === "asc" ? 1 : -1;

  return [...items].sort((left, right) => {
    const leftValue = getSortableValue(left, sortBy);
    const rightValue = getSortableValue(right, sortBy);
    if (leftValue < rightValue) {
      return -1 * direction;
    }
    if (leftValue > rightValue) {
      return 1 * direction;
    }
    return left.file_id - right.file_id;
  });
}

/**
 * 並び替えキーごとの比較値を数値へ正規化する。
 */
function getSortableValue(item: SearchResult, sortBy: "created" | "modified" | "click_count"): number {
  if (sortBy === "click_count") {
    return item.click_count;
  }
  if (sortBy === "created") {
    return new Date(item.created_at).getTime();
  }
  return new Date(item.mtime).getTime();
}

/**
 * 検索対象フォルダの親子判定用に、区切りを統一して末尾スラッシュを除去する。
 */
function normalizeComparablePath(path: string): string {
  const trimmed = path.trim().replace(/\\/g, "/");
  if (trimmed.length <= 1) {
    return trimmed;
  }
  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed;
}

/**
 * 検索対象フォルダ一覧に、指定パス（または親）が含まれるか判定する。
 * 有効/無効に関わらず、親フォルダが登録済みなら子の自動追加候補は表示しない。
 */
function isPathCoveredByTarget(path: string, searchTargets: readonly SearchTargetFolder[]): boolean {
  const normalizedPath = normalizeComparablePath(path);
  if (!normalizedPath) {
    return false;
  }
  const registeredPaths = searchTargets
    .map((item) => normalizeComparablePath(item.full_path))
    .filter(Boolean);
  return registeredPaths.some((rootPath) => normalizedPath === rootPath || normalizedPath.startsWith(`${rootPath}/`));
}

function App() {
  const [launchParams] = useState(() => parseLaunchParams(window.location.search));
  const [pageView, setPageView] = useState<PageView>("search");
  const [query, setQuery] = useState(() => launchParams.q);
  const [fullPath, setFullPath] = useState(() => launchParams.fullPath);
  const [indexDepth, setIndexDepth] = useState(() => launchParams.indexDepth);
  const [isSearchAllEnabled, setIsSearchAllEnabled] = useState(() => launchParams.searchAll);
  const [searchSource, setSearchSource] = useState<SearchSource>("local");
  const [includeGanttTasks, setIncludeGanttTasks] = useState(false);
  const [isRegexEnabled, setIsRegexEnabled] = useState(() => localStorage.getItem("regex_enabled") === "true");
  const [uiZoom, setUiZoom] = useState(() => {
    const saved = Number(localStorage.getItem("ui_zoom") ?? "100");
    return Number.isFinite(saved) ? Math.min(125, Math.max(75, saved)) : 100;
  });
  const [refreshWindowMinutes, setRefreshWindowMinutes] = useState(() => localStorage.getItem("refresh_window_minutes") ?? "60");
  const [savedExcludeKeywords, setSavedExcludeKeywords] = useState(DEFAULT_EXCLUDE_KEYWORDS);
  const [excludeKeywordsDraft, setExcludeKeywordsDraft] = useState(DEFAULT_EXCLUDE_KEYWORDS);
  const [savedWebExcludeKeywords, setSavedWebExcludeKeywords] = useState("");
  const [webExcludeKeywordsDraft, setWebExcludeKeywordsDraft] = useState("");
  const [savedHiddenIndexedTargets, setSavedHiddenIndexedTargets] = useState("");
  const [savedSynonymGroups, setSavedSynonymGroups] = useState(DEFAULT_SYNONYM_GROUPS);
  const [synonymGroupsDraft, setSynonymGroupsDraft] = useState(DEFAULT_SYNONYM_GROUPS);
  const [excludeRuleFilterText, setExcludeRuleFilterText] = useState("");
  const [synonymRuleFilterText, setSynonymRuleFilterText] = useState("");
  const [newExcludeKeyword, setNewExcludeKeyword] = useState("");
  const [newSynonymGroup, setNewSynonymGroup] = useState("");
  const [editingExcludeKeyword, setEditingExcludeKeyword] = useState<string | null>(null);
  const [editingExcludeKeywordValue, setEditingExcludeKeywordValue] = useState("");
  const [editingSynonymGroup, setEditingSynonymGroup] = useState<string | null>(null);
  const [editingSynonymGroupValue, setEditingSynonymGroupValue] = useState("");
  const [ruleContextMenu, setRuleContextMenu] = useState<RuleContextMenu | null>(null);
  const [draggedRule, setDraggedRule] = useState<{ kind: RuleKind; item: string } | null>(null);
  const [isRuleAddModalOpen, setIsRuleAddModalOpen] = useState(false);
  const [ruleAddKind, setRuleAddKind] = useState<RuleKind>("exclude");
  const [activeRuleKind, setActiveRuleKind] = useState<RuleKind>("exclude");
  const [selectedRuleItem, setSelectedRuleItem] = useState<{ kind: RuleKind; item: string } | null>(null);
  const [savedObsidianSidebarExplorerDataPath, setSavedObsidianSidebarExplorerDataPath] = useState("");
  const [obsidianSidebarExplorerDataPathDraft, setObsidianSidebarExplorerDataPathDraft] = useState("");
  const [savedGanttParent, setSavedGanttParent] = useState(0);
  const [ganttParentDraft, setGanttParentDraft] = useState("0");
  const [savedCustomContentExtensions, setSavedCustomContentExtensions] = useState<string[]>([]);
  const [customContentExtensions, setCustomContentExtensions] = useState<string[]>([]);
  const [savedCustomFilenameExtensions, setSavedCustomFilenameExtensions] = useState<string[]>([]);
  const [customFilenameExtensions, setCustomFilenameExtensions] = useState<string[]>([]);
  const [newContentExtension, setNewContentExtension] = useState("");
  const [newFilenameExtension, setNewFilenameExtension] = useState("");
  const [selectedIndexExtensions, setSelectedIndexExtensions] = useState<string[]>(DEFAULT_INDEX_EXTENSIONS);
  const [savedIndexExtensions, setSavedIndexExtensions] = useState<string[]>(DEFAULT_INDEX_EXTENSIONS);
  const [searchFilterText, setSearchFilterText] = useState(() => {
    const stored = localStorage.getItem("search_filter_extensions");
    if (!stored) {
      return DEFAULT_SEARCH_FILTER_TEXT;
    }
    return stored;
  });
  const [searchTarget, setSearchTarget] = useState<SearchTarget>("all");
  const [dateField, setDateField] = useState<"created" | "modified">("modified");
  const [sortBy, setSortBy] = useState<"default" | "created" | "modified" | "click_count">("default");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isIndexExtensionMenuOpen, setIsIndexExtensionMenuOpen] = useState(false);
  const [isFailedFilesOpen, setIsFailedFilesOpen] = useState(false);
  const [schedulerState, setSchedulerState] = useState<SchedulerSettings | null>(null);
  const [launcherState, setLauncherState] = useState<LauncherStatus | null>(null);
  const [schedulerPaths, setSchedulerPaths] = useState<string[]>([]);
  const [schedulerPathDraft, setSchedulerPathDraft] = useState("");
  const [schedulerStartAt, setSchedulerStartAt] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchNextOffset, setSearchNextOffset] = useState<number | null>(null);
  const [hasMoreResults, setHasMoreResults] = useState(false);
  const [currentSearchParams, setCurrentSearchParams] = useState<SearchExecutionParams | null>(null);
  const [failedFiles, setFailedFiles] = useState<FailedFile[]>([]);
  const [indexedTargets, setIndexedTargets] = useState<IndexedTarget[]>([]);
  const [searchTargets, setSearchTargets] = useState<SearchTargetFolder[]>([]);
  const [isCurrentPathCovered, setIsCurrentPathCovered] = useState(false);
  const [selectedTargetPaths, setSelectedTargetPaths] = useState<string[]>([]);
  const [filterKeyword, setFilterKeyword] = useState("");
  const [hideKeyword, setHideKeyword] = useState("");
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [noticeMessage, setNoticeMessage] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [isLoadingMoreResults, setIsLoadingMoreResults] = useState(false);
  const [pendingAutoRefresh, setPendingAutoRefresh] = useState<PendingAutoRefresh | null>(null);
  const [isResettingDatabase, setIsResettingDatabase] = useState(false);
  const [isCancellingIndex, setIsCancellingIndex] = useState(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState(false);
  const [isDeletingTargets, setIsDeletingTargets] = useState(false);
  const [isUpdatingSearchTargets, setIsUpdatingSearchTargets] = useState(false);
  const [isReindexingSearchTargets, setIsReindexingSearchTargets] = useState(false);
  const [isAddingLaunchPath, setIsAddingLaunchPath] = useState(false);
  const [searchTargetActionPath, setSearchTargetActionPath] = useState<string | null>(null);
  const [openingIndexedTargetPath, setOpeningIndexedTargetPath] = useState<string | null>(null);
  const [isIgnoringResultPath, setIsIgnoringResultPath] = useState<string | null>(null);
  const [isSavingExcludeKeywords, setIsSavingExcludeKeywords] = useState(false);
  const [isSavingWebExcludeKeywords, setIsSavingWebExcludeKeywords] = useState(false);
  const [isSavingSynonymGroups, setIsSavingSynonymGroups] = useState(false);
  const [isSavingObsidianSidebarExplorerDataPath, setIsSavingObsidianSidebarExplorerDataPath] = useState(false);
  const [isSavingGanttParent, setIsSavingGanttParent] = useState(false);
  const [isSavingIndexExtensions, setIsSavingIndexExtensions] = useState(false);
  const [isStartingScheduler, setIsStartingScheduler] = useState(false);
  const [isLauncherActionRunning, setIsLauncherActionRunning] = useState(false);
  const [hasLoadedAppSettings, setHasLoadedAppSettings] = useState(false);
  const ruleHistoryRef = useRef<RuleSnapshot[]>([]);
  const ruleHistoryIndexRef = useRef(-1);
  const isIndexCancelling = Boolean(indexStatus?.is_running && indexStatus?.cancel_requested);
  const isIndexRunning = Boolean(indexStatus?.is_running && !indexStatus?.cancel_requested);
  const indexStatusLabel = isIndexCancelling ? "インデックス取得を中止中" : isIndexRunning ? "インデックス取得中" : "インデックス待機中";
  const indexStatusTone = isIndexCancelling ? "cancelling" : isIndexRunning ? "running" : "idle";
  const availableIndexExtensions = buildAvailableExtensions(customContentExtensions, customFilenameExtensions);
  const openLocationLabel =
    typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("windows")
      ? "Explorerで開く"
      : "Finderで開く";
  const isIndexedWebTargetsPage = pageView === "indexed-web-targets";

  const normalizedFilterKeyword = filterKeyword.trim();
  const loweredFilterKeyword = normalizedFilterKeyword.toLowerCase();
  const hiddenKeywordList = normalizeHiddenIndexedTargets(hideKeyword)
    .split(/\r?\n/)
    .map((item) => item.toLowerCase())
    .filter(Boolean);
  const filteredTargets = indexedTargets
    .filter((item) => {
      const normalizedPath = item.full_path.toLowerCase();
      if (loweredFilterKeyword && !normalizedPath.includes(loweredFilterKeyword)) {
        return false;
      }
      if (hiddenKeywordList.some((keyword) => normalizedPath.includes(keyword))) {
        return false;
      }
      return true;
    })
    .sort((left, right) => right.indexed_file_count - left.indexed_file_count || left.full_path.localeCompare(right.full_path));
  const filteredTargetPaths = filteredTargets.map((item) => item.full_path);
  const filteredSearchTargets = !loweredFilterKeyword
    ? searchTargets
    : searchTargets.filter((item) => item.full_path.toLowerCase().includes(loweredFilterKeyword));
  const filteredEnabledSearchTargets = filteredSearchTargets.filter((item) => item.is_enabled);
  const filteredSearchTargetPaths = filteredSearchTargets.map((item) => item.full_path);
  const selectedTargetPathSet = new Set(selectedTargetPaths);
  const selectedFilteredCount = filteredTargetPaths.filter((path) => selectedTargetPathSet.has(path)).length;
  const isAllFilteredSelected = filteredTargetPaths.length > 0 && selectedFilteredCount === filteredTargetPaths.length;
  const isAllFilteredSearchTargetsSelected =
    filteredSearchTargets.length > 0 && filteredSearchTargets.every((item) => item.is_enabled);
  const normalizedExcludeKeywordsDraft = normalizeExcludeKeywords(excludeKeywordsDraft);
  const hasUnsavedExcludeKeywords = normalizedExcludeKeywordsDraft !== savedExcludeKeywords;
  const normalizedWebExcludeKeywordsDraft = normalizeExcludeKeywords(webExcludeKeywordsDraft);
  const hasUnsavedWebExcludeKeywords = normalizedWebExcludeKeywordsDraft !== savedWebExcludeKeywords;
  const normalizedSynonymGroupsDraft = normalizeSynonymGroups(synonymGroupsDraft);
  const hasUnsavedSynonymGroups = normalizedSynonymGroupsDraft !== savedSynonymGroups;
  const normalizedObsidianSidebarExplorerDataPathDraft = obsidianSidebarExplorerDataPathDraft.trim();
  const hasUnsavedObsidianSidebarExplorerDataPath =
    normalizedObsidianSidebarExplorerDataPathDraft !== savedObsidianSidebarExplorerDataPath;
  const normalizedGanttParentDraft = normalizeGanttParent(ganttParentDraft);
  const hasUnsavedGanttParent = normalizedGanttParentDraft !== savedGanttParent || ganttParentDraft.trim() !== String(normalizedGanttParentDraft);
  const hasUnsavedIndexExtensions =
    selectedIndexExtensions.join(" ") !== savedIndexExtensions.join(" ") ||
    customContentExtensions.join(" ") !== savedCustomContentExtensions.join(" ") ||
    customFilenameExtensions.join(" ") !== savedCustomFilenameExtensions.join(" ");
  const sortedResults = sortSearchResults(results, { sortBy, sortOrder });
  const visibleResults = filterSearchResultsByExtensions(sortedResults, searchFilterText);
  const loadMoreTriggerRef = useRef<HTMLDivElement | null>(null);
  const isSchedulerPage = pageView === "scheduler";
  const isLauncherPage = pageView === "launcher";
  const isSearchTargetsPage = pageView === "search-targets";
  const isRuleManagementPage = pageView === "rule-management";
  const excludeKeywordEntries = normalizedExcludeKeywordsDraft.split("\n").filter(Boolean);
  const synonymGroupEntries = normalizedSynonymGroupsDraft.split("\n").filter(Boolean);
  const filteredExcludeKeywordEntries = excludeKeywordEntries.filter((item) => item.toLowerCase().includes(excludeRuleFilterText.trim().toLowerCase()));
  const filteredSynonymGroupEntries = synonymGroupEntries.filter((item) => item.toLowerCase().includes(synonymRuleFilterText.trim().toLowerCase()));
  const excludeKeywordSet = new Set(excludeKeywordEntries.map((item) => item.toLowerCase()));
  const candidateSearchTargetPath = fullPath.trim();
  const fallbackCoveredByLocalTargets = isPathCoveredByTarget(candidateSearchTargetPath, searchTargets);
  const isLaunchPathAddable = Boolean(
    candidateSearchTargetPath &&
    !(isCurrentPathCovered || fallbackCoveredByLocalTargets),
  );

  async function refreshIndexStatus(): Promise<IndexStatus> {
    const response = await fetchIndexStatus();
    setIndexStatus(response);
    return response;
  }

  async function refreshSchedulerState(): Promise<void> {
    const response = await fetchSchedulerSettings();
    setSchedulerState(response);
    setSchedulerPaths(response.paths);
    setSchedulerStartAt(toLocalDateTimeInputValue(response.start_at));
  }

  async function refreshLauncherState(): Promise<void> {
    const response = await fetchLauncherStatus();
    setLauncherState(response);
  }

  /**
   * インデックス済みフォルダ一覧を取得し、消えた選択状態は自動で外す。
   */
  async function refreshIndexedTargets(sourceType: SearchSource = "local"): Promise<void> {
    setIsLoadingTargets(true);
    try {
      const response = await fetchIndexedTargets(sourceType);
      setIndexedTargets(response.items);
      setSelectedTargetPaths((current) => current.filter((path) => response.items.some((item) => item.full_path === path)));
    } finally {
      setIsLoadingTargets(false);
    }
  }

  /**
   * 検索対象フォルダ一覧を取得し、消えた選択状態を外す。
   */
  async function refreshSearchTargets(): Promise<void> {
    setIsLoadingTargets(true);
    try {
      const response = await fetchSearchTargets();
      setSearchTargets(response.items);
    } finally {
      setIsLoadingTargets(false);
    }
  }

  async function loadInitialData(): Promise<void> {
    try {
      const appSettings = await fetchAppSettings();
      const normalizedExcludeKeywords = normalizeExcludeKeywords(appSettings.exclude_keywords);
      const normalizedWebExcludeKeywords = normalizeExcludeKeywords(appSettings.web_exclude_keywords);
      const normalizedHiddenIndexedTargets = normalizeHiddenIndexedTargets(appSettings.hidden_indexed_targets);
      const normalizedSynonymGroups = normalizeSynonymGroups(appSettings.synonym_groups);
      const loadedCustomContentExtensions = parseExtensionText(appSettings.custom_content_extensions);
      const loadedCustomFilenameExtensions = parseExtensionText(appSettings.custom_filename_extensions);
      const loadedAvailableExtensions = buildAvailableExtensions(loadedCustomContentExtensions, loadedCustomFilenameExtensions);
      const loadedSelectedIndexExtensions = normalizeIndexExtensions(
        parseExtensionText(appSettings.index_selected_extensions),
        loadedAvailableExtensions,
      );
      setSavedExcludeKeywords(normalizedExcludeKeywords);
      setExcludeKeywordsDraft(normalizedExcludeKeywords);
      setSavedWebExcludeKeywords(normalizedWebExcludeKeywords);
      setWebExcludeKeywordsDraft(normalizedWebExcludeKeywords);
      setSavedHiddenIndexedTargets(normalizedHiddenIndexedTargets);
      setHideKeyword(normalizedHiddenIndexedTargets);
      setSavedSynonymGroups(normalizedSynonymGroups);
      setSynonymGroupsDraft(normalizedSynonymGroups);
      setSavedObsidianSidebarExplorerDataPath(appSettings.obsidian_sidebar_explorer_data_path.trim());
      setObsidianSidebarExplorerDataPathDraft(appSettings.obsidian_sidebar_explorer_data_path.trim());
      setSavedGanttParent(normalizeGanttParent(appSettings.gantt_parent));
      setGanttParentDraft(String(normalizeGanttParent(appSettings.gantt_parent)));
      setSavedCustomContentExtensions(loadedCustomContentExtensions);
      setCustomContentExtensions(loadedCustomContentExtensions);
      setSavedCustomFilenameExtensions(loadedCustomFilenameExtensions);
      setCustomFilenameExtensions(loadedCustomFilenameExtensions);
      setSavedIndexExtensions(loadedSelectedIndexExtensions);
      setSelectedIndexExtensions(loadedSelectedIndexExtensions);
      setHasLoadedAppSettings(true);
      await refreshIndexStatus();
      await refreshSchedulerState();
      await refreshLauncherState();
      await refreshSearchTargets();
    } catch (error) {
      setNoticeMessage("");
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
    if (!hasLoadedAppSettings) {
      return;
    }
    const normalized = normalizeHiddenIndexedTargets(hideKeyword);
    if (normalized === savedHiddenIndexedTargets) {
      return;
    }

    const timerId = window.setTimeout(() => {
      void (async () => {
        try {
          const savedSettings = await updateAppSettings({ hidden_indexed_targets: normalized });
          const savedValue = normalizeHiddenIndexedTargets(savedSettings.hidden_indexed_targets);
          setSavedHiddenIndexedTargets(savedValue);
          setHideKeyword(savedValue);
        } catch (error) {
          setNoticeMessage("");
          setErrorMessage(error instanceof Error ? error.message : "非表示キーワードの保存に失敗しました。");
        }
      })();
    }, 400);

    return () => window.clearTimeout(timerId);
  }, [hasLoadedAppSettings, hideKeyword, savedHiddenIndexedTargets]);

  /**
   * 検索欄のパスが有効な検索対象フォルダに内包されるかをバックエンド基準で確認する。
   */
  useEffect(() => {
    const targetPath = fullPath.trim();
    if (!targetPath) {
      setIsCurrentPathCovered(false);
      return;
    }
    let isActive = true;
    setIsCurrentPathCovered(isPathCoveredByTarget(targetPath, searchTargets));
    const timerId = window.setTimeout(() => {
      void (async () => {
        try {
          const coverage = await fetchSearchTargetCoverage(targetPath);
          if (isActive) {
            setIsCurrentPathCovered(coverage.is_covered);
          }
        } catch {
          // 通信失敗時はローカル判定のまま継続する。
        }
      })();
    }, 200);

    return () => {
      isActive = false;
      window.clearTimeout(timerId);
    };
  }, [fullPath, searchTargets, searchSource]);

  /**
   * 検索中やインデックス実行中はステータスを定期取得し、中止ボタンの表示状態を追従させる。
   */
  useEffect(() => {
    if (!isSearching && !indexStatus?.is_running && !pendingAutoRefresh) {
      return;
    }

    const timerId = window.setInterval(() => {
      void refreshIndexStatus();
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, [isSearching, indexStatus?.is_running, pendingAutoRefresh]);

  useEffect(() => {
    if (!pendingAutoRefresh || !indexStatus) {
      return;
    }

    if (pendingAutoRefresh.searchKey !== buildSearchKeyFromState()) {
      setPendingAutoRefresh(null);
      return;
    }

    if (!pendingAutoRefresh.hasObservedRunning) {
      if (indexStatus.is_running) {
        setPendingAutoRefresh((current) =>
          current ? { ...current, hasObservedRunning: true } : current,
        );
        return;
      }
      if (indexStatus.last_finished_at && indexStatus.last_finished_at !== pendingAutoRefresh.baselineLastFinishedAt) {
        const params = pendingAutoRefresh.params;
        setPendingAutoRefresh(null);
        void executeSearch(params, { isAutoRefresh: true });
      }
      return;
    }

    if (!indexStatus.is_running) {
      const params = pendingAutoRefresh.params;
      setPendingAutoRefresh(null);
      void executeSearch(params, { isAutoRefresh: true });
    }
  }, [
    pendingAutoRefresh,
    indexStatus,
    query,
    fullPath,
    isSearchAllEnabled,
    indexDepth,
    refreshWindowMinutes,
    isRegexEnabled,
    selectedIndexExtensions,
    dateField,
    sortBy,
    sortOrder,
    createdFrom,
    createdTo,
    searchTarget,
    searchSource,
    includeGanttTasks,
  ]);

  useEffect(() => {
    const isSchedulerActive = schedulerState?.is_enabled || schedulerState?.status === "running" || schedulerState?.status === "launching";
    if (!isSchedulerActive) {
      return;
    }

    const timerId = window.setInterval(() => {
      void refreshSchedulerState().catch(() => undefined);
    }, 1000);

    return () => {
      window.clearInterval(timerId);
    };
  }, [pageView, schedulerState?.is_enabled, schedulerState?.status]);

  useEffect(() => {
    if (pageView !== "launcher" && !launcherState?.is_running) {
      return;
    }

    const timerId = window.setInterval(() => {
      void refreshLauncherState().catch(() => undefined);
    }, 1500);

    return () => {
      window.clearInterval(timerId);
    };
  }, [pageView, launcherState?.is_running]);

  useEffect(() => {
    if (!shouldAutoSearch(launchParams)) {
      return;
    }

    const autoSearchKey = `${launchParams.q}\n${launchParams.fullPath}\n${launchParams.indexDepth}\n${launchParams.searchAll}`;
    if (lastAutoSearchKey === autoSearchKey) {
      return;
    }

    lastAutoSearchKey = autoSearchKey;
    void handleSearch();
  }, [launchParams]);

  useEffect(() => {
    if (!loadMoreTriggerRef.current || !currentSearchParams || !hasMoreResults) {
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      const firstEntry = entries[0];
      if (!firstEntry?.isIntersecting) {
        return;
      }
      void loadMoreResults(currentSearchParams);
    }, { rootMargin: "320px 0px" });

    observer.observe(loadMoreTriggerRef.current);
    return () => observer.disconnect();
  }, [currentSearchParams, hasMoreResults, isLoadingMoreResults, isSearching, searchNextOffset]);

  function buildSearchKeyFromState(): string {
    return [
      query,
      fullPath.trim(),
      searchSource,
      String(includeGanttTasks),
      String(isSearchAllEnabled),
      indexDepth,
      refreshWindowMinutes,
      String(isRegexEnabled),
      searchTarget,
      selectedIndexExtensions.join(" "),
      dateField,
      sortBy,
      sortOrder,
      createdFrom,
      createdTo,
    ].join("\n");
  }

  async function executeSearch(params: SearchExecutionParams, options?: { isAutoRefresh?: boolean }): Promise<void> {
    try {
      setIsSearching(true);
      setIsLoadingMoreResults(false);
      setErrorMessage("");
      if (!options?.isAutoRefresh) {
        setNoticeMessage("");
      }
      setCurrentSearchParams(params);
      const response = await fetchSearchPage({
        ...params,
        limit: 50,
        offset: 0,
        include_snippets: true,
      });
      setResults(response.items);
      setSearchTotal(response.total);
      setHasMoreResults(response.has_more);
      setSearchNextOffset(response.next_offset);
      const latestStatus = await refreshIndexStatus();
      if (isFailedFilesOpen) {
        const failedResponse = await fetchFailedFiles();
        setFailedFiles(failedResponse.items);
      }
      localStorage.setItem("refresh_window_minutes", String(params.refresh_window_minutes));
      localStorage.setItem("search_filter_extensions", searchFilterText);
      if (options?.isAutoRefresh) {
        setNoticeMessage("バックグラウンド再インデックスが完了したため、検索結果を自動更新しました。");
      } else if (searchSource === "local" && hasUnsavedExcludeKeywords) {
        setNoticeMessage("未保存の除外キーワードは今回の検索に反映していません。保存後に再検索してください。");
      } else if (searchSource === "web" && hasUnsavedWebExcludeKeywords) {
        setNoticeMessage("未保存のWeb除外キーワードは今回の検索に反映していません。保存後に再検索してください。");
      } else if (hasUnsavedSynonymGroups) {
        setNoticeMessage("未保存の同義語リストは今回の検索に反映していません。保存後に再検索してください。");
      } else if (response.background_refresh_scheduled) {
        setPendingAutoRefresh({
          params: { ...params, skip_refresh: true },
          searchKey: buildSearchKeyFromState(),
          baselineLastFinishedAt: latestStatus.last_finished_at,
          hasObservedRunning: latestStatus.is_running,
        });
        setNoticeMessage("既存インデックスで先に結果を表示しつつ、フォルダの再インデックスをバックグラウンドで更新しています。");
      } else if (response.used_existing_index) {
        setNoticeMessage("既存インデックスを使って検索結果を表示しました。");
      } else {
        setPendingAutoRefresh(null);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "検索に失敗しました。";
      if (message === "Indexing was cancelled.") {
        setNoticeMessage("インデックス作成を中止しました。必要になったら再検索で再開できます。");
        setErrorMessage("");
      } else {
        setErrorMessage(message);
      }
    } finally {
      await refreshIndexStatus().catch(() => undefined);
      setIsSearching(false);
    }
  }

  async function loadMoreResults(params: SearchExecutionParams): Promise<void> {
    if (isSearching || isLoadingMoreResults || !hasMoreResults || searchNextOffset === null) {
      return;
    }

    try {
      setIsLoadingMoreResults(true);
      const response = await fetchSearchPage({
        ...params,
        limit: 50,
        offset: searchNextOffset,
        include_snippets: true,
      });
      setResults((current) => [...current, ...response.items]);
      setSearchTotal(response.total);
      setHasMoreResults(response.has_more);
      setSearchNextOffset(response.next_offset);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "検索結果の追加取得に失敗しました。");
    } finally {
      setIsLoadingMoreResults(false);
    }
  }

  async function handleSearch(): Promise<void> {
    if (isSearching) {
      return;
    }
    const normalizedInputPath = fullPath.trim();
    const resolvedSearchPath = normalizedInputPath;
    if (!query.trim()) {
      setErrorMessage("検索語を入力してください。");
      return;
    }
    const parsedWindow = Number(refreshWindowMinutes);
    let parsedDepth: number | undefined = undefined;
    if (indexDepth.trim()) {
      parsedDepth = Number(indexDepth);
      if (Number.isNaN(parsedDepth) || parsedDepth < 0) {
        setErrorMessage("階層数は 0 以上で入力してください。");
        return;
      }
    }
    if (Number.isNaN(parsedWindow) || parsedWindow < 0) {
      setErrorMessage("更新間隔は 0 以上の分で入力してください。");
      setIsMenuOpen(true);
      return;
    }
    if (createdFrom && createdTo && createdFrom > createdTo) {
      setErrorMessage("作成日の終了日は開始日以降で入力してください。");
      return;
    }
    if (selectedIndexExtensions.length === 0) {
      setErrorMessage("インデックス対象の拡張子を 1 つ以上選択してください。");
      setIsMenuOpen(true);
      return;
    }

    await executeSearch({
      q: query,
      full_path: resolvedSearchPath,
      search_all_enabled: isSearchAllEnabled,
      source_type: searchSource,
      include_gantt_tasks: includeGanttTasks,
      index_depth: parsedDepth,
      refresh_window_minutes: parsedWindow,
      regex_enabled: isRegexEnabled,
      search_target: searchTarget,
      index_types: selectedIndexExtensions.join(" "),
      date_field: dateField,
      sort_by: sortBy,
      sort_order: sortOrder,
      created_from: createdFrom || undefined,
      created_to: createdTo || undefined,
    });
  }

  async function handlePickFolder(): Promise<void> {
    try {
      const payload = await pickFolder();
      setFullPath(payload.full_path ?? "");
      setErrorMessage("");
      setNoticeMessage("");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "フォルダ選択に失敗しました。");
    }
  }

  function handleOpenSchedulerPage(): void {
    setPageView("scheduler");
    setIsMenuOpen(false);
    setErrorMessage("");
    setNoticeMessage("");
    void refreshSchedulerState().catch(() => undefined);
  }

  /** 検索ルールの変更を履歴へ積み、Ctrl+Z / Ctrl+Shift+Z の対象にする。 */
  function applyRuleChanges(nextExcludeKeywords: string, nextSynonymGroups: string): void {
    const current: RuleSnapshot = {
      excludeKeywords: normalizedExcludeKeywordsDraft,
      synonymGroups: normalizedSynonymGroupsDraft,
    };
    const next: RuleSnapshot = {
      excludeKeywords: normalizeExcludeKeywords(nextExcludeKeywords),
      synonymGroups: normalizeSynonymGroups(nextSynonymGroups),
    };
    if (current.excludeKeywords === next.excludeKeywords && current.synonymGroups === next.synonymGroups) return;
    if (ruleHistoryIndexRef.current < 0) {
      ruleHistoryRef.current = [current];
      ruleHistoryIndexRef.current = 0;
    }
    ruleHistoryRef.current = ruleHistoryRef.current.slice(0, ruleHistoryIndexRef.current + 1);
    ruleHistoryRef.current.push(next);
    ruleHistoryIndexRef.current += 1;
    setExcludeKeywordsDraft(next.excludeKeywords);
    setSynonymGroupsDraft(next.synonymGroups);
  }

  /** 最後の検索ルール変更を取り消す。 */
  function handleUndoRuleChange(): void {
    if (ruleHistoryIndexRef.current <= 0) return;
    ruleHistoryIndexRef.current -= 1;
    const snapshot = ruleHistoryRef.current[ruleHistoryIndexRef.current];
    setExcludeKeywordsDraft(snapshot.excludeKeywords);
    setSynonymGroupsDraft(snapshot.synonymGroups);
    setNoticeMessage("検索ルールの変更を取り消しました。自動保存します。");
  }

  /** 取り消した検索ルール変更をやり直す。 */
  function handleRedoRuleChange(): void {
    if (ruleHistoryIndexRef.current >= ruleHistoryRef.current.length - 1) return;
    ruleHistoryIndexRef.current += 1;
    const snapshot = ruleHistoryRef.current[ruleHistoryIndexRef.current];
    setExcludeKeywordsDraft(snapshot.excludeKeywords);
    setSynonymGroupsDraft(snapshot.synonymGroups);
    setNoticeMessage("検索ルールの変更をやり直しました。自動保存します。");
  }

  /** 同じ種類のルールをドラッグ先へ移動し、表示順も保存対象にする。 */
  function handleMoveRuleItem(kind: RuleKind, sourceItem: string, targetItem: string): void {
    if (sourceItem === targetItem) return;
    const sourceEntries = kind === "exclude" ? excludeKeywordEntries : synonymGroupEntries;
    const fromIndex = sourceEntries.indexOf(sourceItem);
    const toIndex = sourceEntries.indexOf(targetItem);
    if (fromIndex < 0 || toIndex < 0) return;
    const nextEntries = [...sourceEntries];
    const [moved] = nextEntries.splice(fromIndex, 1);
    nextEntries.splice(toIndex, 0, moved);
    if (kind === "exclude") {
      applyRuleChanges(nextEntries.join("\n"), normalizedSynonymGroupsDraft);
    } else {
      applyRuleChanges(normalizedExcludeKeywordsDraft, nextEntries.join("\n"));
    }
  }

  /** 右クリックメニューから、確認を経てルールを削除する。 */
  function handleDeleteRuleItem(kind: RuleKind, item: string): void {
    setRuleContextMenu(null);
    if (!window.confirm("本当に削除しますか？")) return;
    setSelectedRuleItem((current) => current?.kind === kind && current.item === item ? null : current);
    if (kind === "exclude") {
      applyRuleChanges(excludeKeywordEntries.filter((entry) => entry !== item).join("\n"), normalizedSynonymGroupsDraft);
    } else {
      applyRuleChanges(normalizedExcludeKeywordsDraft, synonymGroupEntries.filter((entry) => entry !== item).join("\n"));
    }
  }

  /** 見出しの追加ボタンから、対象リスト専用の入力ポップアップを開く。 */
  function handleOpenRuleAddModal(kind: RuleKind): void {
    setActiveRuleKind(kind);
    setRuleAddKind(kind);
    setIsRuleAddModalOpen(true);
  }

  /** ポップアップの入力を追加し、成功時だけ閉じる。 */
  function handleSubmitRuleAdd(): void {
    const added = ruleAddKind === "exclude" ? handleAddExcludeKeyword() : handleAddSynonymGroup();
    if (added) setIsRuleAddModalOpen(false);
  }

  /** 除外キーワードを重複なく下書きへ追加する。 */
  function handleAddExcludeKeyword(): boolean {
    const keyword = newExcludeKeyword.trim();
    if (!keyword) return false;
    if (excludeKeywordSet.has(keyword.toLowerCase())) {
      setNoticeMessage(`「${keyword}」は除外リストに登録済みです。`);
      return false;
    }
    applyRuleChanges([...excludeKeywordEntries, keyword].join("\n"), normalizedSynonymGroupsDraft);
    setNewExcludeKeyword("");
    setNoticeMessage(`「${keyword}」を追加しました。自動保存します。`);
    return true;
  }

  /** 同義語グループを正規化して下書きへ追加し、語の重複や除外語との競合を知らせる。 */
  function handleAddSynonymGroup(): boolean {
    const group = normalizeSynonymGroups(newSynonymGroup);
    if (!group) return false;
    const tokens = group.split(",").map((item) => item.toLowerCase());
    const registeredTokens = new Set(synonymGroupEntries.flatMap((item) => item.split(",").map((token) => token.toLowerCase())));
    const duplicatedToken = tokens.find((item) => registeredTokens.has(item));
    if (duplicatedToken) {
      setNoticeMessage(`「${duplicatedToken}」は同義語内で重複して登録されています。`);
      return false;
    }
    const excludedToken = tokens.find((item) => excludeKeywordSet.has(item));
    if (excludedToken) {
      setNoticeMessage(`「${excludedToken}」は除外リストに登録済みです。内容を確認してから追加してください。`);
      return false;
    }
    applyRuleChanges(normalizedExcludeKeywordsDraft, [...synonymGroupEntries, group].join("\n"));
    setNewSynonymGroup("");
    setNoticeMessage("同義語グループを追加しました。自動保存します。");
    return true;
  }

  /** ダブルクリックで開始した除外キーワードのインライン編集を確定する。 */
  function handleUpdateExcludeKeyword(original: string): void {
    const next = editingExcludeKeywordValue.trim();
    setEditingExcludeKeyword(null);
    if (!next || next === original) return;
    if (excludeKeywordEntries.some((item) => item !== original && item.toLowerCase() === next.toLowerCase())) {
      setNoticeMessage(`「${next}」は除外リストに登録済みです。`);
      return;
    }
    applyRuleChanges(excludeKeywordEntries.map((item) => item === original ? next : item).join("\n"), normalizedSynonymGroupsDraft);
  }

  /** ダブルクリックで開始した同義語グループのインライン編集を確定する。 */
  function handleUpdateSynonymGroup(original: string): void {
    const next = normalizeSynonymGroups(editingSynonymGroupValue);
    setEditingSynonymGroup(null);
    if (!next || next === original) return;
    const otherTokens = new Set(synonymGroupEntries.filter((item) => item !== original).flatMap((item) => item.split(",").map((token) => token.toLowerCase())));
    const duplicate = next.split(",").map((item) => item.toLowerCase()).find((item) => otherTokens.has(item));
    if (duplicate) {
      setNoticeMessage(`「${duplicate}」は同義語内で重複して登録されています。`);
      return;
    }
    applyRuleChanges(normalizedExcludeKeywordsDraft, synonymGroupEntries.map((item) => item === original ? next : item).join("\n"));
  }

  function handleAddSchedulerPath(path: string): void {
    const normalized = path.trim();
    if (!normalized) {
      setErrorMessage("スケジューラーに追加するパスを入力してください。");
      return;
    }
    setSchedulerPaths((current) => (current.includes(normalized) ? current : [...current, normalized]));
    setSchedulerPathDraft("");
    setErrorMessage("");
  }

  async function handlePickSchedulerFolder(): Promise<void> {
    try {
      const payload = await pickFolder();
      if (payload.full_path) {
        handleAddSchedulerPath(payload.full_path);
      }
      setNoticeMessage("");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "スケジューラー用フォルダの選択に失敗しました。");
    }
  }

  async function handleStartScheduler(): Promise<void> {
    if (isStartingScheduler) {
      return;
    }
    if (schedulerPaths.length === 0) {
      setErrorMessage("スケジューラーの対象フォルダを 1 つ以上追加してください。");
      return;
    }
    if (!schedulerStartAt) {
      setErrorMessage("スケジューラーの開始日時を入力してください。");
      return;
    }

    try {
      setIsStartingScheduler(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await startScheduler({
        paths: schedulerPaths,
        start_at: toSchedulerStartAtIso(schedulerStartAt),
      });
      setSchedulerState(response);
      setSchedulerPaths(response.paths);
      setSchedulerStartAt(toLocalDateTimeInputValue(response.start_at));
      setNoticeMessage("スケジューラーを開始しました。開始時刻になると別プロセスで順次インデックス化します。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "スケジューラーの開始に失敗しました。");
    } finally {
      setIsStartingScheduler(false);
    }
  }

  /**
   * 全 DB 検索の切り替えでは入力済みパスを保持し、後でフォルダ検索へ戻りやすくする。
   */
  function handleToggleSearchAll(): void {
    setIsSearchAllEnabled((current) => !current);
    setErrorMessage("");
    setNoticeMessage("");
  }

  /**
   * フォルダ入力は全 DB 検索中でも保持し、次回のフォルダ限定検索へそのまま使えるようにする。
   */
  function handleFullPathChange(value: string): void {
    setFullPath(value);
  }

  function handleSearchTargetChange(value: SearchTarget): void {
    setSearchTarget(value);
  }

  function handleSearchSourceChange(value: SearchSource): void {
    setSearchSource(value);
    setErrorMessage("");
    setNoticeMessage("");
  }

  function handleIncludeGanttTasksChange(value: boolean): void {
    setIncludeGanttTasks(value);
    setErrorMessage("");
    setNoticeMessage("");
  }

  /**
   * 作成日フィルタは 2 項目まとめて解除し、未指定検索へ戻す。
   */
  function handleClearCreatedDateFilter(): void {
    setCreatedFrom("");
    setCreatedTo("");
    setErrorMessage("");
  }

  /**
   * よく使う相対日付のボタンから開始日と終了日を一度に入力する。
   */
  function handleApplyDateShortcut(days: number): void {
    setCreatedFrom(resolveRelativeDateInputValue(days));
    setCreatedTo(resolveTodayDateInputValue());
    setErrorMessage("");
    setNoticeMessage("");
  }

  /**
   * 検索結果を開いた回数を記録し、次回以降のアクセス数順ソートへ反映する。
   */
  function handleResultOpen(fileId: number): void {
    void recordSearchClick(fileId, query)
      .then((response) => {
        setResults((current) =>
          current.map((item) =>
            item.file_id === response.file_id ? { ...item, click_count: response.click_count } : item,
          ),
        );
      })
      .catch(() => undefined);
  }

  function handleGanttTaskOpen(taskId: number): void {
    void openGanttTaskInput(taskId).catch((error) => {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "gantt タスクを開けませんでした。");
    });
  }

  async function handleResultDelete(fileId: number, fullPath: string): Promise<void> {
    if (!window.confirm(`このファイルを完全に削除しますか？\n（物理ファイルが削除され元に戻せません）\n\n${fullPath}`)) {
      return;
    }
    
    try {
      await deleteFile(fileId);
      setResults((current) => current.filter((item) => item.file_id !== fileId));
      setNoticeMessage("ファイルを削除しました。");
      setErrorMessage("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "ファイルの削除に失敗しました。");
      setNoticeMessage("");
    }
  }

  /**
   * 検索結果のフルパスを除外キーワードへ追記し、以後の検索結果へ出さないようにする。
   */
  async function handleResultIgnore(_fileId: number, fullPath: string): Promise<void> {
    const nextExcludeKeywords = normalizeExcludeKeywords([savedExcludeKeywords, fullPath].filter(Boolean).join("\n"));
    if (nextExcludeKeywords === savedExcludeKeywords) {
      setResults((current) => current.filter((item) => item.full_path !== fullPath));
      setSearchTotal((current) => Math.max(0, current - 1));
      setNoticeMessage("対象ファイルは既に無視リストへ追加済みです。");
      setErrorMessage("");
      return;
    }

    try {
      setIsIgnoringResultPath(fullPath);
      const savedSettings = await updateAppSettings({ exclude_keywords: nextExcludeKeywords });
      const savedValue = normalizeExcludeKeywords(savedSettings.exclude_keywords);
      setSavedExcludeKeywords(savedValue);
      setExcludeKeywordsDraft(savedValue);
      setResults((current) => current.filter((item) => item.full_path !== fullPath));
      setSearchTotal((current) => Math.max(0, current - 1));
      setErrorMessage("");
      setNoticeMessage("無視リストへ追加しました。次回以降の検索結果から除外されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "無視リストへの追加に失敗しました。");
    } finally {
      setIsIgnoringResultPath((currentPath) => (currentPath === fullPath ? null : currentPath));
    }
  }

  function toggleIndexExtension(extension: string): void {
    setSelectedIndexExtensions((current) =>
      current.includes(extension) ? current.filter((item) => item !== extension) : [...current, extension],
    );
  }

  function setAllIndexExtensions(): void {
    setSelectedIndexExtensions([...availableIndexExtensions]);
  }

  function clearAllIndexExtensions(): void {
    setSelectedIndexExtensions([]);
  }

  /**
   * 利用者追加拡張子を下書きへ加え、同時にインデックス対象としても選択状態にする。
   */
  function handleAddCustomExtension(kind: "content" | "filename"): void {
    const nextExtension = normalizeExtensionToken(kind === "content" ? newContentExtension : newFilenameExtension);
    if (!nextExtension) {
      setErrorMessage("追加する拡張子を入力してください。");
      return;
    }
    if (availableIndexExtensions.includes(nextExtension)) {
      setErrorMessage(`拡張子 ${nextExtension} は既に登録されています。`);
      return;
    }

    if (kind === "content") {
      setCustomContentExtensions((current) => [...current, nextExtension]);
      setNewContentExtension("");
    } else {
      setCustomFilenameExtensions((current) => [...current, nextExtension]);
      setNewFilenameExtension("");
    }
    setSelectedIndexExtensions((current) => [...current, nextExtension]);
    setErrorMessage("");
    setNoticeMessage("");
  }

  /**
   * 追加拡張子を下書きから外し、選択状態にも残さない。
   */
  function handleRemoveCustomExtension(extension: string, kind: "content" | "filename"): void {
    if (kind === "content") {
      setCustomContentExtensions((current) => current.filter((item) => item !== extension));
    } else {
      setCustomFilenameExtensions((current) => current.filter((item) => item !== extension));
    }
    setSelectedIndexExtensions((current) => current.filter((item) => item !== extension));
    setErrorMessage("");
    setNoticeMessage("");
  }

  /**
   * インデックス対象拡張子と追加拡張子一覧をテキストファイル管理の設定として保存する。
   */
  async function handleSaveIndexExtensions(): Promise<void> {
    const normalizedCustomContentExtensions = normalizeCustomExtensions(customContentExtensions);
    const normalizedCustomFilenameExtensions = normalizeCustomExtensions(customFilenameExtensions);
    const normalizedAvailableExtensions = buildAvailableExtensions(
      normalizedCustomContentExtensions,
      normalizedCustomFilenameExtensions,
    );
    const normalizedSelectedIndexExtensions = normalizeIndexExtensions(selectedIndexExtensions, normalizedAvailableExtensions);
    try {
      setIsSavingIndexExtensions(true);
      const savedSettings = await updateAppSettings({
        index_selected_extensions: normalizedSelectedIndexExtensions.join("\n"),
        custom_content_extensions: normalizedCustomContentExtensions.join("\n"),
        custom_filename_extensions: normalizedCustomFilenameExtensions.join("\n"),
      });
      const savedCustomContent = parseExtensionText(savedSettings.custom_content_extensions);
      const savedCustomFilename = parseExtensionText(savedSettings.custom_filename_extensions);
      const savedAvailableExtensions = buildAvailableExtensions(savedCustomContent, savedCustomFilename);
      const savedSelected = normalizeIndexExtensions(parseExtensionText(savedSettings.index_selected_extensions), savedAvailableExtensions);
      setSavedCustomContentExtensions(savedCustomContent);
      setCustomContentExtensions(savedCustomContent);
      setSavedCustomFilenameExtensions(savedCustomFilename);
      setCustomFilenameExtensions(savedCustomFilename);
      setSavedIndexExtensions(savedSelected);
      setSelectedIndexExtensions(savedSelected);
      setErrorMessage("");
      setNoticeMessage(
        savedSelected.length > 0
          ? "インデックス対象拡張子を保存しました。テキストファイルを編集した内容もここに反映されます。"
          : "インデックス対象の拡張子をすべて解除した状態で保存しました。",
      );
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス対象拡張子の保存に失敗しました。");
    } finally {
      setIsSavingIndexExtensions(false);
    }
  }

  /**
   * 除外キーワードは明示的な保存ボタンでだけ確定し、次回検索から必ず同じ値を使う。
   */
  async function handleSaveExcludeKeywords(): Promise<void> {
    const normalized = normalizeExcludeKeywords(excludeKeywordsDraft);
    try {
      setIsSavingExcludeKeywords(true);
      const savedSettings = await updateAppSettings({ exclude_keywords: normalized });
      const savedValue = normalizeExcludeKeywords(savedSettings.exclude_keywords);
      setSavedExcludeKeywords(savedValue);
      setExcludeKeywordsDraft(savedValue);
      setErrorMessage("");
      setNoticeMessage("除外キーワードを保存しました。次回検索から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "除外キーワードの保存に失敗しました。");
    } finally {
      setIsSavingExcludeKeywords(false);
    }
  }

  /**
   * Web クロール用の除外キーワードはローカルフォルダ用と分けて保存する。
   */
  async function handleSaveWebExcludeKeywords(): Promise<void> {
    const normalized = normalizeExcludeKeywords(webExcludeKeywordsDraft);
    try {
      setIsSavingWebExcludeKeywords(true);
      const savedSettings = await updateAppSettings({ web_exclude_keywords: normalized });
      const savedValue = normalizeExcludeKeywords(savedSettings.web_exclude_keywords);
      setSavedWebExcludeKeywords(savedValue);
      setWebExcludeKeywordsDraft(savedValue);
      setErrorMessage("");
      setNoticeMessage("Web除外キーワードを保存しました。次回Web検索から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "Web除外キーワードの保存に失敗しました。");
    } finally {
      setIsSavingWebExcludeKeywords(false);
    }
  }

  /**
   * 同義語リストは明示的な保存ボタンでだけ確定し、通常検索の表記ゆれ対応へ反映する。
   */
  async function handleSaveSynonymGroups(): Promise<void> {
    const normalized = normalizeSynonymGroups(synonymGroupsDraft);
    try {
      setIsSavingSynonymGroups(true);
      const savedSettings = await updateAppSettings({ synonym_groups: normalized });
      const savedValue = normalizeSynonymGroups(savedSettings.synonym_groups);
      setSavedSynonymGroups(savedValue);
      setSynonymGroupsDraft(savedValue);
      setErrorMessage("");
      setNoticeMessage("同義語リストを保存しました。次回検索から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "同義語リストの保存に失敗しました。");
    } finally {
      setIsSavingSynonymGroups(false);
    }
  }

  /**
   * Obsidian sidebar-explorer の data.json パスはバックエンド保存し、再読込後も同じ値を使う。
   */
  async function handleSaveObsidianSidebarExplorerDataPath(): Promise<void> {
    const normalized = obsidianSidebarExplorerDataPathDraft.trim();
    try {
      setIsSavingObsidianSidebarExplorerDataPath(true);
      const savedSettings = await updateAppSettings({ obsidian_sidebar_explorer_data_path: normalized });
      const savedValue = savedSettings.obsidian_sidebar_explorer_data_path.trim();
      setSavedObsidianSidebarExplorerDataPath(savedValue);
      setObsidianSidebarExplorerDataPathDraft(savedValue);
      setErrorMessage("");
      setNoticeMessage("Obsidian sidebar-explorer の data.json パスを保存しました。次回検索後の同期から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "Obsidian パスの保存に失敗しました。");
    } finally {
      setIsSavingObsidianSidebarExplorerDataPath(false);
    }
  }

  /**
   * ランチャーの gantt メモ追加で使う parent ID を Web 側の共有設定として保存する。
   */
  async function handleSaveGanttParent(): Promise<void> {
    const normalized = normalizeGanttParent(ganttParentDraft);
    try {
      setIsSavingGanttParent(true);
      const savedSettings = await updateAppSettings({ gantt_parent: normalized });
      const savedValue = normalizeGanttParent(savedSettings.gantt_parent);
      setSavedGanttParent(savedValue);
      setGanttParentDraft(String(savedValue));
      setErrorMessage("");
      setNoticeMessage("gantt parent を保存しました。ランチャーの次回メモ送信から反映されます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "gantt parent の保存に失敗しました。");
    } finally {
      setIsSavingGanttParent(false);
    }
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
      setNoticeMessage("");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "失敗したファイル一覧の取得に失敗しました。");
    }
  }

  /**
   * 管理ページを開くときに最新一覧を読み込み、検索ページへもすぐ戻れるようにする。
   */
  async function handleChangePage(nextView: PageView): Promise<void> {
    setPageView(nextView);
    setErrorMessage("");
    setNoticeMessage("");
    if (nextView === "indexed-targets" || nextView === "indexed-web-targets") {
      try {
        await refreshIndexedTargets(nextView === "indexed-web-targets" ? "web" : "local");
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "インデックス済み対象の取得に失敗しました。");
      }
    }
    if (nextView === "search-targets") {
      try {
        await refreshSearchTargets();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダの取得に失敗しました。");
      }
    }
    if (nextView === "scheduler") {
      try {
        await refreshSchedulerState();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "スケジューラー設定の取得に失敗しました。");
      }
    }
    if (nextView === "launcher") {
      try {
        await refreshLauncherState();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "ランチャー状態の取得に失敗しました。");
      }
    }
  }

  async function handleLauncherAction(action: "start" | "stop" | "restart"): Promise<void> {
    setIsLauncherActionRunning(true);
    setErrorMessage("");
    setNoticeMessage("");
    try {
      const response =
        action === "start"
          ? await startLauncher()
          : action === "stop"
            ? await stopLauncher()
            : await restartLauncher();
      setLauncherState(response);
      setNoticeMessage(
        action === "start"
          ? "ランチャーを起動しました。"
          : action === "stop"
            ? "ランチャーを停止しました。"
            : "ランチャーを再起動しました。",
      );
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "ランチャー操作に失敗しました。");
    } finally {
      setIsLauncherActionRunning(false);
    }
  }

  /**
   * キーワードで絞り込んだ範囲だけを全選択し、既存の選択は維持する。
   */
  function handleToggleAllIndexedTargets(): void {
    if (filteredTargetPaths.length === 0) {
      return;
    }
    setSelectedTargetPaths((current) => {
      const currentSet = new Set(current);
      if (filteredTargetPaths.every((path) => currentSet.has(path))) {
        return current.filter((path) => !filteredTargetPaths.includes(path));
      }
      const merged = new Set([...current, ...filteredTargetPaths]);
      return [...merged];
    });
  }

  function handleToggleIndexedTarget(folderPath: string): void {
    setSelectedTargetPaths((current) =>
      current.includes(folderPath) ? current.filter((item) => item !== folderPath) : [...current, folderPath],
    );
  }

  /**
   * インデックス済みフォルダ一覧から、そのフォルダ位置を OS のファイルマネージャーで開く。
   */
  async function handleOpenIndexedTargetLocation(folderPath: string): Promise<void> {
    if (isIndexedWebTargetsPage) {
      window.open(folderPath, "_blank", "noopener,noreferrer");
      return;
    }
    setOpeningIndexedTargetPath(folderPath);
    try {
      await openFileLocation(folderPath);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "フォルダを開けませんでした。");
    } finally {
      setOpeningIndexedTargetPath((currentPath) => (currentPath === folderPath ? null : currentPath));
    }
  }

  /**
   * 画面内の確認用キーワードだけを消し、除外キーワードの設定値は保持する。
   */
  function handleClearFilterKeyword(): void {
    setFilterKeyword("");
  }

  /**
   * 必要フォルダを隠すキーワードだけを消し、不要候補抽出の絞り込みは維持する。
   */
  function handleClearHideKeyword(): void {
    setHideKeyword("");
  }

  /**
   * 不要候補抽出に使った絞り込みキーワードを除外キーワードへ追記し、入力欄だけ空に戻す。
   */
  function handleAppendFilterKeywordToExcludeKeywords(): void {
    const nextKeyword = filterKeyword.trim();
    if (!nextKeyword) {
      return;
    }
    setExcludeKeywordsDraft((current) => normalizeExcludeKeywords([current, nextKeyword].filter(Boolean).join("\n")));
    setFilterKeyword("");
    setErrorMessage("");
    setNoticeMessage(`「${nextKeyword}」を除外キーワードへ追加しました。保存すると次回検索から反映されます。`);
    setIsMenuOpen(true);
  }

  /**
   * インデックス済み Web ページの絞り込みキーワードを Web 専用の除外キーワードへ追記する。
   */
  function handleAppendFilterKeywordToWebExcludeKeywords(): void {
    const nextKeyword = filterKeyword.trim();
    if (!nextKeyword) {
      return;
    }
    setWebExcludeKeywordsDraft((current) => normalizeExcludeKeywords([current, nextKeyword].filter(Boolean).join("\n")));
    setFilterKeyword("");
    setErrorMessage("");
    setNoticeMessage(`「${nextKeyword}」をWeb除外キーワードへ追加しました。保存すると次回Web検索から反映されます。`);
    setIsMenuOpen(true);
  }

  async function handleToggleAllSearchTargets(): Promise<void> {
    if (isUpdatingSearchTargets || filteredSearchTargetPaths.length === 0) {
      return;
    }
    const nextEnabled = !isAllFilteredSearchTargetsSelected;
    try {
      setIsUpdatingSearchTargets(true);
      setErrorMessage("");
      setNoticeMessage("");
      for (const folderPath of filteredSearchTargetPaths) {
        const response = await setSearchTargetEnabled({ folder_path: folderPath, is_enabled: nextEnabled });
        setSearchTargets(response.items);
      }
      setNoticeMessage(
        nextEnabled
          ? `${filteredSearchTargetPaths.length}件を検索対象として有効化しました。`
          : `${filteredSearchTargetPaths.length}件を検索対象から除外しました。`,
      );
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダの更新に失敗しました。");
    } finally {
      setIsUpdatingSearchTargets(false);
    }
  }

  async function handleToggleSearchTarget(folderPath: string, isEnabled: boolean): Promise<void> {
    if (isUpdatingSearchTargets) {
      return;
    }
    try {
      setIsUpdatingSearchTargets(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await setSearchTargetEnabled({ folder_path: folderPath, is_enabled: isEnabled });
      setSearchTargets(response.items);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダの更新に失敗しました。");
    } finally {
      setIsUpdatingSearchTargets(false);
    }
  }

  async function handleReindexSelectedSearchTargets(): Promise<void> {
    if (isReindexingSearchTargets || filteredEnabledSearchTargets.length === 0) {
      return;
    }
    try {
      setIsReindexingSearchTargets(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await reindexSearchTargets(filteredEnabledSearchTargets.map((item) => item.full_path));
      await refreshIndexedTargets();
      await refreshSearchTargets();
      await refreshIndexStatus().catch(() => undefined);
      setNoticeMessage(`${response.reindexed_count}件の検索対象フォルダをインデックス取得しました。`);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダのインデックス取得に失敗しました。");
    } finally {
      setIsReindexingSearchTargets(false);
    }
  }

  async function handleDeleteSearchTarget(folderPath: string): Promise<void> {
    if (searchTargetActionPath) {
      return;
    }
    const confirmed = window.confirm(`検索対象フォルダから削除しますか？\n\n${folderPath}`);
    if (!confirmed) {
      return;
    }
    try {
      setSearchTargetActionPath(folderPath);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await deleteSearchTargets([folderPath]);
      await refreshSearchTargets();
      const coverage = await fetchSearchTargetCoverage(folderPath).catch(() => null);
      if (coverage?.is_covered && coverage.covering_path) {
        setNoticeMessage(
          `${response.deleted_count}件の個別設定を削除しました。このフォルダは親フォルダ（${coverage.covering_path}）で引き続き検索対象です。`,
        );
      } else {
        setNoticeMessage(`${response.deleted_count}件の検索対象フォルダを削除しました。`);
      }
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダの削除に失敗しました。");
    } finally {
      setSearchTargetActionPath(null);
    }
  }

  async function handleDeleteSearchTargetIndex(folderPath: string): Promise<void> {
    if (searchTargetActionPath) {
      return;
    }
    const confirmed = window.confirm(`このフォルダ配下のインデックスを削除しますか？\n\n${folderPath}`);
    if (!confirmed) {
      return;
    }
    try {
      setSearchTargetActionPath(folderPath);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await deleteIndexedTargets([folderPath]);
      await refreshIndexedTargets();
      await refreshSearchTargets();
      await refreshIndexStatus().catch(() => undefined);
      setNoticeMessage(`${response.deleted_count}件のインデックスを削除しました。`);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス削除に失敗しました。");
    } finally {
      setSearchTargetActionPath(null);
    }
  }

  async function handleReindexSearchTarget(folderPath: string): Promise<void> {
    if (searchTargetActionPath) {
      return;
    }
    try {
      setSearchTargetActionPath(folderPath);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await reindexSearchTargets([folderPath]);
      await refreshIndexedTargets();
      await refreshSearchTargets();
      await refreshIndexStatus().catch(() => undefined);
      setNoticeMessage(`${response.reindexed_count}件のインデックスを再取得しました。`);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス再取得に失敗しました。");
    } finally {
      setSearchTargetActionPath(null);
    }
  }

  async function handleAddCurrentPathToSearchTarget(): Promise<void> {
    const targetPath = fullPath.trim();
    if (!targetPath || isAddingLaunchPath) {
      return;
    }
    try {
      setIsAddingLaunchPath(true);
      setErrorMessage("");
      setNoticeMessage("");
      const coverage = await fetchSearchTargetCoverage(targetPath);
      if (coverage.is_covered) {
        setNoticeMessage(`このフォルダはすでに検索対象です（親フォルダ: ${coverage.covering_path}）。`);
        return;
      }
      const parsedDepth = Number(indexDepth);
      const response = await addSearchTarget(targetPath, Number.isNaN(parsedDepth) ? 3 : parsedDepth);
      setSearchTargets(response.items);
      setIsCurrentPathCovered(true);
      setIsSearchAllEnabled(false);
      setNoticeMessage(
        searchSource === "web"
          ? "指定したWebページを検索対象に追加し、配下ページをインデックスしました。"
          : "指定したフォルダを検索対象に追加しました。全データベース検索を解除し、このフォルダを対象に検索します。",
      );
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "検索対象フォルダの追加に失敗しました。");
    } finally {
      setIsAddingLaunchPath(false);
    }
  }

  /**
   * 選択したフォルダのインデックスを削除し、一覧・検索結果・通知を更新する。
   */
  async function handleDeleteIndexedTargets(): Promise<void> {
    if (isDeletingTargets || selectedTargetPaths.length === 0) {
      return;
    }

    const confirmed = window.confirm(
      isIndexedWebTargetsPage
        ? "選択したWebページのインデックスを削除します。\n対象URLの検索インデックスと失敗履歴が消えます。続行しますか？"
        : "選択したフォルダのインデックスを削除します。\n対象フォルダ配下の検索インデックスと失敗履歴が消えます。続行しますか？",
    );
    if (!confirmed) {
      return;
    }

    try {
      setIsDeletingTargets(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await deleteIndexedTargets(selectedTargetPaths);
      setResults([]);
      setSelectedTargetPaths([]);
      await refreshIndexedTargets(isIndexedWebTargetsPage ? "web" : "local");
      await refreshIndexStatus().catch(() => undefined);
      setNoticeMessage(`${response.deleted_count}件のインデックス済み${isIndexedWebTargetsPage ? "Webページ" : "フォルダ"}を削除しました。`);
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス済みフォルダの削除に失敗しました。");
    } finally {
      setIsDeletingTargets(false);
    }
  }

  /**
   * 実行中のインデックスへ中止要求を送り、完了するまでステータス表示を追従させる。
   */
  async function handleCancelIndexing(): Promise<void> {
    if (isCancellingIndex || !indexStatus?.is_running) {
      return;
    }

    try {
      setIsCancellingIndex(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await cancelIndexing();
      setIndexStatus(response.status);
      setNoticeMessage("インデックス中止をリクエストしました。停止完了まで少し待つ場合があります。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "インデックス中止に失敗しました。");
    } finally {
      setIsCancellingIndex(false);
    }
  }

  /**
   * 利用者の確認後にインデックス DB を空へ戻し、画面の一覧とステータスも初期状態へそろえる。
   */
  async function handleResetDatabase(): Promise<void> {
    if (isResettingDatabase) {
      return;
    }

    const confirmed = window.confirm(
      "データベースを初期化します。\n検索インデックス、対象キャッシュ、失敗履歴がすべて消えます。続行しますか？",
    );
    if (!confirmed) {
      return;
    }

    try {
      setIsResettingDatabase(true);
      setErrorMessage("");
      setNoticeMessage("");
      const response = await resetDatabase();
      setResults([]);
      setFailedFiles([]);
      setIndexedTargets([]);
      setSearchTargets([]);
      setSelectedTargetPaths([]);
      setIsFailedFilesOpen(false);
      setIndexStatus(response.status);
      setNoticeMessage("データベースを初期化しました。必要なら再検索すると再インデックスされます。");
    } catch (error) {
      setNoticeMessage("");
      setErrorMessage(error instanceof Error ? error.message : "データベースの初期化に失敗しました。");
    } finally {
      setIsResettingDatabase(false);
    }
  }

  /** 検索ルール画面での変更は短い待機後に自動保存する。 */
  useEffect(() => {
    if (!isRuleManagementPage || (!hasUnsavedExcludeKeywords && !hasUnsavedSynonymGroups)) return;
    const timer = window.setTimeout(() => {
      if (hasUnsavedExcludeKeywords) void handleSaveExcludeKeywords();
      if (hasUnsavedSynonymGroups) void handleSaveSynonymGroups();
    }, 120);
    return () => window.clearTimeout(timer);
  }, [excludeKeywordsDraft, synonymGroupsDraft, isRuleManagementPage, hasUnsavedExcludeKeywords, hasUnsavedSynonymGroups]);

  /** Ctrl+Z / Ctrl+Shift+Z（macOS は Command）で検索ルール履歴を操作する。 */
  useEffect(() => {
    if (!isRuleManagementPage) return;
    const handleRuleHistoryShortcut = (event: KeyboardEvent): void => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
      event.preventDefault();
      if (event.shiftKey) {
        handleRedoRuleChange();
      } else {
        handleUndoRuleChange();
      }
    };
    window.addEventListener("keydown", handleRuleHistoryShortcut);
    return () => window.removeEventListener("keydown", handleRuleHistoryShortcut);
  }, [isRuleManagementPage, excludeKeywordsDraft, synonymGroupsDraft]);

  /** 入力欄を操作していないときだけ、A キーで選択中カードの追加画面を開く。 */
  useEffect(() => {
    if (!isRuleManagementPage || isRuleAddModalOpen) return;
    const handleRuleAddShortcut = (event: KeyboardEvent): void => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.key.toLowerCase() !== "a") return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || (target instanceof HTMLElement && target.isContentEditable)) return;
      event.preventDefault();
      handleOpenRuleAddModal(activeRuleKind);
    };
    window.addEventListener("keydown", handleRuleAddShortcut);
    return () => window.removeEventListener("keydown", handleRuleAddShortcut);
  }, [isRuleManagementPage, isRuleAddModalOpen, activeRuleKind]);

  /** 選択中のルールは、入力中以外なら Delete キーでも確認削除できる。 */
  useEffect(() => {
    if (!isRuleManagementPage || !selectedRuleItem || isRuleAddModalOpen) return;
    const handleRuleDeleteShortcut = (event: KeyboardEvent): void => {
      if (event.key !== "Delete") return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement || (target instanceof HTMLElement && target.isContentEditable)) return;
      event.preventDefault();
      handleDeleteRuleItem(selectedRuleItem.kind, selectedRuleItem.item);
    };
    window.addEventListener("keydown", handleRuleDeleteShortcut);
    return () => window.removeEventListener("keydown", handleRuleDeleteShortcut);
  }, [isRuleManagementPage, isRuleAddModalOpen, selectedRuleItem, excludeKeywordsDraft, synonymGroupsDraft]);

  /** アプリ内の表示倍率をブラウザー倍率とは別に保存・反映する。 */
  useEffect(() => {
    document.body.style.zoom = String(uiZoom / 100);
    localStorage.setItem("ui_zoom", String(uiZoom));
  }, [uiZoom]);

  return (
    <div className="page-shell">
      <header className="top-nav">
        <div className="view-switcher" role="tablist" aria-label="ページ切替">
          <button
            className={`secondary-button page-tab ${pageView === "search" ? "active" : ""}`}
            onClick={() => void handleChangePage("search")}
            type="button"
          >
            検索
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "indexed-targets" ? "active" : ""}`}
            onClick={() => void handleChangePage("indexed-targets")}
            type="button"
          >
            インデックス済みフォルダ
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "indexed-web-targets" ? "active" : ""}`}
            onClick={() => void handleChangePage("indexed-web-targets")}
            type="button"
          >
            インデックス済みWebページ
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "search-targets" ? "active" : ""}`}
            onClick={() => void handleChangePage("search-targets")}
            type="button"
          >
            検索対象フォルダ
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "rule-management" ? "active" : ""}`}
            onClick={() => void handleChangePage("rule-management")}
            type="button"
          >
            検索ルール管理
          </button>
          <button
            className={`secondary-button page-tab ${pageView === "launcher" ? "active" : ""}`}
            onClick={() => void handleChangePage("launcher")}
            type="button"
          >
            ランチャー
          </button>
        </div>

        {pageView === "search" ? (
          <SearchBar
            query={query}
            fullPath={fullPath}
            indexDepth={indexDepth}
            searchFilterText={searchFilterText}
            searchSource={searchSource}
            includeGanttTasks={includeGanttTasks}
            searchTarget={searchTarget}
            dateField={dateField}
            sortBy={sortBy}
            sortOrder={sortOrder}
            createdFrom={createdFrom}
            createdTo={createdTo}
            isSearching={isSearching}
            isRegexEnabled={isRegexEnabled}
            isSearchAllEnabled={isSearchAllEnabled}
            indexStatusLabel={indexStatusLabel}
            indexStatusTone={indexStatusTone}
            isCancelDisabled={!indexStatus?.is_running || isCancellingIndex}
            isCancellingIndex={isCancellingIndex || isIndexCancelling}
            onQueryChange={setQuery}
            onFullPathChange={handleFullPathChange}
            onIndexDepthChange={setIndexDepth}
            onSearchFilterTextChange={setSearchFilterText}
            onSearchSourceChange={handleSearchSourceChange}
            onIncludeGanttTasksChange={handleIncludeGanttTasksChange}
            onSearchTargetChange={handleSearchTargetChange}
            onDateFieldChange={setDateField}
            onSortByChange={setSortBy}
            onSortOrderChange={setSortOrder}
            onCreatedFromChange={setCreatedFrom}
            onCreatedToChange={setCreatedTo}
            onApplyDateShortcut={handleApplyDateShortcut}
            onClearCreatedDateFilter={handleClearCreatedDateFilter}
            onCancelIndexing={() => void handleCancelIndexing()}
            onRegexToggle={() => setIsRegexEnabled((value) => !value)}
            onSearchAllToggle={handleToggleSearchAll}
            onPickFolder={() => void handlePickFolder()}
            showSearchTargetHint={isLaunchPathAddable}
            isAddingSearchTarget={isAddingLaunchPath}
            onAddSearchTarget={() => void handleAddCurrentPathToSearchTarget()}
            onSubmit={() => void handleSearch()}
            onToggleMenu={() => setIsMenuOpen((value) => !value)}
          />
        ) : null}
      </header>

      {errorMessage ? <div className="error-banner">{errorMessage}</div> : null}
      {noticeMessage ? <div className="notice-banner">{noticeMessage}</div> : null}

      <main className="content-grid">
        {pageView === "search" ? (
          <section>
            <div className="section-header">
              <h2>Search Results</h2>
              <span>
                {searchFilterText.trim()
                  ? `${visibleResults.length} / ${sortedResults.length}件表示`
                  : `${visibleResults.length} / ${searchTotal}件`}
              </span>
            </div>
            <ResultsList
              items={visibleResults}
              dateField={dateField}
              onResultOpen={handleResultOpen}
              onGanttTaskOpen={handleGanttTaskOpen}
              onResultDelete={handleResultDelete}
              onResultIgnore={handleResultIgnore}
              ignoringResultPath={isIgnoringResultPath}
            />
            {hasMoreResults ? (
              <div className="search-results-footer">
                <div ref={loadMoreTriggerRef} className="search-results-trigger" />
                <button
                  type="button"
                  className="menu-button"
                  onClick={() => currentSearchParams ? void loadMoreResults(currentSearchParams) : undefined}
                  disabled={isLoadingMoreResults}
                >
                  {isLoadingMoreResults ? "続きを読み込み中..." : "次の50件を表示"}
                </button>
              </div>
            ) : null}
          </section>
        ) : pageView === "indexed-targets" || pageView === "search-targets" || pageView === "indexed-web-targets" ? (
          <section className="indexed-targets-panel">
            <div className="indexed-targets-panel-header">
              <div className="section-header">
                <div>
                  <h2>{isSearchTargetsPage ? "検索対象フォルダ" : isIndexedWebTargetsPage ? "インデックス済みWebページ" : "インデックス済みフォルダ"}</h2>
                  <div className="form-help">
                    {isSearchTargetsPage
                      ? "検索対象フォルダを有効/無効で管理し、必要なら再インデックスできます。"
                      : isIndexedWebTargetsPage
                        ? "インデックス済みWebページをURLごとに確認し、必要なページを選択できます。"
                        : "どのフォルダがインデックスされているか確認し、選択して削除できます。"}
                  </div>
                </div>
                <div className="section-header-actions">
                  <span>{isSearchTargetsPage ? filteredSearchTargets.length : filteredTargets.length}件</span>
                  <button className="menu-button" onClick={() => setIsMenuOpen((value) => !value)} type="button" aria-label="設定">
                    <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
                      <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
                    </svg>
                  </button>
                </div>
              </div>

              <div className="indexed-targets-toolbar">
                <div className="indexed-targets-left-controls">
                  <div className="indexed-targets-search-group">
                    <input
                      className="search-input indexed-targets-search"
                      value={filterKeyword}
                      onChange={(event) => setFilterKeyword(event.target.value)}
                      placeholder="キーワードで絞り込み"
                    />
                    <button
                      className="secondary-button indexed-targets-inline-button"
                      onClick={handleClearFilterKeyword}
                      type="button"
                      disabled={!filterKeyword.trim()}
                      aria-label="絞り込みをクリア"
                    >
                      クリア
                    </button>
                    {!isSearchTargetsPage ? (
                      <button
                        className="secondary-button indexed-targets-inline-button"
                        onClick={isIndexedWebTargetsPage ? handleAppendFilterKeywordToWebExcludeKeywords : handleAppendFilterKeywordToExcludeKeywords}
                        type="button"
                        disabled={!filterKeyword.trim()}
                      >
                        {isIndexedWebTargetsPage ? "Web除外キーワードへ追加" : "除外キーワードへ追加"}
                      </button>
                    ) : null}
                  </div>
                  <div className="indexed-targets-action-row">
                    {isSearchTargetsPage ? (
                      <button
                        className="secondary-button indexed-targets-secondary-action"
                        onClick={() => void handleToggleAllSearchTargets()}
                        type="button"
                        disabled={isUpdatingSearchTargets}
                      >
                        {isAllFilteredSearchTargetsSelected ? "選択解除" : "すべて選択"}
                      </button>
                    ) : (
                      <button className="secondary-button indexed-targets-secondary-action" onClick={handleToggleAllIndexedTargets} type="button">
                        {isAllFilteredSelected ? "選択解除" : "すべて選択"}
                      </button>
                    )}
                    <button
                      className="secondary-button indexed-targets-secondary-action"
                      onClick={() => void (isSearchTargetsPage ? refreshSearchTargets() : refreshIndexedTargets(isIndexedWebTargetsPage ? "web" : "local"))}
                      type="button"
                      disabled={isLoadingTargets}
                    >
                      {isLoadingTargets ? "再読込中..." : "再読込"}
                    </button>
                    {isSearchTargetsPage ? (
                      <button
                        className="secondary-button indexed-targets-primary-action"
                        onClick={() => void handleReindexSelectedSearchTargets()}
                        type="button"
                        disabled={filteredEnabledSearchTargets.length === 0 || isReindexingSearchTargets}
                      >
                        {isReindexingSearchTargets ? "取得中..." : "インデックス取得"}
                      </button>
                    ) : (
                      <button
                        className="secondary-button danger indexed-targets-primary-action"
                        onClick={() => void handleDeleteIndexedTargets()}
                        type="button"
                        disabled={selectedTargetPaths.length === 0 || isDeletingTargets}
                      >
                        {isDeletingTargets ? "削除中..." : isIndexedWebTargetsPage ? "選択したWebページのインデックスを削除" : "選択したフォルダのインデックスを削除"}
                      </button>
                    )}
                  </div>
                </div>
                {!isSearchTargetsPage ? (
                  <div className="indexed-targets-search-group indexed-targets-hide-group">
                    <textarea
                      className="indexed-targets-hide-box"
                      value={hideKeyword}
                      onChange={(event) => setHideKeyword(event.target.value)}
                      placeholder="必要フォルダを隠すキーワード"
                      rows={4}
                    />
                    <button
                      className="secondary-button indexed-targets-inline-button"
                      onClick={handleClearHideKeyword}
                      type="button"
                      disabled={!hideKeyword.trim()}
                      aria-label="非表示をクリア"
                    >
                      クリア
                    </button>
                  </div>
                ) : null}
              </div>

              <div className="form-help indexed-targets-selection-status">
                {isSearchTargetsPage
                  ? `対象中: ${filteredEnabledSearchTargets.length}件 / 全${filteredSearchTargets.length}件`
                  : normalizedFilterKeyword || hiddenKeywordList.length > 0
                    ? `絞り込み: ${normalizedFilterKeyword || "なし"} / 非表示: ${hiddenKeywordList.length}件 / 選択中: ${selectedTargetPaths.length}件`
                    : `選択中: ${selectedTargetPaths.length}件`}
              </div>
            </div>

            <div className="indexed-targets-list">
              {isSearchTargetsPage ? (
                filteredSearchTargets.length === 0 ? (
                  <div className="empty-panel">
                    <div>{searchTargets.length === 0 ? "まだ検索対象フォルダはありません。" : "条件に一致するフォルダはありません。"}</div>
                  </div>
                ) : (
                  filteredSearchTargets.map((item) => (
                    <label className="target-list-item" key={item.full_path}>
                      <div className="target-list-main target-list-main-compact">
                        <input
                          checked={item.is_enabled}
                          onChange={(event) => void handleToggleSearchTarget(item.full_path, event.target.checked)}
                          type="checkbox"
                          disabled={isUpdatingSearchTargets}
                        />
                        <div className="target-list-content target-list-content-compact">
                          <div className="target-list-path">{item.full_path}</div>
                          <div className="target-list-meta">
                            <span>状態: {item.is_enabled ? "対象" : "対象外"}</span>
                            <span>ファイル数: {item.indexed_file_count}</span>
                            <span>最終取得: {item.last_indexed_at ? new Date(item.last_indexed_at).toLocaleString() : "-"}</span>
                          </div>
                        </div>
                        <div className="target-list-actions">
                          <button
                            className="secondary-button small-btn"
                            onClick={(event) => {
                              event.preventDefault();
                              void handleDeleteSearchTarget(item.full_path);
                            }}
                            type="button"
                            disabled={Boolean(searchTargetActionPath)}
                          >
                            削除
                          </button>
                          <button
                            className="secondary-button small-btn"
                            onClick={(event) => {
                              event.preventDefault();
                              void handleDeleteSearchTargetIndex(item.full_path);
                            }}
                            type="button"
                            disabled={Boolean(searchTargetActionPath)}
                          >
                            インデックス削除
                          </button>
                          <button
                            className="secondary-button small-btn"
                            onClick={(event) => {
                              event.preventDefault();
                              void handleReindexSearchTarget(item.full_path);
                            }}
                            type="button"
                            disabled={Boolean(searchTargetActionPath)}
                          >
                            インデックス再取得
                          </button>
                        </div>
                      </div>
                    </label>
                  ))
                )
              ) : (
                filteredTargets.length === 0 ? (
                      <div className="empty-panel">
                    <div>
                      {indexedTargets.length === 0
                        ? isIndexedWebTargetsPage
                          ? "まだインデックス済みWebページはありません。"
                          : "まだインデックス済みフォルダはありません。"
                        : isIndexedWebTargetsPage
                          ? "条件に一致するWebページはありません。"
                          : "条件に一致するフォルダはありません。"}
                    </div>
                  </div>
                ) : (
                  filteredTargets.map((item) => (
                    <label className="target-list-item" key={item.full_path}>
                      <div className="target-list-main">
                        <input
                          checked={selectedTargetPathSet.has(item.full_path)}
                          onChange={() => handleToggleIndexedTarget(item.full_path)}
                          type="checkbox"
                        />
                        <div className="target-list-content">
                          <div className="target-list-path">{item.full_path}</div>
                          <div className="target-list-meta">
                            {isIndexedWebTargetsPage ? <span>URL: {item.full_path}</span> : null}
                            <span>{isIndexedWebTargetsPage ? "ページ数" : "ファイル数"}: {item.indexed_file_count}</span>
                            <span>
                              最終取得: {item.last_indexed_at ? new Date(item.last_indexed_at).toLocaleString() : "-"}
                            </span>
                          </div>
                        </div>
                        <div className="target-list-actions">
                          <button
                            className="secondary-button small-btn"
                            onClick={(event) => {
                              event.preventDefault();
                              void handleOpenIndexedTargetLocation(item.full_path);
                            }}
                            type="button"
                            disabled={openingIndexedTargetPath === item.full_path}
                          >
                            {isIndexedWebTargetsPage
                              ? "Webページを開く"
                              : openingIndexedTargetPath === item.full_path
                                ? "開いています..."
                                : openLocationLabel}
                          </button>
                        </div>
                      </div>
                    </label>
                  ))
                )
              )}
            </div>
          </section>
        ) : isSchedulerPage ? (
          <section className="scheduler-panel">
            <div className="indexed-targets-panel-header">
              <div className="section-header">
                <div>
                  <h2>スケジューラー</h2>
                  <div className="form-help">
                    指定した開始日時になると、登録済みフォルダを別プロセスで順次インデックスします。
                  </div>
                </div>
                <div className="section-header-actions">
                  <span>{schedulerState?.status ?? "idle"}</span>
                  <button className="menu-button" onClick={() => setIsMenuOpen((value) => !value)} type="button" aria-label="設定">
                    <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
                      <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <div className="scheduler-card">
              <label className="form-help" htmlFor="scheduler-start-at">
                開始日時
              </label>
              <input
                id="scheduler-start-at"
                className="search-input"
                value={schedulerStartAt}
                onChange={(event) => setSchedulerStartAt(event.target.value)}
                type="datetime-local"
              />

              <div className="scheduler-path-editor">
                <label className="form-help" htmlFor="scheduler-path-input">
                  対象パス
                </label>
                <div className="scheduler-path-actions">
                  <input
                    id="scheduler-path-input"
                    className="search-input"
                    value={schedulerPathDraft}
                    onChange={(event) => setSchedulerPathDraft(event.target.value)}
                    placeholder="/Users/name/Documents/project-a"
                  />
                  <button className="secondary-button" onClick={() => handleAddSchedulerPath(schedulerPathDraft)} type="button">
                    フォルダを追加
                  </button>
                  <button className="secondary-button" onClick={() => void handlePickSchedulerFolder()} type="button">
                    フォルダ選択
                  </button>
                </div>
                <div className="scheduler-path-list">
                  {schedulerPaths.length === 0 ? (
                    <div className="form-help">まだ対象フォルダはありません。</div>
                  ) : (
                    schedulerPaths.map((path) => (
                      <div className="scheduler-path-item" key={path}>
                        <div className="scheduler-path-text">{path}</div>
                        <button
                          className="secondary-button"
                          onClick={() => setSchedulerPaths((current) => current.filter((item) => item !== path))}
                          type="button"
                        >
                          削除
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="scheduler-actions">
                <button className="secondary-button settings-save-button" onClick={() => void handleStartScheduler()} type="button" disabled={isStartingScheduler}>
                  {isStartingScheduler ? "開始中..." : "スケジュール開始"}
                </button>
              </div>
            </div>

            <div className="status-card scheduler-status-card">
              <div>状態: {schedulerState?.status ?? "-"}</div>
              <div>開始予定: {schedulerState?.start_at ? new Date(schedulerState.start_at).toLocaleString() : "-"}</div>
              <div>最終開始: {schedulerState?.last_started_at ? new Date(schedulerState.last_started_at).toLocaleString() : "-"}</div>
              <div>最終完了: {schedulerState?.last_finished_at ? new Date(schedulerState.last_finished_at).toLocaleString() : "-"}</div>
              <div>処理中パス: {schedulerState?.current_path ?? "-"}</div>
              <div>最終エラー: {schedulerState?.last_error ?? "-"}</div>
            </div>

            <div className="scheduler-log-panel">
              <div className="section-header">
                <h3>ログ</h3>
                <span>{schedulerState?.logs.length ?? 0}件</span>
              </div>
              <div className="scheduler-log-list">
                {schedulerState?.logs.length ? (
                  schedulerState.logs.map((item, index) => (
                    <div className={`scheduler-log-item ${item.level}`} key={`${item.logged_at}-${index}`}>
                      <div className="scheduler-log-meta">
                        <span>{new Date(item.logged_at).toLocaleString()}</span>
                        <span>{item.level}</span>
                      </div>
                      <div>{item.message}</div>
                      {item.folder_path ? <div className="scheduler-log-path">{item.folder_path}</div> : null}
                    </div>
                  ))
                ) : (
                  <div className="form-help">ログはまだありません。</div>
                )}
              </div>
            </div>
          </section>
        ) : isRuleManagementPage ? (
          <section className="rule-management-panel" onClick={() => setRuleContextMenu(null)}>
            <div className="section-header">
              <div>
                <h2>検索ルール管理</h2>
                <div className="form-help">行全体をダブルクリックで編集。ドラッグで並べ替え、右クリックで削除できます。</div>
              </div>
              <div className="section-header-actions">
                <button className="secondary-button" onClick={handleUndoRuleChange} type="button">元に戻す</button>
                <button className="secondary-button" onClick={handleRedoRuleChange} type="button">やり直す</button>
                <button className="secondary-button" onClick={() => void handleChangePage("search")} type="button">検索へ戻る</button>
                <button className="menu-button" onClick={() => setIsMenuOpen((value) => !value)} type="button" aria-label="設定">☰</button>
              </div>
            </div>

            <div className="rule-management-grid">
              <div className={`rule-list-card ${activeRuleKind === "exclude" ? "active" : ""}`} onClick={() => setActiveRuleKind("exclude")}>
                <div className="section-header">
                  <h3>除外キーワード</h3>
                  <div className="rule-card-header-actions"><span>{filteredExcludeKeywordEntries.length}件</span><button className="secondary-button" onClick={() => handleOpenRuleAddModal("exclude")} type="button">追加</button></div>
                </div>
                <input className="rule-card-search" value={excludeRuleFilterText} onChange={(event) => setExcludeRuleFilterText(event.target.value)} placeholder="除外キーワードを検索" aria-label="除外キーワードを検索" />
                <div className="rule-list">
                  {filteredExcludeKeywordEntries.map((item) => (
                    <div
                      className={`rule-list-item ${selectedRuleItem?.kind === "exclude" && selectedRuleItem.item === item ? "selected" : ""}`}
                      draggable
                      key={item}
                      onDoubleClick={() => { if (editingExcludeKeyword !== item) { setEditingExcludeKeyword(item); setEditingExcludeKeywordValue(item); } }}
                      onClick={(event) => { event.stopPropagation(); setActiveRuleKind("exclude"); setSelectedRuleItem({ kind: "exclude", item }); }}
                      onContextMenuCapture={(event) => { event.preventDefault(); setRuleContextMenu({ kind: "exclude", item, x: event.clientX, y: event.clientY }); }}
                      onDragStart={() => { setActiveRuleKind("exclude"); setSelectedRuleItem({ kind: "exclude", item }); setDraggedRule({ kind: "exclude", item }); }}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={() => { if (draggedRule?.kind === "exclude") handleMoveRuleItem("exclude", draggedRule.item, item); setDraggedRule(null); }}
                    >
                      {editingExcludeKeyword === item ? (
                        <input
                          autoFocus
                          className="rule-inline-input"
                          value={editingExcludeKeywordValue}
                          onChange={(event) => setEditingExcludeKeywordValue(event.target.value)}
                          onBlur={() => handleUpdateExcludeKeyword(item)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") event.currentTarget.blur();
                          }}
                        />
                      ) : <code title="ダブルクリックで編集">{item}</code>}
                      <button
                        className="secondary-button"
                        onClick={(event) => { event.stopPropagation(); handleDeleteRuleItem("exclude", item); }}
                        type="button"
                      >削除</button>
                    </div>
                  ))}
                  {filteredExcludeKeywordEntries.length === 0 ? <div className="form-help">一致する除外キーワードはありません。</div> : null}
                </div>
                <div className={`settings-save-status ${hasUnsavedExcludeKeywords ? "dirty" : "saved"}`}>{isSavingExcludeKeywords ? "自動保存中..." : hasUnsavedExcludeKeywords ? "自動保存待ち" : "自動保存済み"}</div>
              </div>

              <div className={`rule-list-card ${activeRuleKind === "synonym" ? "active" : ""}`} onClick={() => setActiveRuleKind("synonym")}>
                <div className="section-header">
                  <h3>同義語リスト</h3>
                  <div className="rule-card-header-actions"><span>{filteredSynonymGroupEntries.length}件</span><button className="secondary-button" onClick={() => handleOpenRuleAddModal("synonym")} type="button">追加</button></div>
                </div>
                <input className="rule-card-search" value={synonymRuleFilterText} onChange={(event) => setSynonymRuleFilterText(event.target.value)} placeholder="同義語を検索" aria-label="同義語を検索" />
                <div className="rule-list">
                  {filteredSynonymGroupEntries.map((item) => {
                    const conflicts = item.split(",").filter((token) => excludeKeywordSet.has(token.toLowerCase()));
                    return (
                      <div
                        className={`rule-list-item ${selectedRuleItem?.kind === "synonym" && selectedRuleItem.item === item ? "selected" : ""}`}
                        draggable
                        key={item}
                        onDoubleClick={() => { if (editingSynonymGroup !== item) { setEditingSynonymGroup(item); setEditingSynonymGroupValue(item); } }}
                        onClick={(event) => { event.stopPropagation(); setActiveRuleKind("synonym"); setSelectedRuleItem({ kind: "synonym", item }); }}
                        onContextMenuCapture={(event) => { event.preventDefault(); setRuleContextMenu({ kind: "synonym", item, x: event.clientX, y: event.clientY }); }}
                        onDragStart={() => { setActiveRuleKind("synonym"); setSelectedRuleItem({ kind: "synonym", item }); setDraggedRule({ kind: "synonym", item }); }}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => { if (draggedRule?.kind === "synonym") handleMoveRuleItem("synonym", draggedRule.item, item); setDraggedRule(null); }}
                      >
                        <div>
                          {editingSynonymGroup === item ? (
                            <input
                              autoFocus
                              className="rule-inline-input"
                              value={editingSynonymGroupValue}
                              onChange={(event) => setEditingSynonymGroupValue(event.target.value)}
                              onBlur={() => handleUpdateSynonymGroup(item)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") event.currentTarget.blur();
                              }}
                            />
                          ) : <code title="ダブルクリックで編集">{item}</code>}
                          {conflicts.length ? <div className="rule-conflict">除外リストに登録済み: {conflicts.join(", ")}</div> : null}
                        </div>
                        <button
                          className="secondary-button"
                          onClick={(event) => { event.stopPropagation(); handleDeleteRuleItem("synonym", item); }}
                          type="button"
                        >削除</button>
                      </div>
                    );
                  })}
                  {filteredSynonymGroupEntries.length === 0 ? <div className="form-help">一致する同義語グループはありません。</div> : null}
                </div>
                <div className={`settings-save-status ${hasUnsavedSynonymGroups ? "dirty" : "saved"}`}>{isSavingSynonymGroups ? "自動保存中..." : hasUnsavedSynonymGroups ? "自動保存待ち" : "自動保存済み"}</div>
              </div>
            </div>
            {ruleContextMenu ? (
              <div
                className="rule-context-menu"
                style={{ left: ruleContextMenu.x, top: ruleContextMenu.y }}
                onClick={(event) => event.stopPropagation()}
              >
                <button type="button" onClick={() => handleDeleteRuleItem(ruleContextMenu.kind, ruleContextMenu.item)}>削除</button>
              </div>
            ) : null}
            {isRuleAddModalOpen ? (
              <div className="rule-add-modal-backdrop" role="presentation" onMouseDown={() => setIsRuleAddModalOpen(false)}>
                <div className="rule-add-modal" role="dialog" aria-modal="true" aria-label={`${ruleAddKind === "exclude" ? "除外キーワード" : "同義語"}を追加`} onMouseDown={(event) => event.stopPropagation()}>
                  <h3>{ruleAddKind === "exclude" ? "除外キーワードを追加" : "同義語を追加"}</h3>
                  <input
                    autoFocus
                    value={ruleAddKind === "exclude" ? newExcludeKeyword : newSynonymGroup}
                    onChange={(event) => ruleAddKind === "exclude" ? setNewExcludeKeyword(event.target.value) : setNewSynonymGroup(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.nativeEvent.isComposing) handleSubmitRuleAdd();
                    }}
                    placeholder={ruleAddKind === "exclude" ? "例: node_modules" : "例: スマートフォン,スマホ"}
                  />
                  <div className="rule-add-modal-actions">
                    <button className="secondary-button" onClick={() => setIsRuleAddModalOpen(false)} type="button">キャンセル</button>
                    <button className="secondary-button" onClick={handleSubmitRuleAdd} type="button">追加する</button>
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        ) : isLauncherPage ? (
          <section className="launcher-panel">
            <div className="indexed-targets-panel-header">
              <div className="section-header">
                <div>
                  <h2>ランチャー</h2>
                  <div className="form-help">
                    デスクトップランチャーの起動状態、停止・再起動、ログを確認できます。
                  </div>
                </div>
                <div className="section-header-actions">
                  <span>{launcherState?.status ?? "unknown"}</span>
                  <button className="menu-button" onClick={() => setIsMenuOpen((value) => !value)} type="button" aria-label="設定">
                    <svg fill="currentColor" viewBox="0 0 24 24" width="24" height="24">
                      <path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z"></path>
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <div className="launcher-control-grid">
              <div className="status-card launcher-status-card">
                <div>状態: {launcherState?.status ?? "-"}</div>
                <div>PID: {launcherState?.pid ?? "-"}</div>
                <div>終了コード: {launcherState?.returncode ?? "-"}</div>
                <div>自動起動: {launcherState?.autostart ? "有効" : "無効"}</div>
                <div>ログ: {launcherState?.log_path ?? "-"}</div>
              </div>

              <div className="scheduler-card launcher-actions-card">
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleLauncherAction("start")}
                  type="button"
                  disabled={isLauncherActionRunning || launcherState?.is_running}
                >
                  起動
                </button>
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleLauncherAction("restart")}
                  type="button"
                  disabled={isLauncherActionRunning}
                >
                  再起動
                </button>
                <button
                  className="secondary-button danger settings-save-button"
                  onClick={() => void handleLauncherAction("stop")}
                  type="button"
                  disabled={isLauncherActionRunning || !launcherState?.is_running}
                >
                  停止
                </button>
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void refreshLauncherState()}
                  type="button"
                  disabled={isLauncherActionRunning}
                >
                  再読込
                </button>
              </div>
            </div>

            <div className="scheduler-log-panel launcher-log-panel">
              <div className="section-header">
                <h3>ログ</h3>
                <span>{launcherState?.logs.length ?? 0}行</span>
              </div>
              <pre className="launcher-log-output">
                {launcherState?.logs.length ? launcherState.logs.join("\n") : "ログはまだありません。"}
              </pre>
            </div>
          </section>
        ) : null}

        <aside className={`settings-drawer ${isMenuOpen ? "open" : ""}`} aria-hidden={!isMenuOpen}>
          <div className="settings-panel">
            <div className="settings-header">
              <h2>設定</h2>
              <button className="secondary-button" onClick={() => setIsMenuOpen(false)} type="button">
                閉じる
              </button>
            </div>

            <div className="settings-action-row">
              <button className="secondary-button" onClick={handleOpenSchedulerPage} type="button">
                スケジューラー
              </button>
              <div className="form-help">複数フォルダと開始日時を指定し、別プロセスで順次インデックスできます。</div>
            </div>

            <div className="settings-action-row">
              <button className="secondary-button" onClick={() => void handleChangePage("launcher")} type="button">
                ランチャー
              </button>
              <div className="form-help">デスクトップランチャーの起動・停止・再起動とログ確認を行います。</div>
            </div>

            <div className="zoom-settings">
              <label className="form-help" htmlFor="ui-zoom">表示倍率 <strong>{uiZoom}%</strong></label>
              <div className="zoom-settings-controls">
                <input id="ui-zoom" type="range" min="75" max="125" step="5" value={uiZoom} onChange={(event) => setUiZoom(Number(event.target.value))} />
                <button className="secondary-button" onClick={() => setUiZoom(100)} type="button">100%に戻す</button>
              </div>
              <div className="form-help">このアプリの表示だけを変更します。ブラウザーのズーム設定には影響しません。</div>
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
                  onClick={() => setIsIndexExtensionMenuOpen((value) => !value)}
                  type="button"
                >
                  対象拡張子
                </button>
                {isIndexExtensionMenuOpen ? (
                  <div className="extension-menu">
                    <div className="extension-menu-actions">
                      <button className="secondary-button" onClick={setAllIndexExtensions} type="button">
                        すべて選択
                      </button>
                      <button className="secondary-button" onClick={clearAllIndexExtensions} type="button">
                        全解除
                      </button>
                      <button
                        className="secondary-button settings-save-button"
                        onClick={() => void handleSaveIndexExtensions()}
                        type="button"
                        disabled={!hasUnsavedIndexExtensions || isSavingIndexExtensions}
                      >
                        {isSavingIndexExtensions ? "保存中..." : "保存"}
                      </button>
                    </div>

                    <div className="extension-add-grid">
                      <div className="extension-add-card">
                        <div className="form-help">本文を index 化する追加拡張子</div>
                        <div className="extension-add-row">
                          <input
                            className="extension-add-input"
                            value={newContentExtension}
                            onChange={(event) => setNewContentExtension(event.target.value)}
                            placeholder=".py / .dat"
                          />
                          <button className="secondary-button" onClick={() => handleAddCustomExtension("content")} type="button">
                            拡張子を追加
                          </button>
                        </div>
                      </div>

                      <div className="extension-add-card">
                        <div className="form-help">ファイル名だけを index 化する追加拡張子</div>
                        <div className="extension-add-row">
                          <input
                            className="extension-add-input"
                            value={newFilenameExtension}
                            onChange={(event) => setNewFilenameExtension(event.target.value)}
                            placeholder=".cae / .mesh"
                          />
                          <button className="secondary-button" onClick={() => handleAddCustomExtension("filename")} type="button">
                            拡張子を追加
                          </button>
                        </div>
                      </div>
                    </div>

                    <div className="extension-group">
                      <div className="form-help">標準拡張子</div>
                      {DEFAULT_INDEX_EXTENSIONS.map((extension) => (
                        <label className="extension-option" key={extension}>
                          <input
                            checked={selectedIndexExtensions.includes(extension)}
                            onChange={() => toggleIndexExtension(extension)}
                            type="checkbox"
                          />
                          <span>{extension}</span>
                        </label>
                      ))}
                    </div>

                    {customContentExtensions.length > 0 ? (
                      <div className="extension-group">
                        <div className="form-help">追加した本文 index 用拡張子</div>
                        {customContentExtensions.map((extension) => (
                          <div className="extension-custom-row" key={extension}>
                            <label className="extension-option">
                              <input
                                checked={selectedIndexExtensions.includes(extension)}
                                onChange={() => toggleIndexExtension(extension)}
                                type="checkbox"
                              />
                              <span>{extension}</span>
                            </label>
                            <button
                              className="secondary-button extension-remove-button"
                              onClick={() => handleRemoveCustomExtension(extension, "content")}
                              type="button"
                            >
                              削除
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}

                    {customFilenameExtensions.length > 0 ? (
                      <div className="extension-group">
                        <div className="form-help">追加したファイル名のみ拡張子</div>
                        {customFilenameExtensions.map((extension) => (
                          <div className="extension-custom-row" key={extension}>
                            <label className="extension-option">
                              <input
                                checked={selectedIndexExtensions.includes(extension)}
                                onChange={() => toggleIndexExtension(extension)}
                                type="checkbox"
                              />
                              <span>{extension}</span>
                            </label>
                            <button
                              className="secondary-button extension-remove-button"
                              onClick={() => handleRemoveCustomExtension(extension, "filename")}
                              type="button"
                            >
                              削除
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className={`settings-save-status ${hasUnsavedIndexExtensions ? "dirty" : "saved"}`}>
                  {hasUnsavedIndexExtensions ? "未保存の変更があります" : "保存済み"}
                </div>
                <div className="form-help">
                  インデックス作成対象です。追加拡張子は backend のテキストファイルへ保存され、検索フィルタ側の拡張子選択とは独立しています。
                </div>
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

              <label className="form-help" htmlFor="web-exclude-keywords">
                Web除外キーワード
              </label>
              <textarea
                id="web-exclude-keywords"
                className="settings-textarea"
                value={webExcludeKeywordsDraft}
                onChange={(event) => setWebExcludeKeywordsDraft(event.target.value)}
                placeholder="/tag/&#10;?replytocom=&#10;/login"
                rows={8}
              />
              <div className="settings-action-row">
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleSaveWebExcludeKeywords()}
                  type="button"
                  disabled={!hasUnsavedWebExcludeKeywords || isSavingWebExcludeKeywords}
                >
                  {isSavingWebExcludeKeywords ? "保存中..." : "保存"}
                </button>
                <div className={`settings-save-status ${hasUnsavedWebExcludeKeywords ? "dirty" : "saved"}`}>
                  {hasUnsavedWebExcludeKeywords ? "未保存の変更があります" : "保存済み"}
                </div>
              </div>
              <div className="form-help">
                WebページのURLに含まれる文字列を1行1キーワードで指定します。ローカルフォルダ用の除外キーワードとは独立しています。
              </div>

              <label className="form-help" htmlFor="obsidian-sidebar-explorer-data-path">
                Obsidian sidebar-explorer data.json パス
              </label>
              <textarea
                id="obsidian-sidebar-explorer-data-path"
                className="settings-textarea"
                value={obsidianSidebarExplorerDataPathDraft}
                onChange={(event) => setObsidianSidebarExplorerDataPathDraft(event.target.value)}
                placeholder="/Users/name/Vault/.obsidian/plugins/obsidian-sidebar-explorer/data.json"
                rows={3}
              />
              <div className="settings-action-row">
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleSaveObsidianSidebarExplorerDataPath()}
                  type="button"
                  disabled={!hasUnsavedObsidianSidebarExplorerDataPath || isSavingObsidianSidebarExplorerDataPath}
                >
                  {isSavingObsidianSidebarExplorerDataPath ? "保存中..." : "保存"}
                </button>
                <div className={`settings-save-status ${hasUnsavedObsidianSidebarExplorerDataPath ? "dirty" : "saved"}`}>
                  {hasUnsavedObsidianSidebarExplorerDataPath ? "未保存の変更があります" : "保存済み"}
                </div>
              </div>
              <div className="form-help">
                環境ごとに異なる Obsidian Vault の sidebar-explorer `data.json` を指定します。未設定なら既定パスを使います。
              </div>

              <label className="form-help" htmlFor="gantt-parent">
                gantt parent
              </label>
              <input
                id="gantt-parent"
                value={ganttParentDraft}
                onChange={(event) => setGanttParentDraft(event.target.value)}
                type="number"
                min={0}
              />
              <div className="settings-action-row">
                <button
                  className="secondary-button settings-save-button"
                  onClick={() => void handleSaveGanttParent()}
                  type="button"
                  disabled={!hasUnsavedGanttParent || isSavingGanttParent}
                >
                  {isSavingGanttParent ? "保存中..." : "保存"}
                </button>
                <div className={`settings-save-status ${hasUnsavedGanttParent ? "dirty" : "saved"}`}>
                  {hasUnsavedGanttParent ? "未保存の変更があります" : "保存済み"}
                </div>
              </div>
              <div className="form-help">
                ランチャーのメモ画面から gantt タスクを追加するときの親タスク ID です。
              </div>

              <div className="extension-panel">
                <button
                  className="secondary-button danger"
                  onClick={() => void handleResetDatabase()}
                  type="button"
                  disabled={isResettingDatabase}
                >
                  {isResettingDatabase ? "初期化中..." : "データベースを初期化"}
                </button>
                <div className="form-help">
                  検索インデックス、対象キャッシュ、失敗履歴を空に戻します。次回検索時に必要な範囲だけ再作成します。
                </div>
              </div>

              <hr className="divider" />

              <div className="status-card">
                <div>最終完了: {indexStatus?.last_finished_at ? new Date(indexStatus.last_finished_at).toLocaleString() : "-"}</div>
                <div>総ファイル数: {indexStatus?.total_files ?? 0}</div>
                <div>エラー件数: {indexStatus?.error_count ?? 0}</div>
                <div>状態: {indexStatusLabel}</div>
              </div>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}

export default App;
