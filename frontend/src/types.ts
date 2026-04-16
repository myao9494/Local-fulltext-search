export type SearchResult = {
  file_id: number;
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

export type AppSettings = {
  exclude_keywords: string;
  synonym_groups: string;
  index_selected_extensions: string;
  custom_content_extensions: string;
  custom_filename_extensions: string;
};
