export type SearchResult = {
  file_id: number;
  result_kind: "file" | "folder";
  target_path: string;
  file_name: string;
  full_path: string;
  file_ext: string;
  created_at: string;
  mtime: string;
  click_count: number;
  snippet: string;
};

export type SearchResponse = {
  total: number;
  items: SearchResult[];
  used_existing_index: boolean;
  background_refresh_scheduled: boolean;
};

export type IndexStatus = {
  last_started_at: string | null;
  last_finished_at: string | null;
  total_files: number;
  error_count: number;
  is_running: boolean;
  cancel_requested: boolean;
  last_error: string | null;
};

export type FailedFile = {
  normalized_path: string;
  file_name: string;
  error_message: string;
  last_failed_at: string;
};

export type FailedFileListResponse = {
  items: FailedFile[];
};

export type IndexedTarget = {
  full_path: string;
  last_indexed_at: string | null;
  indexed_file_count: number;
};

export type IndexedTargetListResponse = {
  items: IndexedTarget[];
};

export type SearchTargetFolder = {
  full_path: string;
  is_enabled: boolean;
  last_indexed_at: string | null;
  indexed_file_count: number;
};

export type SearchTargetListResponse = {
  items: SearchTargetFolder[];
};

export type SearchTargetCoverage = {
  normalized_path: string;
  is_covered: boolean;
  covering_path: string | null;
};

export type AppSettings = {
  exclude_keywords: string;
  synonym_groups: string;
  index_selected_extensions: string;
  custom_content_extensions: string;
  custom_filename_extensions: string;
};

export type SchedulerLog = {
  logged_at: string;
  level: string;
  message: string;
  folder_path: string | null;
};

export type SchedulerSettings = {
  paths: string[];
  start_at: string | null;
  is_enabled: boolean;
  status: string;
  last_started_at: string | null;
  last_finished_at: string | null;
  current_path: string | null;
  last_error: string | null;
  logs: SchedulerLog[];
};
