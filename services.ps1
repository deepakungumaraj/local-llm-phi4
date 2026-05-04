<#
.SYNOPSIS
    Manage local AI agent services: Ollama, Agent Server, Open WebUI.
.PARAMETER Action
    health   - Check status of all services
    start    - Start all services (skips already running)
    restart  - Stop and restart all services
    stop     - Stop Agent Server and Open WebUI (not Ollama)
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("health", "start", "restart", "stop")]
    [string]$Action = "health"
)

$ErrorActionPreference = "SilentlyContinue"

# --- Config ---
$OllamaPort    = 11434
$AgentPort     = 8000
$WebUIPort     = 8080
$AgentAppDir   = "c:\dev\local-llm-phi4\phi4-agent"

function Test-Service($Port) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch {
        # Fall back to root — some services (Ollama, WebUI) don't have /health
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:$Port" -UseBasicParsing -TimeoutSec 3
            return $r.StatusCode -lt 500
        } catch { return $false }
    }
}

function Get-ListeningPid($Port) {
    $line = netstat -ano | Select-String ":$Port\s.*LISTENING" | Select-Object -First 1
    if ($line) { return ($line -split '\s+')[-1] }
    return $null
}

function Stop-ServiceOnPort($Port, $Name) {
    $pid_ = Get-ListeningPid $Port
    if ($pid_) {
        Write-Host "  Stopping $Name (PID $pid_)..." -ForegroundColor Yellow
        Stop-Process -Id $pid_ -Force
        Start-Sleep -Seconds 2
    }
}

# --- Health ---
function Show-Health {
    Write-Host "`n=== Service Health ===" -ForegroundColor Cyan
    $services = @(
        @{ Name = "Ollama";       Port = $OllamaPort },
        @{ Name = "Agent Server"; Port = $AgentPort },
        @{ Name = "Open WebUI";   Port = $WebUIPort }
    )
    foreach ($svc in $services) {
        $up = Test-Service $svc.Port
        $status = if ($up) { "UP" } else { "DOWN" }
        $color  = if ($up) { "Green" } else { "Red" }
        Write-Host ("  {0,-15} http://localhost:{1,-6} [{2}]" -f $svc.Name, $svc.Port, $status) -ForegroundColor $color
    }
    Write-Host ""
}

# --- Start ---
function Start-Ollama {
    if (Test-Service $OllamaPort) {
        Write-Host "  Ollama already running" -ForegroundColor Green
        return
    }
    Write-Host "  Starting Ollama..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    if (Test-Service $OllamaPort) {
        Write-Host "  Ollama started" -ForegroundColor Green
    } else {
        Write-Host "  Ollama failed to start!" -ForegroundColor Red
    }
}

function Start-AgentServer {
    if (Test-Service $AgentPort) {
        Write-Host "  Agent Server already running" -ForegroundColor Green
        return
    }
    Write-Host "  Starting Agent Server..." -ForegroundColor Yellow
    $env:PYTHONUTF8 = "1"
    $env:OLLAMA_MODEL = "qwen2.5:3b"
    Start-Process "py" -ArgumentList "-m", "uvicorn", "server:app", "--port", "$AgentPort", "--app-dir", "$AgentAppDir" -WindowStyle Hidden
    $retries = 0
    while ($retries -lt 10) {
        Start-Sleep -Seconds 2
        if (Test-Service $AgentPort) {
            Write-Host "  Agent Server started" -ForegroundColor Green
            return
        }
        $retries++
    }
    Write-Host "  Agent Server failed to start!" -ForegroundColor Red
}

function Start-OpenWebUI {
    if (Test-Service $WebUIPort) {
        Write-Host "  Open WebUI already running" -ForegroundColor Green
        return
    }
    Write-Host "  Starting Open WebUI..." -ForegroundColor Yellow
    $env:OPENAI_API_BASE_URL = "http://localhost:$AgentPort/v1"
    $env:OPENAI_API_KEY = "sk-unused"
    $env:OLLAMA_BASE_URL = "http://localhost:$OllamaPort"
    Start-Process "uv" -ArgumentList "tool", "run", "open-webui", "serve" -WindowStyle Hidden
    $retries = 0
    while ($retries -lt 15) {
        Start-Sleep -Seconds 3
        if (Test-Service $WebUIPort) {
            Write-Host "  Open WebUI started" -ForegroundColor Green
            return
        }
        $retries++
    }
    Write-Host "  Open WebUI failed to start (may still be loading)..." -ForegroundColor Yellow
}

function Start-AllServices {
    Write-Host "`n=== Starting Services ===" -ForegroundColor Cyan
    Start-Ollama
    Start-AgentServer
    Start-OpenWebUI
    Write-Host ""
}

# --- Stop ---
function Stop-AllServices {
    Write-Host "`n=== Stopping Services ===" -ForegroundColor Cyan
    Stop-ServiceOnPort $WebUIPort  "Open WebUI"
    Stop-ServiceOnPort $AgentPort  "Agent Server"
    # Don't stop Ollama by default — it's shared
    Write-Host "  (Ollama left running — stop manually if needed)" -ForegroundColor DarkGray
    Write-Host ""
}

# --- Main ---
switch ($Action) {
    "health"  { Show-Health }
    "start"   { Start-AllServices; Show-Health }
    "stop"    { Stop-AllServices; Show-Health }
    "restart" { Stop-AllServices; Start-AllServices; Show-Health }
}
