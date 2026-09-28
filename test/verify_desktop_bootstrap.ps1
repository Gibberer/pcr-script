param([string]$Executable = 'artifacts/gui/PcrDesktop.exe')
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path "$PSScriptRoot/..").Path
$root = Join-Path $workspace ('cache/build/bootstrap-' + [guid]::NewGuid())
$exePath = (Resolve-Path $Executable).Path
$arguments = @('--bootstrap-smoke', $root, $workspace) | ForEach-Object { '"' + $_ + '"' }
# Explicit network test, not part of the offline suite. No installed pip cache is used.
$previousCache = $env:PIP_NO_CACHE_DIR
try {
    $env:PIP_NO_CACHE_DIR = '1'
    $process = Start-Process -FilePath $exePath -ArgumentList $arguments -PassThru -WindowStyle Hidden
    Write-Output "Bootstrap verification log: $root/bootstrap.log"
    if (-not $process.WaitForExit(2400000)) {
        & "$env:SystemRoot/System32/taskkill.exe" /PID $process.Id /T /F | Out-Null
        throw 'Bootstrap verification timed out'
    }
    if ($process.ExitCode -ne 0) {
        Get-Content (Join-Path $root 'error.txt') -ErrorAction SilentlyContinue
        throw 'Bootstrap verification failed; see bootstrap.log and project/cache/desktop/setup'
    }
    Get-Content (Join-Path $root 'bootstrap.log') -Tail 4
}
finally { $env:PIP_NO_CACHE_DIR = $previousCache }
