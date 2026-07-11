param([ValidateSet("all", "folder", "single-file")][string]$Mode = "all")
$ErrorActionPreference = "Stop"
$project = Join-Path $PSScriptRoot "LocalSearchLauncher\LocalSearchLauncher.csproj"
$output = Join-Path $PSScriptRoot "publish"
$dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
$dotnet = if ($dotnetCommand) { $dotnetCommand.Source } else { Join-Path $env:LOCALAPPDATA "Microsoft\dotnet\dotnet.exe" }
if (-not (Test-Path $dotnet)) {
  throw ".NET 8 SDK が見つかりません。launcher/windows/README.md の手順でSDKを導入してください。"
}
function Reset-PublishDirectory([string]$Path) {
  $root = [IO.Path]::GetFullPath($output).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $target = [IO.Path]::GetFullPath($Path)
  if (-not $target.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "発行先が launcher/windows/publish の外にあります: $target"
  }
  if (Test-Path $target) { Remove-Item -LiteralPath $target -Recurse -Force }
  New-Item -ItemType Directory -Path $target -Force | Out-Null
}
if ($Mode -in @("all", "folder")) {
  $folderOutput = Join-Path $output "folder"
  Reset-PublishDirectory $folderOutput
  & $dotnet publish $project -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -p:DebugType=None -p:DebugSymbols=false -o $folderOutput
}
if ($Mode -in @("all", "single-file")) {
  $singleFileOutput = Join-Path $output "single-file"
  Reset-PublishDirectory $singleFileOutput
  & $dotnet publish $project -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=None -p:DebugSymbols=false -o $singleFileOutput
}
