param(
    [string]$BoardHost = "auto",
    [string]$BoardUser = "fibo",
    [string]$SshKey = "$env:USERPROFILE\.ssh\id_ed25519_xingbao_board"
)

$ErrorActionPreference = "Stop"
$Candidates = if ($BoardHost -eq "auto") {
    @("192.168.43.35", "10.21.236.12", "qcs6490-odk.local")
} else {
    @($BoardHost)
}
$Args = @(
    "-i", $SshKey,
    "-o", "BatchMode=yes",
    "-o", "IdentitiesOnly=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=5"
)

$SelectedHost = $null
foreach ($candidate in $Candidates) {
    & ssh @Args "$BoardUser@$candidate" "printf XINGBAO_BOARD_OK" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $SelectedHost = $candidate
        break
    }
}
if (-not $SelectedHost) {
    throw "Cannot reach the board. Re-run with: -BoardHost <current-board-ip>"
}

& ssh @Args "$BoardUser@$SelectedHost" "sh /home/fibo/xingbao_one_click/board_one_click_deploy.sh start"
exit $LASTEXITCODE
