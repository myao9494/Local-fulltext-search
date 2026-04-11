import type { IndexStatus, SearchResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8081";

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

export async function pickFolder(): Promise<{ full_path: string }> {
  return request<{ full_path: string }>("/api/folders/pick", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function search(params: {
  q: string;
  full_path: string;
  index_depth: number;
  refresh_window_minutes: number;
  types?: string;
}): Promise<SearchResponse> {
  return request<SearchResponse>("/api/search", {
    method: "POST",
    body: JSON.stringify({
      ...params,
      limit: 20,
      offset: 0,
    }),
  });
}
