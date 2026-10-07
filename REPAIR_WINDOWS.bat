@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "TODAYGO_REPAIR_FILE=%~f0"
if not "%~1"=="" set "TODAYGO_REPAIR_PROJECT=%~1"
echo TodayGo - repair button animation
powershell.exe -NoLogo -NoProfile -Command "$body=[System.IO.File]::ReadAllText($env:TODAYGO_REPAIR_FILE,[System.Text.Encoding]::UTF8); $marker=[regex]::Match($body,'(?m)^# TODAYGO_REPAIR_POWERSHELL\r?\n'); if(-not $marker.Success){throw 'Embedded repair script is missing.'}; & ([scriptblock]::Create($body.Substring($marker.Index+$marker.Length)))"
set "TODAYGO_REPAIR_EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %TODAYGO_REPAIR_EXIT_CODE%
# TODAYGO_REPAIR_POWERSHELL
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$temporary = $null

function Get-ThemePath([string] $Project) {
    return Join-Path (Join-Path (Join-Path $Project 'client') 'todaygo') 'theme.py'
}

try {
    if (-not [string]::IsNullOrWhiteSpace($env:TODAYGO_REPAIR_PROJECT)) {
        $project = [System.IO.Path]::GetFullPath($env:TODAYGO_REPAIR_PROJECT)
        if (-not [System.IO.File]::Exists((Get-ThemePath $project))) {
            throw "В указанной папке нет client/todaygo/theme.py: $project"
        }
    }
    else {
        $candidates = [System.Collections.Generic.List[string]]::new()
        $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop)
        if (-not [string]::IsNullOrWhiteSpace($desktop)) {
            $candidates.Add((Join-Path $desktop 'ssdsad-main'))
        }
        if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            $candidates.Add((Join-Path (Join-Path $env:USERPROFILE 'Desktop') 'ssdsad-main'))
        }
        if (-not [string]::IsNullOrWhiteSpace($env:TODAYGO_REPAIR_FILE)) {
            $candidates.Add([System.IO.Path]::GetDirectoryName($env:TODAYGO_REPAIR_FILE))
        }
        $project = $null
        foreach ($candidate in $candidates) {
            if ([System.IO.File]::Exists((Get-ThemePath $candidate))) {
                $project = [System.IO.Path]::GetFullPath($candidate)
                break
            }
        }
        if ($null -eq $project) {
            throw 'Проект не найден. Поместите REPAIR_WINDOWS.bat в папку проекта рядом с START_WINDOWS.bat и запустите снова. Или перетащите папку проекта на REPAIR_WINDOWS.bat.'
        }
    }

    Write-Host "Исправляем проект: $project"
    Write-Host 'Закройте окно приложения перед исправлением. База данных и настройки сохраняются.'
    $theme = Get-ThemePath $project
    $originalBytes = [System.IO.File]::ReadAllBytes($theme)
    $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $source = $utf8.GetString($originalBytes)
    $actionPattern = '(?ms)^class Action\(Button\):[ \t]*\r?\n.*?(?=^(?:class |def |[A-Za-z_]\w*[ \t]*=)|\z)'
    $actions = [regex]::Matches($source, $actionPattern)
    if ($actions.Count -ne 1) {
        throw 'Файл theme.py отличается от ожидаемого: не найден единственный класс Action(Button). Файлы не изменены.'
    }
    $action = $actions[0]
    $legacyProperty = '(?m)^    press[ \t]*=[ \t]*NumericProperty\([ \t]*0[ \t]*\)[ \t]*(?:#[^\r\n]*)?\r?$'
    $newProperty = '(?m)^    press_progress[ \t]*=[ \t]*NumericProperty\([ \t]*0[ \t]*\)[ \t]*(?:#[^\r\n]*)?\r?$'
    $oldCount = [regex]::Matches($action.Value, $legacyProperty).Count
    $newCount = [regex]::Matches($action.Value, $newProperty).Count
    $legacyReferences = '\bself\.press\b|\bAnimation\(press[ \t]*=|\bpress[ \t]*=self\.redraw\b|\bAnimation\.cancel_all\(self,[^\r\n]*["'']press["'']'
    $requiredReferences = @(
        $newProperty,
        '\bself\.press_progress\b',
        '\bAnimation\(press_progress[ \t]*=',
        '\bpress_progress[ \t]*=self\.redraw\b'
    )
    $hasRequiredReferences = $true
    foreach ($reference in $requiredReferences) {
        if (-not [regex]::IsMatch($action.Value, $reference)) {
            $hasRequiredReferences = $false
        }
    }
    if ($oldCount -eq 0 -and $newCount -eq 1 -and -not [regex]::IsMatch($action.Value, $legacyReferences) -and $hasRequiredReferences) {
        Write-Host 'Эта ошибка уже исправлена. Файлы не изменены.' -ForegroundColor Green
        Write-Host "Запустите START_WINDOWS.bat именно из папки: $project"
        exit 0
    }
    if ($oldCount -ne 1 -or $newCount -ne 0) {
        throw 'В theme.py не найден ожидаемый старый параметр press = NumericProperty(0). Автоматическое исправление не применено.'
    }

    $patchedAction = [regex]::Replace($action.Value, '\bpress\b', 'press_progress')
    foreach ($reference in $requiredReferences) {
        if (-not [regex]::IsMatch($patchedAction, $reference)) {
            throw 'Структура анимации отличается от ожидаемой. Автоматическое исправление не применено.'
        }
    }
    if ([regex]::IsMatch($patchedAction, $legacyReferences) -or [regex]::IsMatch($patchedAction, $legacyProperty)) {
        throw 'Проверка исправления не прошла. Файлы не изменены.'
    }
    $patchedSource = $source.Substring(0, $action.Index) + $patchedAction + $source.Substring($action.Index + $action.Length)
    $patchedBytes = $utf8.GetBytes($patchedSource)
    if ([Convert]::ToBase64String([System.IO.File]::ReadAllBytes($theme)) -cne [Convert]::ToBase64String($originalBytes)) {
        throw 'Файл theme.py изменился во время проверки. Закройте приложение и редактор, затем повторите исправление.'
    }

    $repairs = Join-Path (Join-Path $project '.data') 'repairs'
    [System.IO.Directory]::CreateDirectory($repairs) > $null
    $identifier = [Guid]::NewGuid().ToString('N')
    $backup = Join-Path $repairs ('theme.py.before-press-repair-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + $identifier + '.bak')
    $temporary = Join-Path ([System.IO.Path]::GetDirectoryName($theme)) ('.todaygo-theme-repair-' + $identifier + '.tmp')
    [System.IO.File]::WriteAllBytes($temporary, $patchedBytes)
    [System.IO.File]::Replace($temporary, $theme, $backup, $false)
    $temporary = $null
    if ([Convert]::ToBase64String([System.IO.File]::ReadAllBytes($theme)) -cne [Convert]::ToBase64String($patchedBytes)) {
        throw "Файл изменился после исправления. Резервная копия сохранена: $backup"
    }
    Write-Host 'Исправлено: кнопки больше не конфликтуют с событием on_press.' -ForegroundColor Green
    Write-Host "Резервная копия: $backup"
    Write-Host "Теперь запустите START_WINDOWS.bat из папки: $project"
    exit 0
}
catch {
    if ($null -ne $temporary -and [System.IO.File]::Exists($temporary)) {
        try { [System.IO.File]::Delete($temporary) } catch { }
    }
    Write-Host ('Исправление не выполнено: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Скопируйте текст ошибки из этого окна и отправьте его для проверки.'
    exit 1
}
