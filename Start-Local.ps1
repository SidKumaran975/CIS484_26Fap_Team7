param([string]$Distribution = 'Ubuntu-22.04', [string]$LinuxUser = 'logan')
$ErrorActionPreference = 'Stop'
$databaseFile = Join-Path $PSScriptRoot 'runtime\assessment.sqlite3'
if (Test-Path -LiteralPath $databaseFile) {
    # Windows DB Browser can leave WAL mode enabled. Normalize with Windows
    # SQLite before a Linux process tries to read the Windows WAL index.
    $headerStream = [IO.File]::Open($databaseFile, 'Open', 'Read', 'ReadWrite')
    try {
        $databaseHeader = New-Object byte[] 20
        $headerLength = $headerStream.Read($databaseHeader, 0, 20)
    } finally { $headerStream.Dispose() }
    if ($headerLength -eq 20 -and ($databaseHeader[18] -eq 2 -or $databaseHeader[19] -eq 2)) {
        $windowsPython = $env:EXAM_WINDOWS_PYTHON
        if (-not $windowsPython) {
            $windowsPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        }
        if (-not (Test-Path -LiteralPath $windowsPython)) {
            throw 'Windows Python is needed to prepare this WAL database. Set EXAM_WINDOWS_PYTHON to your Windows python.exe path.'
        }
        & $windowsPython (Join-Path $PSScriptRoot 'scripts\prepare-windows-database.py') $databaseFile
        if ($LASTEXITCODE -ne 0) { throw 'Database preparation failed. Close DB Browser and stop both services, then retry.' }
    }
}
$windowsRoot = $PSScriptRoot.Replace('\', '/')
$linuxRoot = & wsl.exe -d $Distribution -u $LinuxUser --exec wslpath -a -u $windowsRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the project path in WSL. Verify the selected distribution and Linux user.' }
& wsl.exe -d $Distribution -u $LinuxUser --exec bash "$($linuxRoot.Trim())/scripts/start-local.sh"
if ($LASTEXITCODE -notin @(0, 130)) { throw "Application launch failed with exit code $LASTEXITCODE. See prerequisite error above." }
