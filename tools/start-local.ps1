<#
Start the complete local Mycelium stack when needed:
  INVENTory :8080, coordinator :8000, Ollama :11434, Hermes :8642,
  and local Obsidian LiveSync CouchDB :5984 when Docker is ready.
Services already answering locally are left alone. Running this again repairs
services that were stopped; this script is not a background watchdog.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script:startupFailures = @()

function Add-StartupFailure {
    param([string]$Message)
    $script:startupFailures += $Message
    Write-Output "STARTUP WARNING: $Message"
}

# Docker Desktop starts the CouchDB service for Obsidian LiveSync. Open the
# desktop app at sign-in so its engine can start when firmware virtualization
# is enabled. Docker's own UI reports the firmware blocker when it is not.
$dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
if (Test-Path -LiteralPath $dockerDesktop) {
    if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $dockerDesktop -WindowStyle Normal
        Write-Output "Docker Desktop: launched (engine availability is shown in Docker Desktop)."
    } else {
        Write-Output "Docker Desktop: already open."
    }
} else {
    Write-Output "Docker Desktop: not installed; skipping."
}

function Test-LocalHttp {
    param([string]$Url, [int]$ExpectedStatus = 0)
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(2)
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        $status = [int]$response.StatusCode
        $response.Dispose()
        if ($ExpectedStatus -gt 0) { return ($status -eq $ExpectedStatus) }
        return ($status -ge 200 -and $status -lt 500)
    } catch {
        # A live service may not implement /health and may return 404/405.
        return $false
    } finally {
        $client.Dispose()
    }
}

function Start-LocalHttpService {
    param(
        [string]$Name,
        [string]$Url,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )
    if (Test-LocalHttp -Url $Url) {
        Write-Output "${Name}: already responding at $Url"
        return
    }
    if (-not $FilePath -or -not (Test-Path -LiteralPath $FilePath)) {
        Add-StartupFailure "${Name}: executable not found."
        return
    }
    try {
        Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -WindowStyle Hidden
    } catch {
        Add-StartupFailure "${Name}: process launch failed."
        return
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-LocalHttp -Url $Url) {
            Write-Output "${Name}: started at $Url"
            return
        }
    }
    Add-StartupFailure "${Name}: did not answer its local health URL within 30 seconds."
}

function Start-ObsidianCouchDB {
    $composeDir = Join-Path $root "ops\obsidian-livesync"
    $composeFile = Join-Path $composeDir "compose.yaml"
    $healthUrl = "http://127.0.0.1:5984/_up"
    if (Test-LocalHttp -Url $healthUrl -ExpectedStatus 200) {
        Write-Output "Obsidian LiveSync CouchDB: already responding locally."
        return
    }
    if (-not (Test-Path -LiteralPath $composeFile)) {
        Add-StartupFailure "Obsidian LiveSync CouchDB: compose file not found."
        return
    }
    $docker = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (-not (Test-Path -LiteralPath $docker)) {
        $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
        if ($dockerCommand) { $docker = $dockerCommand.Source }
    }
    if (-not (Test-Path -LiteralPath $docker)) {
        Add-StartupFailure "Obsidian LiveSync CouchDB: Docker CLI not found."
        return
    }
    try {
        $null = & $docker info --format '{{.ServerVersion}}' 2>$null
        $daemonReady = ($LASTEXITCODE -eq 0)
    } catch {
        $daemonReady = $false
    }
    if (-not $daemonReady) {
        Add-StartupFailure "Obsidian LiveSync CouchDB: Docker engine is unavailable; check Docker Desktop/UEFI virtualization."
        return
    }
    Push-Location $composeDir
    try {
        $null = & $docker compose up -d 2>$null
        $composeExit = $LASTEXITCODE
    } catch {
        $composeExit = 1
    } finally {
        Pop-Location
    }
    if ($composeExit -ne 0) {
        Add-StartupFailure "Obsidian LiveSync CouchDB: Compose could not start the local service."
        return
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-LocalHttp -Url $healthUrl -ExpectedStatus 200) {
            Write-Output "Obsidian LiveSync CouchDB: started at 127.0.0.1:5984."
            return
        }
    }
    Add-StartupFailure "Obsidian LiveSync CouchDB: did not become healthy within 30 seconds."
}

function Select-PythonRuntime {
    param(
        [string]$ProjectDirectory,
        [string]$VirtualEnvironmentPython,
        [string]$AppModule
    )
    $candidates = @($VirtualEnvironmentPython, $pythonFallback) |
        Where-Object { $_ } | Select-Object -Unique
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        Push-Location $ProjectDirectory
        try {
            $null = & $candidate -c "import importlib, fastapi, uvicorn; importlib.import_module('$AppModule')" 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {
            # Try the next interpreter; the startup warning explains if none work.
        } finally {
            Pop-Location
        }
    }
    return ""
}

$invDir = Join-Path $root "inventory"
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonFallback = if ($pythonCommand) { $pythonCommand.Source } else { "" }
$inv = Select-PythonRuntime -ProjectDirectory $invDir -VirtualEnvironmentPython (Join-Path $invDir ".venv\Scripts\python.exe") -AppModule "app.main"
if ($inv) {
    Start-LocalHttpService -Name "INVENTory" -Url "http://127.0.0.1:8080/" -FilePath $inv -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080") -WorkingDirectory $invDir
} else {
    Add-StartupFailure "INVENTory: no Python environment can import FastAPI, Uvicorn, and app.main."
}

$coordDir = Join-Path $root "mycelium-ai-main"
$coord = Select-PythonRuntime -ProjectDirectory $coordDir -VirtualEnvironmentPython (Join-Path $coordDir ".venv\Scripts\python.exe") -AppModule "coordinator.app.main"
if ($coord) {
    Start-LocalHttpService -Name "Coordinator" -Url "http://127.0.0.1:8000/health" -FilePath $coord -ArgumentList @("-m", "uvicorn", "coordinator.app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $coordDir
} else {
    Add-StartupFailure "Coordinator: no Python environment can import FastAPI, Uvicorn, and coordinator.app.main."
}

$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path -LiteralPath $ollama)) {
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaCommand) { $ollama = $ollamaCommand.Source }
}
if (-not (Test-Path -LiteralPath $ollama)) {
    Add-StartupFailure "Ollama: executable not found."
} else {
    Start-LocalHttpService -Name "Ollama" -Url "http://127.0.0.1:11434/api/tags" -FilePath $ollama -ArgumentList @("serve") -WorkingDirectory $env:LOCALAPPDATA
}

$hermes = Join-Path $env:LOCALAPPDATA "hermes\bin\hermes.exe"
if (-not (Test-Path -LiteralPath $hermes)) {
    $hermesCommand = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermesCommand) { $hermes = $hermesCommand.Source }
}
if (-not (Test-Path -LiteralPath $hermes)) {
    Add-StartupFailure "Hermes gateway: executable not found."
} else {
    Start-LocalHttpService -Name "Hermes gateway" -Url "http://127.0.0.1:8642/health" -FilePath $hermes -ArgumentList @("gateway", "start") -WorkingDirectory $root
}

Start-ObsidianCouchDB

if ($script:startupFailures.Count -gt 0) {
    Write-Output "Local stack started with $($script:startupFailures.Count) warning(s); see above."
    exit 1
}
Write-Output "Local stack ready: INVENTory :8080, coordinator :8000, Ollama :11434, Hermes :8642, CouchDB :5984."
