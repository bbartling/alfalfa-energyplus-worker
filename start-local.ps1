# Launch unmodified upstream Alfalfa, pinned to a reviewed source commit.
param([string]$Destination = "$PSScriptRoot\_alfalfa_upstream")
$ErrorActionPreference = "Stop"
$sha = "6c76e0b04fccc1fcbf64f8304bf622bc26710368"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is required" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop is required" }
docker compose version
if ($LASTEXITCODE -ne 0) { throw "Docker Compose is required" }
if (-not (Test-Path (Join-Path $Destination ".git"))) {
    git clone https://github.com/NatLabRockies/alfalfa.git $Destination
    if ($LASTEXITCODE -ne 0) { throw "Unable to clone upstream Alfalfa" }
}
Push-Location $Destination
try {
    git fetch origin $sha
    if ($LASTEXITCODE -ne 0) { throw "Unable to fetch pinned upstream commit" }
    git checkout --detach $sha
    if ($LASTEXITCODE -ne 0) { throw "Unable to check out upstream commit" }
    docker compose up --build
    if ($LASTEXITCODE -ne 0) { throw "Upstream Alfalfa failed" }
} finally { Pop-Location }
