using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace LocalSearchLauncher;

/// <summary>ローカルバックエンドへプロキシを介さず接続する。</summary>
internal sealed class LauncherApiClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly HttpClient _ganttHttp;
    private readonly JsonSerializerOptions _json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    public LauncherApiClient()
    {
        var baseUrl = Environment.GetEnvironmentVariable("LAUNCHER_API_BASE_URL") ?? "http://127.0.0.1:8079";
        var timeout = double.TryParse(Environment.GetEnvironmentVariable("LAUNCHER_REQUEST_TIMEOUT"), out var seconds) && seconds > 0 ? seconds : 5;
        _http = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(timeout) };
        var ganttBase = Environment.GetEnvironmentVariable("LAUNCHER_GANTT_API_BASE_URL") ?? "http://localhost:8000/api";
        _ganttHttp = new HttpClient(new HttpClientHandler { UseProxy = false }) { BaseAddress = new Uri(ganttBase.TrimEnd('/') + "/"), Timeout = TimeSpan.FromSeconds(timeout) };
    }

    public async Task<SearchResponse> SearchAsync(string query, int limit, bool includeGanttTasks, CancellationToken token)
    {
        var endpoint = includeGanttTasks ? "api/search" : "api/search/indexed";
        object payload = includeGanttTasks
            ? new { q = query, full_path = "", search_all_enabled = true, skip_refresh = true, source_type = "local", refresh_window_minutes = 0, search_target = "all", sort_by = "default", sort_order = "desc", limit, offset = 0, include_snippets = true, include_gantt_tasks = true }
            : new { q = query, folder_path = "", limit, offset = 0 };
        using var response = await _http.PostAsJsonAsync(endpoint, payload, _json, token);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<SearchResponse>(_json, token) ?? new SearchResponse(0, [], false);
    }

    public async Task RecordClickAsync(SearchItem item, string query)
    {
        if (item.FileId <= 0) return;
        using var response = await _http.PostAsJsonAsync("api/search/click", new { file_id = item.FileId, query }, _json);
        response.EnsureSuccessStatusCode();
    }

    public async Task OpenLocationAsync(string path)
    {
        using var response = await _http.PostAsJsonAsync("api/files/open-location", new { path }, _json);
        response.EnsureSuccessStatusCode();
    }

    public async Task OpenGanttTaskAsync(int taskId)
    {
        using var response = await _http.PostAsJsonAsync($"api/gantt/tasks/{Math.Abs(taskId)}/open-input", new { }, _json);
        response.EnsureSuccessStatusCode();
    }

    public async Task<int> GetGanttParentAsync(int fallback)
    {
        using var response = await _http.GetAsync("api/index/settings");
        response.EnsureSuccessStatusCode();
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        if (!document.RootElement.TryGetProperty("gantt_parent", out var value)) return fallback;
        return value.ValueKind switch
        {
            JsonValueKind.Number when value.TryGetInt32(out var number) && number >= 0 => number,
            JsonValueKind.String when int.TryParse(value.GetString(), out var number) && number >= 0 => number,
            _ => fallback,
        };
    }

    public async Task CreateGanttTaskAsync(GanttTaskRequest task)
    {
        using var response = await _ganttHttp.PostAsJsonAsync("tasks", task, _json);
        response.EnsureSuccessStatusCode();
    }

    public void Dispose()
    {
        _http.Dispose();
        _ganttHttp.Dispose();
    }
}
