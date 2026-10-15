<# Install a per-user Startup shortcut for the complete local stack.
   No administrator task registration is required. Remove the shortcut
   from the Windows Startup folder to disable logon startup. #>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$startupDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Startup)
if (-not $startupDir) { throw "Windows did not return the current user's Startup folder." }
if (-not (Test-Path -LiteralPath $startupDir)) {
    New-Item -ItemType Directory -Path $startupDir -Force | Out-Null
}

$shortcutPath = Join-Path $startupDir "MyceliumLocal.lnk"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $powershell)) {
    $powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershell
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -File `"$root\tools\start-local.ps1`""
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Start Docker Desktop, INVENTory, Mycelium coordinator, Ollama and Hermes at sign-in"
$shortcut.Save()

if (-not (Test-Path -LiteralPath $shortcutPath)) {
    throw "Startup shortcut was not created at $shortcutPath"
}
Write-Output "Installed current-user startup shortcut: $shortcutPath"
