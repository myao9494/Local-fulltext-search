/**
 * 検索結果の種別・拡張子から表示用 Catppuccin アイコン名を選ぶ。
 */
export function catppuccinIconForResult(item: { file_name: string; result_kind: string; source_type?: string }): string {
  if (item.source_type === "gantt") return "task.svg";
  if (item.source_type === "web") return "html.svg";
  if (item.result_kind === "folder") return "folder.svg";

  const extension = item.file_name.toLowerCase().split(".").pop() ?? "";
  const iconByExtension: Record<string, string> = {
    md: "markdown.svg", markdown: "markdown.svg", pdf: "pdf.svg", json: "json.svg", xml: "xml.svg",
    txt: "txt.svg", csv: "csv.svg", yaml: "yaml.svg", yml: "yaml.svg", zip: "zip.svg",
    html: "html.svg", htm: "html.svg", js: "javascript.svg", jsx: "javascript.svg",
    ts: "typescript.svg", tsx: "typescript.svg", py: "python.svg",
    excalidraw: "excalidraw.svg", dio: "drawio.svg", drawio: "drawio.svg", epub: "epub.svg",
    png: "image.svg", jpg: "image.svg", jpeg: "image.svg", gif: "image.svg", svg: "image.svg", webp: "image.svg",
    mp3: "audio.svg", wav: "audio.svg", m4a: "audio.svg", mp4: "video.svg", mov: "video.svg", avi: "video.svg",
  };
  return iconByExtension[extension] ?? "file.svg";
}
