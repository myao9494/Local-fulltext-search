export type SearchResult = {
  file_id: number;
  target_id: number;
  target_path: string;
  file_name: string;
  full_path: string;
  file_ext: string;
  mtime: string;
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
  last_error: string | null;
};
