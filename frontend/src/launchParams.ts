/**
 * 起動 URL のクエリ文字列から初期検索条件を取り出す。
 */
export type LaunchParams = {
  q: string;
  fullPath: string;
  indexDepth: string;
  searchAll: boolean;
};

/**
 * URLSearchParams から画面初期値を生成する。
 */
export function parseLaunchParams(search: string): LaunchParams {
  const params = new URLSearchParams(search);
  const fullPath = params.get("full_path")?.trim() ?? "";
  const q = params.get("q")?.trim() ?? "";
  const rawIndexDepth = params.get("index_depth")?.trim() ?? "";
  const searchAll = isTruthyQueryFlag(params.get("search_all"));

  return {
    q,
    fullPath,
    indexDepth: normalizeIndexDepth(rawIndexDepth),
    searchAll,
  };
}

/**
 * 自動検索を実行してよい URL パラメータかを判定する。
 */
export function shouldAutoSearch(params: LaunchParams): boolean {
  return params.q.length > 0 && (params.fullPath.length > 0 || params.searchAll);
}

/**
 * 階層数は不正値を既定値に丸めて扱う。
 */
function normalizeIndexDepth(value: string): string {
  if (value.length === 0) {
    return "1";
  }

  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) {
    return "1";
  }

  return String(parsed);
}

function isTruthyQueryFlag(value: string | null): boolean {
  if (value === null) {
    return false;
  }

  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}
