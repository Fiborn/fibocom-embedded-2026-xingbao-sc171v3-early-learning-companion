param(
    [string]$Output = "dist/xingbao_companion_central.zip"
)

$ErrorActionPreference = "Stop"

$CurrentRoot = Resolve-Path (Get-Location)
if ((Test-Path (Join-Path $CurrentRoot "app.py")) -and (Test-Path (Join-Path $CurrentRoot "core"))) {
    $ProjectRoot = $CurrentRoot
} else {
    $ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
}
$StageRoot = Join-Path $ProjectRoot "work\package"
$Stage = Join-Path $StageRoot "xingbao_companion"
$OutputPath = Join-Path $ProjectRoot $Output

if ((Resolve-Path $ProjectRoot).Path -notlike "*xingbao_companion*") {
    throw "Refusing to package from unexpected project root: $ProjectRoot"
}

if (Test-Path $Stage) {
    Remove-Item -LiteralPath $Stage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $OutputPath -Parent) | Out-Null

$Files = @(
    ".env.example",
    "AGENTS.md",
    "app.py",
    "main.py",
    "pc5.py",
    "pytest.ini",
    "README.md",
    "requirements.txt",
    "requirements-wake-word.txt"
)

$Dirs = @(
    "config",
    "core",
    "docs",
    "deploy",
    "examples",
    "intelligence",
    "multimodal",
    "src",
    "tests",
    "tools",
    "web"
)

foreach ($file in $Files) {
    $source = Join-Path $ProjectRoot $file
    if (Test-Path $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $Stage $file) -Force
    }
}

foreach ($dir in $Dirs) {
    $source = Join-Path $ProjectRoot $dir
    if (Test-Path $source) {
        $targetRoot = Join-Path $Stage $dir
        New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
        Get-ChildItem -LiteralPath $source -Recurse -File | ForEach-Object {
            $relative = $_.FullName.Substring($source.Length).TrimStart("\", "/")
            $target = Join-Path $targetRoot $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

$RuntimeDirs = @("data", "logs", "work\tmp")
foreach ($dir in $RuntimeDirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Stage $dir) | Out-Null
}

Get-ChildItem -LiteralPath $Stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $Stage -Recurse -Include "*.pyc", "*.pyo" -File | Remove-Item -Force

if (Test-Path $OutputPath) {
    Remove-Item -LiteralPath $OutputPath -Force
}

Compress-Archive -LiteralPath $Stage -DestinationPath $OutputPath -Force

Write-Host "Created package: $OutputPath"
Write-Host "Upload target directory on board: /home/fibo/arm_luojiefu/xingbao/xingbao/xingbao_companion"
Write-Host "Note: .env, .venv, work cache, logs, and local zip files are intentionally excluded."
