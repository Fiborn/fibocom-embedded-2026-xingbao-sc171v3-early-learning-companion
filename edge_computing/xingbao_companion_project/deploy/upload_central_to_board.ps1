param(
    [Parameter(Mandatory = $true)]
    [string]$BoardHost,

    [string]$BoardUser = "fibo",
    [string]$RemoteDir = "/home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion",
    [string]$Package = "dist/xingbao_companion_central.zip"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PackagePath = Join-Path $ProjectRoot $Package

if (!(Test-Path $PackagePath)) {
    throw "Package not found: $PackagePath. Run python tools\make_central_board_package.py first."
}

$Remote = "$BoardUser@$BoardHost"
$RemoteZip = "/tmp/xingbao_companion_central.zip"

Write-Host "Uploading $PackagePath to ${Remote}:$RemoteZip"
scp $PackagePath "${Remote}:$RemoteZip"

Write-Host "Installing to $RemoteDir"
ssh $Remote "rm -rf /tmp/xingbao_companion_unpack && mkdir -p /tmp/xingbao_companion_unpack '$RemoteDir' && unzip -o '$RemoteZip' -d /tmp/xingbao_companion_unpack >/dev/null && cp -a /tmp/xingbao_companion_unpack/xingbao_companion/. '$RemoteDir'/ && mkdir -p '$RemoteDir/data' '$RemoteDir/logs' '$RemoteDir/work/tmp' && rm -rf /tmp/xingbao_companion_unpack"

Write-Host "Done."
Write-Host "Install/update dependencies with:"
Write-Host "ssh $Remote `"cd $RemoteDir && sh deploy/board_install_deps.sh`""
Write-Host "Check board readiness with:"
Write-Host "ssh $Remote `"cd $RemoteDir && python3 tools/board_health_check.py`""
Write-Host "Start central demo with:"
Write-Host "ssh $Remote `"cd $RemoteDir && sh deploy/board_start_demo.sh`""
