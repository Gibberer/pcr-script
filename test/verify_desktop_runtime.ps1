param(
    [string]$Executable = 'artifacts/gui/PcrDesktop.exe',
    [string]$Python = (Get-Command python).Source,
    [string]$Evidence = 'artifacts/gui-smoke.png'
)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path "$PSScriptRoot/..").Path
$fixture = Join-Path $workspace ('cache/build/runtime-smoke-' + [guid]::NewGuid())
$source = Join-Path $fixture 'source'
$target = Join-Path $fixture 'download'
New-Item -ItemType Directory -Path $source -Force | Out-Null
foreach ($item in @('pcrscript', 'images', 'requirements.txt', 'runtime_defaults.yml')) {
    $destination = Join-Path $source $item
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $workspace $item) -Destination $destination -Recurse
}
# Unrelated payload must remain absent from both the checkout and downloaded blobs.
New-Item -ItemType Directory -Path "$source/scripts", "$source/docs", "$source/desktop/PcrDesktop" | Out-Null
$unrelated = 'excluded-content-' + [guid]::NewGuid()
Set-Content "$source/scripts/agent-only.txt" $unrelated
Set-Content "$source/docs/notes.txt" 'not needed'
Set-Content "$source/desktop/PcrDesktop/gui-source.txt" 'not needed'
Set-Content "$source/README.md" 'not needed'
Set-Content "$source/.gitignore" "__pycache__/`n*.pyc"
function Git([string]$directory, [string[]]$arguments) {
    $result = & git.exe -C $directory @arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($result | Out-String) }
    return $result
}
Git $source @('init', '-b', 'runtime-test') | Out-Null
Git $source @('config', 'uploadpack.allowFilter', 'true') | Out-Null
Git $source @('add', '.') | Out-Null
Git $source @('-c', 'user.name=Runtime Test', '-c', 'user.email=runtime@example.invalid', 'commit', '-m', 'Synthetic runtime checkout') | Out-Null
$missingHash = (Git $source @('hash-object', 'scripts/agent-only.txt')).Trim()
$sourceUrl = ([uri]($source.Replace('\', '/') + '/')).AbsoluteUri
$exePath = (Resolve-Path $Executable).Path
$pythonPath = (Resolve-Path $Python).Path
$imagePath = [IO.Path]::GetFullPath($Evidence)
New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($imagePath)) -Force | Out-Null
$arguments = @('--smoke', $imagePath, $target, $pythonPath, $sourceUrl, 'runtime-test') | ForEach-Object { '"' + $_ + '"' }
$process = Start-Process -FilePath $exePath -ArgumentList $arguments -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'Runtime GUI smoke timed out' }
if ($process.ExitCode -ne 0) {
    Get-Content ($imagePath + '.error.txt') -ErrorAction SilentlyContinue
    throw 'Runtime GUI smoke failed'
}
foreach ($excluded in @('scripts', 'docs', 'desktop/PcrDesktop', 'README.md', 'docs/examples/daily.example.yml', 'daily_task.py')) {
    if (Test-Path (Join-Path $target $excluded)) { throw "Unexpected download: $excluded" }
}
if (-not (Test-Path (Join-Path $target 'runtime_defaults.yml')) -or
    (Test-Path (Join-Path $target 'desktop/runtime_defaults.yml')) -or
    (Test-Path (Join-Path $target 'pcrscript/runtime_defaults.yml'))) {
    throw 'GUI runtime defaults missing or duplicated in the core checkout'
}
$objects = Git $target @('rev-list', '--objects', '--all', '--missing=print')
if ($objects -notcontains ('?' + $missingHash)) { throw 'Unrelated file blob was downloaded' }
if ((Git $target @('status', '--porcelain') | Out-String).Trim()) { throw 'Generated runtime data is not ignored' }
if (-not (Test-Path $imagePath)) { throw 'Missing GUI render' }
# Normal fast-forward updates must retain the sparse checkout and skip new tool files.
Set-Content "$source/pcrscript/runtime-update.txt" 'synthetic update'
Set-Content "$source/scripts/new-agent-tool.txt" 'excluded update'
Git $source @('add', '.') | Out-Null
Git $source @('-c', 'user.name=Runtime Test', '-c', 'user.email=runtime@example.invalid', 'commit', '-m', 'Synthetic update') | Out-Null
Git $target @('fetch', 'origin', 'runtime-test') | Out-Null
Git $target @('merge', '--ff-only', 'FETCH_HEAD') | Out-Null
if (-not (Test-Path "$target/pcrscript/runtime-update.txt") -or (Test-Path "$target/scripts")) {
    throw 'Update did not preserve core download scope'
}
Write-Output "Runtime-only download and GUI verification passed: $target"

$fullTarget = Join-Path $fixture 'full'
$fullImage = $imagePath + '.full.png'
$arguments = @('--smoke', $fullImage, $fullTarget, $pythonPath, $sourceUrl, 'runtime-test', 'full') | ForEach-Object { '"' + $_ + '"' }
$process = Start-Process -FilePath $exePath -ArgumentList $arguments -PassThru -WindowStyle Hidden
if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'Full repository GUI smoke timed out' }
if ($process.ExitCode -ne 0) {
    Get-Content ($fullImage + '.error.txt') -ErrorAction SilentlyContinue
    throw 'Full repository GUI smoke failed'
}
foreach ($included in @('scripts/agent-only.txt', 'docs/notes.txt', 'desktop/PcrDesktop/gui-source.txt', 'README.md')) {
    if (-not (Test-Path (Join-Path $fullTarget $included))) { throw "Full download missing: $included" }
}
Write-Output "Full repository download and GUI verification passed: $fullTarget"
