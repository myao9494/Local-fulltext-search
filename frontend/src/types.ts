export type SearchResult = {
  file_id: number;
  result_kind: "file" | "folder";
  source_type: "local" | "web" | "gantt";
  target_path: string;
  file_name: string;
  full_path: string;
  file_ext: string;
  created_at: string;
  mtime: string;
  click_count: number;
  has_obsidian_top_tag?: boolean;
  filename_match_priority?: boolean;
  filename_match_level?: number;
  relevance_bucket?: number;
  utility_score?: number;
  query_click_score?: number;
  snippet: string;
  gantt_link?: string | null;
};

export type SearchResponse = {
  total: number;
  items: SearchResult[];
  has_more: boolean;
  next_offset: number | null;
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
  source_type: "local" | "web" | "gantt";
  last_indexed_at: string | null;
  indexed_file_count: number;
};

export type IndexedTargetListResponse = {
  items: IndexedTarget[];
};

export type SearchTargetFolder = {
  full_path: string;
  source_type: "local" | "web" | "gantt";
  is_enabled: boolean;
  last_indexed_at: string | null;
  indexed_file_count: number;
};

export type SearchTargetListResponse = {
  items: SearchTargetFolder[];
};

export type SearchTargetCoverage = {
  normalized_path: string;
  source_type: "local" | "web" | "gantt";
  is_covered: boolean;
  covering_path: string | null;
};

export type AppSettings = {
  exclude_keywords: string;
  web_exclude_keywords: string;
  web_fetch_mode: "http" | "edge" | "chrome";
  hidden_indexed_targets: string;
  synonym_groups: string;
  obsidian_sidebar_explorer_data_path: string;
  gantt_parent: number;
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

export type LauncherStatus = {
  status: "running" | "stopped" | "exited";
  is_running: boolean;
  pid: number | null;
  returncode: number | null;
  autostart: boolean;
  log_path: string;
  logs: string[];
};
