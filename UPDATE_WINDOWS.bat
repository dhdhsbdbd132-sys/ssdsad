@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "TODAYGO_UPDATE_FILE=%~f0"
if not "%~1"=="" set "TODAYGO_UPDATE_PROJECT=%~1"
echo TodayGo - update application
powershell.exe -NoLogo -NoProfile -Command "$body=[System.IO.File]::ReadAllText($env:TODAYGO_UPDATE_FILE,[System.Text.Encoding]::UTF8); $marker=[regex]::Match($body,'(?m)^# TODAYGO_UPDATE_POWERSHELL\r?\n'); if(-not $marker.Success){throw 'Embedded updater script is missing.'}; & ([scriptblock]::Create($body.Substring($marker.Index+$marker.Length)))"
set "TODAYGO_UPDATE_EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %TODAYGO_UPDATE_EXIT_CODE%
# TODAYGO_UPDATE_POWERSHELL
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-FileDigest([string] $Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $digest = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $digest.Dispose(); $stream.Dispose() }
}

function Assert-RegularPath([string] $Base, [string] $Relative) {
    $current = [System.IO.Path]::GetFullPath($Base)
    if (Test-Path -LiteralPath $current) {
        if (((Get-Item -LiteralPath $current -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Ссылки и перенаправления папок не поддерживаются: $current"
        }
    }
    foreach ($part in ($Relative -split '/')) {
        if ([string]::IsNullOrEmpty($part)) { continue }
        $current = Join-Path $current $part
        if (Test-Path -LiteralPath $current) {
            if (((Get-Item -LiteralPath $current -Force).Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Обновление остановлено: обнаружена ссылка вместо обычного файла или папки: $current"
            }
        }
    }
    return $current
}

function Get-SafeArchivePath([string] $Path) {
    if ([string]::IsNullOrEmpty($Path) -or $Path.Contains('\') -or $Path.StartsWith('/')) {
        throw "Недопустимый путь в архиве: $Path"
    }
    $trimmed = $Path.TrimEnd('/')
    foreach ($part in ($trimmed -split '/')) {
        if ([string]::IsNullOrEmpty($part) -or $part -eq '.' -or $part -eq '..' -or
            $part -match '[\x00-\x1f<>:"|?*]' -or $part -match '[. ]$' -or
            $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            throw "Недопустимый путь в архиве: $Path"
        }
    }
    return $trimmed
}

function Expand-ProjectArchive([string] $ArchivePath, [string] $Stage) {
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        if ($archive.Entries.Count -gt 4000) { throw 'В архиве слишком много файлов.' }
        $allowedRootFiles = @('.dockerignore', '.env.example', '.gitattributes', '.gitignore',
            'README.md', 'pyproject.toml', 'START_WINDOWS.bat', 'READ_CODE_WINDOWS.bat',
            'REPAIR_WINDOWS.bat', 'UPDATE_WINDOWS.bat', 'CONFIGURE_EMAIL_WINDOWS.bat',
            'START_ANDROID_SERVER_WINDOWS.bat')
        $allowedDirectories = @('backend', 'client', 'scripts', 'docs', 'deploy', '.github')
        $files = [System.Collections.Generic.List[string]]::new()
        $paths = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $root = $null
        [long] $totalSize = 0
        foreach ($entry in $archive.Entries) {
            $safe = Get-SafeArchivePath $entry.FullName
            $parts = $safe -split '/'
            if ($null -eq $root) {
                $root = $parts[0]
                if ($root -notmatch '^ssdsad-[A-Za-z0-9_-]+$') { throw 'Архив не соответствует репозиторию ssdsad.' }
            }
            if ($parts[0] -cne $root) { throw 'В архиве обнаружены разные корневые папки.' }
            $unixMode = ($entry.ExternalAttributes -shr 16) -band 0xf000
            if ($unixMode -eq 0xa000 -or ($entry.ExternalAttributes -band 0x400) -ne 0) {
                throw "Ссылки в архиве запрещены: $safe"
            }
            if ($parts.Count -eq 1) {
                if (-not $entry.FullName.EndsWith('/')) { throw 'Неверная структура корня архива.' }
                continue
            }
            $relative = [string]::Join('/', $parts[1..($parts.Count - 1)])
            if ($relative -match '(?i)(^|/)(\.data|\.git|\.codex|\.agents|[^/]*venv|__pycache__|\.pytest_cache|\.ruff_cache|node_modules)(/|$)' -or
                ($relative -match '(?i)(^|/)\.env(?:\.|/|$)' -and $relative -cne '.env.example') -or
                $relative -match '(?i)\.(?:sqlite3?|db|pyc|pyo)$') {
                throw "В архиве обнаружен путь с пользовательскими данными: $relative"
            }
            if ($parts.Count -eq 2 -and -not $entry.FullName.EndsWith('/')) {
                if ($allowedRootFiles -cnotcontains $relative) { throw "Неожиданный файл в корне архива: $relative" }
            }
            elseif ($allowedDirectories -cnotcontains $parts[1]) {
                throw "Неожиданная папка в архиве: $relative"
            }
            if (-not $paths.Add($relative)) { throw "Повторяющийся путь в архиве: $relative" }
            if ($entry.FullName.EndsWith('/')) { continue }
            $totalSize += $entry.Length
            if ($entry.Length -gt 67108864 -or $totalSize -gt 134217728) { throw 'Архив превышает допустимый размер.' }
            $destination = Assert-RegularPath $Stage $relative
            [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($destination)) > $null
            $inputStream = $entry.Open()
            $outputStream = $null
            try {
                $outputStream = [System.IO.File]::Open($destination, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                $inputStream.CopyTo($outputStream)
            }
            finally {
                if ($null -ne $outputStream) { $outputStream.Dispose() }
                $inputStream.Dispose()
            }
            if ((Get-Item -LiteralPath $destination -Force).Length -ne $entry.Length) { throw "Неполный файл в архиве: $relative" }
            $files.Add($relative)
        }
        foreach ($required in @('START_WINDOWS.bat', 'CONFIGURE_EMAIL_WINDOWS.bat', 'README.md', 'pyproject.toml',
                'client/main.py', 'client/todaygo/theme.py', 'backend/app/main.py',
                'scripts/bootstrap_windows.ps1', 'scripts/launch_windows.py')) {
            if (-not $files.Contains($required)) { throw "В архиве отсутствует обязательный файл: $required" }
        }
        $readme = [System.IO.File]::ReadAllText((Join-Path $Stage 'README.md'), [System.Text.Encoding]::UTF8)
        if ($readme -notmatch 'Сегодня идём|TodayGo') { throw 'README не соответствует проекту Сегодня идём.' }
        return ,$files.ToArray()
    }
    finally { $archive.Dispose() }
}

function Write-AtomicFile([string] $Source, [string] $Destination) {
    $parent = [System.IO.Path]::GetDirectoryName($Destination)
    $identifier = [Guid]::NewGuid().ToString('N')
    $temporary = Join-Path $parent ('.todaygo-update-new-' + $identifier + '.tmp')
    $previous = Join-Path $parent ('.todaygo-update-old-' + $identifier + '.tmp')
    try {
        [System.IO.File]::Copy($Source, $temporary, $false)
        if ([System.IO.File]::Exists($Destination)) {
            # PowerShell 5.1 converts a null backup path to an invalid empty string.
            [System.IO.File]::Replace($temporary, $Destination, $previous, $false)
        }
        else { [System.IO.File]::Move($temporary, $Destination) }
    }
    finally {
        foreach ($created in @($temporary, $previous)) {
            if ([System.IO.File]::Exists($created)) { [System.IO.File]::Delete($created) }
        }
    }
}

function Write-UpdateManifest([string] $Backup, $Manifest) {
    $text = $Manifest | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText((Join-Path $Backup 'manifest.json'), $text, [System.Text.UTF8Encoding]::new($false))
}

function Update-ProjectFromZip([string] $Project, [string] $ArchivePath, [string] $Stage) {
    $files = Expand-ProjectArchive $ArchivePath $Stage
    $changes = [System.Collections.Generic.List[object]]::new()
    foreach ($relative in $files) {
        $destination = Assert-RegularPath $Project $relative
        if ([System.IO.Directory]::Exists($destination)) { throw "Вместо файла обнаружена папка: $relative" }
        $parent = [System.IO.Path]::GetDirectoryName($destination)
        while (-not [System.IO.Directory]::Exists($parent)) {
            if ([System.IO.File]::Exists($parent)) { throw "Вместо папки обнаружен файл: $parent" }
            $parent = [System.IO.Path]::GetDirectoryName($parent)
        }
        $stageFile = Join-Path $Stage $relative
        $nextHash = Get-FileDigest $stageFile
        $exists = [System.IO.File]::Exists($destination)
        $previousHash = $null
        if ($exists) { $previousHash = Get-FileDigest $destination }
        if (-not $exists -or $previousHash -cne $nextHash) {
            $changes.Add([PSCustomObject]@{ Path = $relative; Existed = $exists; OriginalSHA256 = $previousHash; NewSHA256 = $nextHash })
        }
    }
    if ($changes.Count -eq 0) {
        Write-Host 'Уже установлены актуальные файлы. Ничего менять не требуется.' -ForegroundColor Green
        return
    }
    $identifier = [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
    $backupRelative = '.data/updates/' + $identifier
    $backup = Assert-RegularPath $Project $backupRelative
    [System.IO.Directory]::CreateDirectory($backup) > $null
    $manifest = [ordered]@{
        State = 'preparing'; Source = 'https://github.com/dhdhsbdbd132-sys/ssdsad/tree/main';
        ArchiveSHA256 = Get-FileDigest $ArchivePath; Created = [DateTime]::UtcNow.ToString('o'); Files = $changes.ToArray()
    }
    Write-UpdateManifest $backup $manifest
    # Every original is copied and verified before the first project source write.
    foreach ($change in $changes) {
        if ($change.Existed) {
            $destination = Assert-RegularPath $Project $change.Path
            if ((Get-FileDigest $destination) -cne $change.OriginalSHA256) { throw "Файл изменился во время подготовки: $($change.Path)" }
            $saved = Join-Path (Join-Path $backup 'files') $change.Path
            [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($saved)) > $null
            [System.IO.File]::Copy($destination, $saved, $false)
            if ((Get-FileDigest $saved) -cne $change.OriginalSHA256) { throw "Не удалось проверить резервную копию: $($change.Path)" }
        }
    }
    $manifest.State = 'prepared'
    Write-UpdateManifest $backup $manifest
    Write-Host "Резервная копия: $backup"
    $applied = [System.Collections.Generic.List[object]]::new()
    $createdDirectories = [System.Collections.Generic.List[string]]::new()
    try {
        foreach ($change in $changes) {
            $destination = Assert-RegularPath $Project $change.Path
            if ($change.Existed) {
                if (-not [System.IO.File]::Exists($destination) -or (Get-FileDigest $destination) -cne $change.OriginalSHA256) {
                    throw "Исходный файл изменился во время обновления: $($change.Path)"
                }
            }
            elseif (Test-Path -LiteralPath $destination) { throw "Появился новый файл во время обновления: $($change.Path)" }
            $parent = [System.IO.Path]::GetDirectoryName($destination)
            $missing = [System.Collections.Generic.List[string]]::new()
            while (-not [System.IO.Directory]::Exists($parent)) {
                $missing.Add($parent)
                $parent = [System.IO.Path]::GetDirectoryName($parent)
            }
            for ($index = $missing.Count - 1; $index -ge 0; $index--) {
                [System.IO.Directory]::CreateDirectory($missing[$index]) > $null
                $createdDirectories.Add($missing[$index])
            }
            # Register before the atomic write so failures after replacement are rolled back too.
            $applied.Add($change)
            Write-AtomicFile (Join-Path $Stage $change.Path) $destination
            if ((Get-FileDigest $destination) -cne $change.NewSHA256) { throw "Проверка обновлённого файла не прошла: $($change.Path)" }
        }
        $manifest.State = 'committed'
        Write-UpdateManifest $backup $manifest
        Write-Host ("Обновлено файлов: " + $changes.Count) -ForegroundColor Green
    }
    catch {
        $reason = $_.Exception.Message
        $rollbackErrors = [System.Collections.Generic.List[string]]::new()
        for ($index = $applied.Count - 1; $index -ge 0; $index--) {
            $change = $applied[$index]
            try {
                $destination = Assert-RegularPath $Project $change.Path
                if ($change.Existed) {
                    Write-AtomicFile (Join-Path (Join-Path $backup 'files') $change.Path) $destination
                    if ((Get-FileDigest $destination) -cne $change.OriginalSHA256) { throw 'Восстановленный файл не прошёл проверку.' }
                }
                elseif ([System.IO.File]::Exists($destination)) {
                    if ((Get-FileDigest $destination) -cne $change.NewSHA256) { throw 'Новый файл был изменён вне обновления; он сохранён.' }
                    [System.IO.File]::Delete($destination)
                }
            }
            catch { $rollbackErrors.Add($change.Path + ': ' + $_.Exception.Message) }
        }
        for ($index = $createdDirectories.Count - 1; $index -ge 0; $index--) {
            $directory = $createdDirectories[$index]
            if ([System.IO.Directory]::Exists($directory) -and [System.IO.Directory]::GetFileSystemEntries($directory).Length -eq 0) {
                try { [System.IO.Directory]::Delete($directory, $false) } catch { }
            }
        }
        $manifest.State = 'rolled_back'
        if ($rollbackErrors.Count -gt 0) { $manifest.State = 'rollback_incomplete' }
        try { Write-UpdateManifest $backup $manifest } catch { }
        if ($rollbackErrors.Count -gt 0) {
            throw ("Обновление остановлено: $reason. Не все файлы удалось восстановить. Резервная копия: $backup. " + [string]::Join('; ', $rollbackErrors.ToArray()))
        }
        throw "Обновление остановлено: $reason. Исходные файлы восстановлены. Резервная копия: $backup"
    }
}

# TODAYGO_UPDATE_MAIN
$working = $null
$launchLock = $null
$exitCode = 1
try {
    if (-not [string]::IsNullOrWhiteSpace($env:TODAYGO_UPDATE_PROJECT)) {
        $project = [System.IO.Path]::GetFullPath($env:TODAYGO_UPDATE_PROJECT)
    }
    else {
        $candidates = [System.Collections.Generic.List[string]]::new()
        $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
        if (-not [string]::IsNullOrWhiteSpace($desktop)) { $candidates.Add((Join-Path $desktop 'ssdsad-main')) }
        if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) { $candidates.Add((Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'ssdsad-main')) }
        if (-not [string]::IsNullOrWhiteSpace($env:TODAYGO_UPDATE_FILE)) { $candidates.Add([System.IO.Path]::GetDirectoryName($env:TODAYGO_UPDATE_FILE)) }
        $project = $null
        foreach ($candidate in $candidates) {
            if ([System.IO.File]::Exists((Join-Path $candidate 'START_WINDOWS.bat')) -and
                [System.IO.File]::Exists((Join-Path $candidate 'client/main.py')) -and
                [System.IO.File]::Exists((Join-Path $candidate 'backend/app/main.py'))) {
                $project = [System.IO.Path]::GetFullPath($candidate)
                break
            }
        }
        if ($null -eq $project) { throw 'Проект не найден. Поместите UPDATE_WINDOWS.bat рядом с START_WINDOWS.bat. Также можно перетащить папку проекта на UPDATE_WINDOWS.bat.' }
    }
    foreach ($required in @('START_WINDOWS.bat', 'client/main.py', 'backend/app/main.py')) {
        $path = Assert-RegularPath $project $required
        if (-not [System.IO.File]::Exists($path)) { throw "В указанной папке нет проекта Сегодня идём: $project" }
    }
    Write-Host "Обновляем проект: $project"
    $data = Assert-RegularPath $project '.data'
    [System.IO.Directory]::CreateDirectory($data) > $null
    $lockPath = Assert-RegularPath $project '.data/windows-launch.lock'
    try {
        # FileShare.None and the same byte-range lock exclude the Python Windows launcher.
        $launchLock = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        if ($launchLock.Length -eq 0) { $launchLock.WriteByte(49); $launchLock.Flush() }
        $launchLock.Lock(0, 1)
    }
    catch { throw 'Приложение уже запущено. Закройте его окно и окно START_WINDOWS.bat, затем запустите обновление снова.' }
    Write-Host 'База, почтовые настройки и установленные зависимости сохраняются.'
    $working = Join-Path ([System.IO.Path]::GetTempPath()) ('TodayGo-update-' + [Guid]::NewGuid().ToString('N'))
    [System.IO.Directory]::CreateDirectory($working) > $null
    $archivePath = Join-Path $working 'main.zip'
    $stage = Join-Path $working 'source'
    [System.IO.Directory]::CreateDirectory($stage) > $null
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Write-Host 'Скачиваем актуальные исходники с GitHub...'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://codeload.github.com/dhdhsbdbd132-sys/ssdsad/zip/refs/heads/main' -OutFile $archivePath -TimeoutSec 90 -ErrorAction Stop
    if ((Get-Item -LiteralPath $archivePath).Length -gt 67108864) { throw 'Скачанный архив превышает допустимый размер.' }
    Update-ProjectFromZip $project $archivePath $stage
    Write-Host 'Обновление завершено.' -ForegroundColor Green
    Write-Host "1. Откройте CONFIGURE_EMAIL_WINDOWS.bat в папке: $project"
    Write-Host '2. Введите адрес Mail.ru и пароль приложения локально в открывшемся окне.'
    Write-Host '3. После настройки запустите START_WINDOWS.bat в той же папке.'
    $exitCode = 0
}
catch {
    Write-Host ('Обновление не выполнено: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Скопируйте текст ошибки из этого окна и отправьте его для проверки.'
}
finally {
    if ($null -ne $launchLock) { $launchLock.Dispose() }
    # This GUID folder was created by this updater under TEMP; never remove project data.
    if ($null -ne $working -and [System.IO.Directory]::Exists($working)) {
        try { [System.IO.Directory]::Delete($working, $true) } catch { }
    }
}
exit $exitCode
