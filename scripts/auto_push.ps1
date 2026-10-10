param(
    [string]$CommitMessage = ""
)

$ErrorActionPreference = "Continue"
$RepoDir = "D:\Git\sovapp"
$GitExe = "C:\Program Files\Git\cmd\git.exe"

if (-not (Test-Path $GitExe)) {
    $GitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($GitCmd) { $GitExe = $GitCmd.Source }
}

Write-Host "=== sovapp Auto Push & Retry System ===" -ForegroundColor Cyan
& python "$RepoDir\scripts\auto_push.py" $CommitMessage
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "=== Push Completed Successfully ===" -ForegroundColor Green
} else {
    Write-Host "=== Push Failed with Exit Code $exitCode ===" -ForegroundColor Red
}

exit $exitCode
