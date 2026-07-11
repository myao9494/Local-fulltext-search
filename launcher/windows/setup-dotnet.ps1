param([string]$Channel = "8.0")

$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:LOCALAPPDATA "Microsoft\dotnet"
$dotnet = Join-Path $installDir "dotnet.exe"
$installed = if (Test-Path $dotnet) { @(& $dotnet --list-sdks) } else { @() }

if (-not ($installed | Where-Object { $_ -like "$Channel.*" })) {
  $installer = Join-Path $env:TEMP "dotnet-install.ps1"
  Invoke-WebRequest -UseBasicParsing "https://dot.net/v1/dotnet-install.ps1" -OutFile $installer
  & $installer -Channel $Channel -Architecture x64 -InstallDir $installDir
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($null -eq $userPath) { $userPath = "" }
if (($userPath -split ";") -notcontains $installDir) {
  $updatedPath = (($userPath.TrimEnd(";") + ";" + $installDir).TrimStart(";"))
  [Environment]::SetEnvironmentVariable("Path", $updatedPath, "User")
}

$env:PATH = "$installDir;$env:PATH"
& $dotnet --info
