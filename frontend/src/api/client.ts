import type {
  AppSettings,
  FailedFileListResponse,
  IndexedTargetListResponse,
  IndexStatus,
  SearchTargetListResponse,
  SearchTargetCoverage,
  SchedulerSettings,
  SearchResponse,
} from "../types";

const API_BASE = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL ?? "";
const SEARCH_PAGE_SIZE = 1000;

type ApiErrorDetail = {
  msg?: string;
};

function getErrorMessage(raw: string): string {
  try {
    const parsed = JSON.parse(raw) as { detail?: string | ApiErrorDetail[] };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
    if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
      return parsed.detail.map((item) => item.msg ?? "入力内容を確認してください。").join(" ");
    }
  } catch {
    return raw || "Request failed.";
  }
  return raw || "Request failed.";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!response.ok) {
    throw new Error(getErrorMessage(await response.text()));
  }
  return (await response.json()) as T;
}

export async function fetchIndexStatus(): Promise<IndexStatus> {
  return request<IndexStatus>("/api/index/status");
}

export async function fetchAppSettings(): Promise<AppSettings> {
  return request<AppSettings>("/api/index/settings");
}

export async function fetchSchedulerSettings(): Promise<SchedulerSettings> {
  return request<SchedulerSettings>("/api/index/scheduler");
}

export async function startScheduler(payload: { paths: string[]; start_at: string }): Promise<SchedulerSettings> {
  return request<SchedulerSettings>("/api/index/scheduler/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAppSettings(payload: {
  exclude_keywords?: string;
  hidden_indexed_targets?: string;
  synonym_groups?: string;
  index_selected_extensions?: string;
  custom_content_extensions?: string;
  custom_filename_extensions?: string;
}): Promise<AppSettings> {
  return request<AppSettings>("/api/index/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function fetchFailedFiles(): Promise<FailedFileListResponse> {
  return request<FailedFileListResponse>("/api/index/failed-files");
}

export async function fetchIndexedTargets(): Promise<IndexedTargetListResponse> {
  return request<IndexedTargetListResponse>("/api/index/targets");
}

export async function deleteIndexedTargets(folderPaths: string[]): Promise<{ deleted_count: number }> {
  return request<{ deleted_count: number }>("/api/index/targets", {
    method: "DELETE",
    body: JSON.stringify({ folder_paths: folderPaths }),
  });
}

export async function fetchSearchTargets(): Promise<SearchTargetListResponse> {
  return request<SearchTargetListResponse>("/api/index/search-targets");
}

export async function fetchSearchTargetCoverage(folderPath: string): Promise<SearchTargetCoverage> {
  const query = new URLSearchParams({ folder_path: folderPath });
  return request<SearchTargetCoverage>(`/api/index/search-targets/coverage?${query.toString()}`);
}

export async function setSearchTargetEnabled(payload: {
  folder_path: string;
  is_enabled: boolean;
}): Promise<SearchTargetListResponse> {
  return request<SearchTargetListResponse>("/api/index/search-targets", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function addSearchTarget(folderPath: string): Promise<SearchTargetListResponse> {
  return request<SearchTargetListResponse>("/api/index/search-targets", {
    method: "POST",
    body: JSON.stringify({ folder_path: folderPath }),
  });
}

export async function deleteSearchTargets(folderPaths: string[]): Promise<{ deleted_count: number }> {
  return request<{ deleted_count: number }>("/api/index/search-targets", {
    method: "DELETE",
    body: JSON.stringify({ folder_paths: folderPaths }),
  });
}

export async function reindexSearchTargets(folderPaths: string[]): Promise<{ reindexed_count: number }> {
  return request<{ reindexed_count: number }>("/api/index/search-targets/reindex", {
    method: "POST",
    body: JSON.stringify({ folder_paths: folderPaths }),
  });
}

export async function resetDatabase(): Promise<{ message: string; status: IndexStatus }> {
  return request<{ message: string; status: IndexStatus }>("/api/index/reset", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function cancelIndexing(): Promise<{ message: string; status: IndexStatus }> {
  return request<{ message: string; status: IndexStatus }>("/api/index/cancel", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function pickFolder(): Promise<{ full_path: string }> {
  return request<{ full_path: string }>("/api/folders/pick", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function search(params: {
  q: string;
  full_path: string;
  search_all_enabled?: boolean;
  skip_refresh?: boolean;
  index_depth: number;
  refresh_window_minutes: number;
  regex_enabled?: boolean;
  search_target?: "all" | "body" | "filename" | "folder" | "filename_and_folder";
  index_types?: string;
  types?: string;
  date_field?: "created" | "modified";
  sort_by?: "created" | "modified" | "click_count";
  sort_order?: "asc" | "desc";
  created_from?: string;
  created_to?: string;
}, options?: {
  onProgress?: (response: SearchResponse) => void;
}): Promise<SearchResponse> {
  const items = [];
  let total = 0;
  let offset = 0;
  let usedExistingIndex = false;
  let backgroundRefreshScheduled = false;

  while (true) {
    const response = await request<SearchResponse>("/api/search", {
      method: "POST",
      body: JSON.stringify({
        ...params,
        limit: SEARCH_PAGE_SIZE,
        offset,
      }),
    });

    if (offset === 0) {
      total = response.total;
      usedExistingIndex = response.used_existing_index;
      backgroundRefreshScheduled = response.background_refresh_scheduled;
    }

    items.push(...response.items);
    options?.onProgress?.({
      total,
      items: [...items],
      used_existing_index: usedExistingIndex,
      background_refresh_scheduled: backgroundRefreshScheduled,
    });

    if (response.items.length === 0 || items.length >= response.total) {
      return {
        total,
        items,
        used_existing_index: usedExistingIndex,
        background_refresh_scheduled: backgroundRefreshScheduled,
      };
    }

    offset += response.items.length;
  }
}

export async function recordSearchClick(fileId: number): Promise<{ file_id: number; click_count: number }> {
  return request<{ file_id: number; click_count: number }>("/api/search/click", {
    method: "POST",
    keepalive: true,
    body: JSON.stringify({ file_id: fileId }),
  });
}

export async function deleteFile(fileId: number): Promise<{ status: string; file_id: number }> {
  return request<{ status: string; file_id: number }>(`/api/files/${fileId}`, {
    method: "DELETE",
  });
}

export async function openFileLocation(path: string): Promise<{ status: string }> {
  return request<{ status: string }>("/api/files/open-location", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}
