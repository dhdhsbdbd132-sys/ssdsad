# Read by START_WINDOWS.bat. No machine-wide ExecutionPolicy changes are needed.
$ErrorActionPreference = 'Stop'
$project = $env:TODAYGO_PROJECT_ROOT
$runtime = Join-Path $env:LOCALAPPDATA 'TodayGo\Python312'
$python = $null

function Find-Python312 {
    param([string]$Executable, [string[]]$Prefix = @())
    # A failed Python-version probe is expected when a candidate is unsupported.
    $ErrorActionPreference = 'Continue'
    try {
        $result = & $Executable @Prefix -X utf8 -c 'import sys; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) {
            $candidate = [string](@($result)[-1])
            if (Test-Path -LiteralPath $candidate.Trim() -PathType Leaf) {
                return $candidate.Trim()
            }
        }
    } catch { }
    return $null
}

try {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) { $python = Find-Python312 -Executable $launcher.Source -Prefix @('-3.12') }
    if (-not $python) {
        $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pathPython -and $pathPython.Source -notlike '*\Microsoft\WindowsApps\*') {
            $python = Find-Python312 -Executable $pathPython.Source
        }
    }
    if (-not $python) {
        $candidates = @(
            (Join-Path $runtime 'python.exe'),
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
            (Join-Path $env:ProgramFiles 'Python312\python.exe')
        )
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $python = Find-Python312 $candidate
                if ($python) { break }
            }
        }
    }
    if (-not $python) {
        $architecture = $env:PROCESSOR_ARCHITEW6432
        if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
        if ($architecture -ne 'AMD64') {
            throw 'This automatic installer needs 64-bit Intel/AMD Windows 10 or 11.'
        }
        Write-Host 'Python 3.12 was not found. Installing an official per-user runtime for TodayGo...'
        $installer = Join-Path ([System.IO.Path]::GetTempPath()) ('todaygo-python-' + [guid]::NewGuid().ToString('N') + '.exe')
        try {
            # 3.12.10 is the final 3.12 release with an official Windows installer.
            # HTTPS validation stays enabled, and Authenticode is checked before execution.
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
            $signature = Get-AuthenticodeSignature -LiteralPath $installer
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)CN=Python Software Foundation(,|$)') {
                throw 'The Python installer signature could not be verified. Installation stopped.'
            }
            $arguments = @('/quiet', '/norestart', 'InstallAllUsers=0', 'Include_launcher=0', 'Include_test=0', 'PrependPath=0', 'AssociateFiles=0', 'Shortcuts=0', ('TargetDir="' + $runtime + '"'))
            $installation = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
            if ($installation.ExitCode -notin @(0, 3010)) {
                throw ('Python installer failed with exit code ' + $installation.ExitCode)
            }
            $python = Find-Python312 (Join-Path $runtime 'python.exe')
            if (-not $python) { throw 'Python 3.12 was not installed. Check the installer result.' }
        } finally {
            if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer }
        }
    }
    $launchArguments = @('-X', 'utf8', (Join-Path $project 'scripts\launch_windows.py'))
    if ($env:TODAYGO_ANDROID_SERVER -eq '1') {
        $launchArguments += '--android-server'
    }
    & $python @launchArguments
    exit $LASTEXITCODE
} catch {
    Write-Host ('Error: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
