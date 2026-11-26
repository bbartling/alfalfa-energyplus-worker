# Launch upstream Alfalfa and the separate telemetry client.
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
} finally { Pop-Location }
if ([IO.Path]::GetFullPath($Destination) -ne [IO.Path]::GetFullPath("$PSScriptRoot\_alfalfa_upstream")) {
    throw "Compose uses the pinned _alfalfa_upstream directory; custom destinations are unsupported"
}
Push-Location $PSScriptRoot
try {
    docker compose pull web worker minio mc mongo redis
    if ($LASTEXITCODE -ne 0) { throw "Unable to pull upstream images" }
    docker compose build telemetry
    if ($LASTEXITCODE -ne 0) { throw "Unable to build telemetry client" }
    docker compose up -d --no-build
    if ($LASTEXITCODE -ne 0) { throw "Alfalfa failed to start" }
} finally { Pop-Location }
