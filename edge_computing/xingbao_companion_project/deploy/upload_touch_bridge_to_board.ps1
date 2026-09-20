param(
    [Parameter(Mandatory = $true)]
    [string]$BoardHost,

    [string]$BoardUser = "fibo",
    [string]$Package = "work/incoming/xingbao_touch_game_latest/xingbao_touch_game/dist/xingbao_touch_game_board.zip",
    [string]$RemoteBase = "/home/fibo/arm_luojiefu/xingbao/xingbao"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PackagePath = Join-Path $ProjectRoot $Package
if (!(Test-Path $PackagePath)) {
    throw "Package not found: $PackagePath"
}

$Remote = "$BoardUser@$BoardHost"
$RemoteZip = "/tmp/xingbao_touch_game_bridge.zip"
$ReleaseId = Get-Date -Format "yyyyMMdd-HHmmss"
$Releases = "$RemoteBase/xingbao_touch_game_bridge_releases"
$Release = "$Releases/$ReleaseId"
$Current = "$RemoteBase/xingbao_touch_game_bridge"
$Shared = "$RemoteBase/xingbao_touch_game_shared"

Write-Host "Uploading touch desktop bridge to $Remote"
scp $PackagePath "${Remote}:$RemoteZip"

$Install = @"
set -eu
mkdir -p '$Releases' '$Shared/saves' '$Shared/logs' '$Release'
if [ -d '$Current/saves' ] && [ ! -L '$Current/saves' ]; then cp -an '$Current/saves/.' '$Shared/saves/' 2>/dev/null || true; fi
if [ -d '$Current/logs' ] && [ ! -L '$Current/logs' ]; then cp -an '$Current/logs/.' '$Shared/logs/' 2>/dev/null || true; fi
unzip -q '$RemoteZip' -d '$Release'
rm -rf '$Release/saves' '$Release/logs'
ln -s '$Shared/saves' '$Release/saves'
ln -s '$Shared/logs' '$Release/logs'
if [ -e '$Current' ] && [ ! -L '$Current' ]; then mv '$Current' '${Current}_backup_$ReleaseId'; fi
ln -sfn '$Release' '$Current'
test -f '$Current/desktop.py'
find '$Releases' -mindepth 1 -maxdepth 1 -type d | sort -r | awk 'NR>3' | xargs -r rm -rf
echo TOUCH_BRIDGE_RELEASE=$Release
"@
ssh $Remote $Install

Write-Host "Touch desktop bridge installed at $Current"
Write-Host "Start it with:"
Write-Host "ssh $Remote `"cd $Current && python3 desktop.py --fullscreen --low-effects`""
