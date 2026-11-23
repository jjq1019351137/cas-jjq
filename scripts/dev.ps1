#Requires -Version 5.1
<#
.SYNOPSIS
  一键启动前后端本地调试环境（各开一个控制台窗口）。

.PARAMETER BackendOnly
  只启动后端

.PARAMETER FrontendOnly
  只启动前端

.PARAMETER SameWindow
  在当前窗口前台串行等待（不新开窗口；适合只看一侧日志时）
#>
[CmdletBinding()]
param(
  [switch]$BackendOnly,
  [switch]$FrontendOnly,
  [switch]$SameWindow
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$BackendPort = 8000
$FrontendPort = 5173

$userLocal = Join-Path $env:USERPROFILE ".local"
$userLocalBin = Join-Path $env:USERPROFILE ".local\bin"
$env:Path = "$userLocal;$userLocalBin;$env:Path"

function Write-Step([string]$Message) {
  Write-Host "[dev] $Message" -ForegroundColor Cyan
}

function Write-Fail([string]$Message) {
  Write-Host "[dev] $Message" -ForegroundColor Red
}

function Test-PortInUse([int]$Port) {
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    $listener.Stop()
    return $false
  } catch {
    return $true
  }
}

function Ensure-BackendEnv {
  $envFile = Join-Path $BackendDir ".env"
  $example = Join-Path $BackendDir ".env.example"
  if (-not (Test-Path $envFile) -and (Test-Path $example)) {
    Copy-Item $example $envFile
    Write-Step "已从 .env.example 生成 backend/.env"
  }
}

function Ensure-BackendReady {
  if (-not (Test-Path $VenvPython)) {
    Write-Step "未找到 backend/.venv，正在用 uv 创建 Python 3.13 ..."
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
      Write-Fail "未安装 uv。请执行: irm https://astral.sh/uv/install.ps1 | iex"
      exit 1
    }
    Push-Location $BackendDir
    try {
      uv python install 3.13
      uv venv --python 3.13 .venv
      uv pip install -r requirements.txt
      if (Test-Path ".\requirements-dev.txt") {
        uv pip install -r requirements-dev.txt
      }
    } finally {
      Pop-Location
    }
  }
}

function Ensure-FrontendReady {
  if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Write-Fail "未找到 pnpm。可执行: npm install -g pnpm --prefix `"$env:USERPROFILE\.local`""
    exit 1
  }
  if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Step "安装前端依赖 (pnpm install) ..."
    Push-Location $FrontendDir
    try {
      pnpm install --frozen-lockfile
    } finally {
      Pop-Location
    }
  }
}

function Start-BackendWindow {
  $py = $VenvPython
  $cmd = @"
`$Host.UI.RawUI.WindowTitle = 'CASX Backend :$BackendPort'
`$env:Path = '$userLocal;$userLocalBin;' + `$env:Path
Set-Location -LiteralPath '$BackendDir'
Write-Host '[backend] http://127.0.0.1:$BackendPort  docs: /docs' -ForegroundColor Green
& '$py' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort
Write-Host '[backend] 已退出，按任意键关闭窗口' -ForegroundColor Yellow
pause
"@
  Start-Process powershell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd) | Out-Null
}

function Start-FrontendWindow {
  $cmd = @"
`$Host.UI.RawUI.WindowTitle = 'CASX Frontend :$FrontendPort'
`$env:Path = '$userLocal;$userLocalBin;' + `$env:Path
Set-Location -LiteralPath '$FrontendDir'
Write-Host '[frontend] http://127.0.0.1:$FrontendPort  (/api -> :$BackendPort)' -ForegroundColor Green
pnpm dev --host 127.0.0.1 --port $FrontendPort
Write-Host '[frontend] 已退出，按任意键关闭窗口' -ForegroundColor Yellow
pause
"@
  Start-Process powershell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $cmd) | Out-Null
}

# ---- main ----
Ensure-BackendEnv

if (-not $FrontendOnly) {
  if (Test-PortInUse $BackendPort) {
    Write-Fail "端口 $BackendPort 已被占用。"
    exit 1
  }
  Ensure-BackendReady
}

if (-not $BackendOnly) {
  if (Test-PortInUse $FrontendPort) {
    Write-Fail "端口 $FrontendPort 已被占用。"
    exit 1
  }
  Ensure-FrontendReady
}

if ($SameWindow) {
  if ($BackendOnly -and -not $FrontendOnly) {
    Set-Location $BackendDir
    & $VenvPython -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort
    exit $LASTEXITCODE
  }
  if ($FrontendOnly -and -not $BackendOnly) {
    Set-Location $FrontendDir
    pnpm dev --host 127.0.0.1 --port $FrontendPort
    exit $LASTEXITCODE
  }
  Write-Fail "SameWindow 仅支持配合 -BackendOnly 或 -FrontendOnly 使用；默认会开两个窗口。"
  exit 1
}

if (-not $FrontendOnly) {
  Write-Step "启动后端窗口 :$BackendPort"
  Start-BackendWindow
}

if (-not $BackendOnly) {
  Write-Step "启动前端窗口 :$FrontendPort"
  Start-FrontendWindow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  调试环境已在新窗口启动" -ForegroundColor Green
if (-not $FrontendOnly) {
  Write-Host "  后端 API : http://127.0.0.1:$BackendPort/docs"
}
if (-not $BackendOnly) {
  Write-Host "  前端页面 : http://127.0.0.1:$FrontendPort"
  Write-Host "  /api 已由 Vite 代理到后端"
}
Write-Host "  关闭对应窗口即可停止该服务"
Write-Host "========================================" -ForegroundColor Green
