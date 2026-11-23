# Start the real laboratory-maintained Alfalfa stack without modifying its source.
param([string]$Destination = "$PSScriptRoot\_alfalfa_upstream", [switch]$PullLatest)
$ErrorActionPreference = "Stop"
$repo = "https://github.com/NatLabRockies/alfalfa.git"
$reviewedSha = "6c76e0b04fccc1fcbf64f8304bf622bc26710368"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Install Git first." }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Install and start Docker Desktop first." }
docker compose version
if ($LASTEXITCODE -ne 0) { throw "Docker Compose plugin unavailable." }
if (-not (Test-Path (Join-Path $Destination ".git"))) {
    git clone $repo $Destination
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}
Push-Location $Destination
try {
    git fetch origin $reviewedSha
    if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
    if ($PullLatest) {
        Write-Warning "PullLatest is not supported: this launcher intentionally pins reviewed upstream source."
    }
    git checkout --detach $reviewedSha
    if ($LASTEXITCODE -ne 0) { throw "git checkout failed" }
    Write-Host "Starting official Alfalfa at upstream commit $reviewedSha"
    docker compose up --build
    if ($LASTEXITCODE -ne 0) { throw "Alfalfa Docker Compose failed" }
} finally { Pop-Location }
