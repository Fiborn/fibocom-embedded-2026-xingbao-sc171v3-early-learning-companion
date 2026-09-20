param(
    [string]$BoardHost = "auto",
    [string]$BoardUser = "fibo",
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519_xingbao_board"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CentralPackage = Join-Path $ProjectRoot "dist\xingbao_companion_central.zip"
$TouchPackage = Join-Path $ProjectRoot "dist\xingbao_touch_game_board.zip"
$CentralHash = "$CentralPackage.sha256"
$TouchHash = "$TouchPackage.sha256"
$BoardInstaller = Join-Path $ProjectRoot "deploy\board_one_click_deploy.sh"
$RemoteHome = "/home/fibo/xingbao_one_click"
$RemotePackages = "$RemoteHome/packages"

foreach ($path in @($CentralPackage, $TouchPackage, $CentralHash, $TouchHash, $BoardInstaller, $SshKey)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing one-click deployment file: $path"
    }
}

function Assert-PackageHash {
    param([string]$Package, [string]$Sidecar)
    $expected = ((Get-Content -LiteralPath $Sidecar -Raw).Trim() -split '\s+')[0].ToLower()
    $actual = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        throw "SHA256 mismatch: $Package"
    }
    Write-Host "[one-click] SHA256 verified: $(Split-Path $Package -Leaf)"
}

Assert-PackageHash -Package $CentralPackage -Sidecar $CentralHash
Assert-PackageHash -Package $TouchPackage -Sidecar $TouchHash

$Candidates = if ($BoardHost -eq "auto") {
    @("192.168.43.35", "10.21.236.12", "qcs6490-odk.local")
} else {
    @($BoardHost)
}

$CommonSshArgs = @(
    "-i", $SshKey,
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=5"
)

$SelectedHost = $null
foreach ($candidate in $Candidates) {
    & ssh @CommonSshArgs "$BoardUser@$candidate" "printf XINGBAO_BOARD_OK" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $SelectedHost = $candidate
        break
    }
}
if (-not $SelectedHost) {
    throw "Cannot reach the board. Re-run with: -BoardHost <current-board-ip>"
}

$Remote = "$BoardUser@$SelectedHost"
Write-Host "[one-click] Board found: $Remote"
& ssh @CommonSshArgs $Remote "mkdir -p '$RemotePackages'"
if ($LASTEXITCODE -ne 0) { throw "Cannot create the remote deployment directory." }

$Uploads = @(
    @($CentralPackage, "$RemotePackages/xingbao_companion_central.zip"),
    @($CentralHash, "$RemotePackages/xingbao_companion_central.zip.sha256"),
    @($TouchPackage, "$RemotePackages/xingbao_touch_game_board.zip"),
    @($TouchHash, "$RemotePackages/xingbao_touch_game_board.zip.sha256"),
    @($BoardInstaller, "$RemoteHome/board_one_click_deploy.sh")
)

foreach ($upload in $Uploads) {
    Write-Host "[one-click] Uploading $(Split-Path $upload[0] -Leaf)..."
    & scp @CommonSshArgs $upload[0] "$Remote`:$($upload[1])"
    if ($LASTEXITCODE -ne 0) {
        throw "Upload failed: $($upload[0])"
    }
}

$RemoteCommand = "chmod +x '$RemoteHome/board_one_click_deploy.sh' && sh '$RemoteHome/board_one_click_deploy.sh' install '$RemotePackages/xingbao_companion_central.zip' '$RemotePackages/xingbao_touch_game_board.zip'"

Write-Host "[one-click] Installing and starting the reviewed Xingbao release..."
& ssh @CommonSshArgs $Remote $RemoteCommand
$RemoteExit = $LASTEXITCODE
if ($RemoteExit -eq 0) {
    Write-Host "[one-click] RESULT=READY" -ForegroundColor Green
    exit 0
}
if ($RemoteExit -eq 2) {
    Write-Warning "Deployment succeeded, but the camera is not ready. Reconnect it and run the same command again."
    exit 2
}
throw "One-click deployment failed with exit code $RemoteExit."
