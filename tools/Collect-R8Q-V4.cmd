@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Run next to adb.exe. This collector never reboots, formats or deletes phone logs.
set "R8Q_TOOL_DIR=%~dp0"
set "R8Q_ADB=%R8Q_TOOL_DIR%adb.exe"
set "R8Q_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%R8Q_ADB%" goto missing_adb
if not exist "%R8Q_PS%" goto missing_powershell
pushd "%R8Q_TOOL_DIR%" || goto missing_directory

:choose_output
set "R8Q_OUTPUT_DIR=%R8Q_TOOL_DIR%R8Q-LOGS-V4-%RANDOM%-%RANDOM%"
if exist "%R8Q_OUTPUT_DIR%" goto choose_output
if exist "%R8Q_OUTPUT_DIR%.zip" goto choose_output
if exist "%R8Q_OUTPUT_DIR%-PARTIAL.zip" goto choose_output
mkdir "%R8Q_OUTPUT_DIR%"
if errorlevel 1 goto output_failed
set "R8Q_STATUS=%R8Q_OUTPUT_DIR%\COLLECTION-STATUS.txt"
set "R8Q_READY_INFO=%R8Q_OUTPUT_DIR%\_ready-device.tmp"
set "R8Q_COMMAND_LOG=%R8Q_OUTPUT_DIR%\_command-output.tmp"
set "R8Q_COLLECT_PARTIAL=0"
set "R8Q_OPTIONAL=0"
set "R8Q_SERIAL="
>"%R8Q_STATUS%" echo R8Q recovery evidence collection. No phone logs are deleted or cleared.
echo Checking one ready ADB device and recovery mode...
"%R8Q_ADB%" start-server >"%R8Q_COMMAND_LOG%" 2>&1
set "R8Q_COMMAND_EXIT=%ERRORLEVEL%"
type "%R8Q_COMMAND_LOG%"
type "%R8Q_COMMAND_LOG%" >>"%R8Q_STATUS%"
if not "%R8Q_COMMAND_EXIT%"=="0" goto readiness_failed
rem All paths enter PowerShell through environment variables, never as code.
"%R8Q_PS%" -NoProfile -Command "try { $lines = @(& $env:R8Q_ADB devices 2>&1); if ($LASTEXITCODE -ne 0) { throw 'adb devices failed.' }; $ready = @($lines | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ -match '^([A-Za-z0-9._:-]+)\s+(device|recovery)$' }); if ($ready.Count -ne 1) { throw ('Expected exactly one ready ADB device; found ' + $ready.Count + '. Disconnect extra devices, leave ADB Sideload, and check the USB connection in recovery.') }; $serial = ($ready[0] -split '\s+')[0]; $mode = ((& $env:R8Q_ADB -s $serial shell getprop ro.bootmode 2>&1) | Out-String).Trim(); if ($LASTEXITCODE -ne 0) { throw 'Could not read recovery boot mode.' }; $fox = ((& $env:R8Q_ADB -s $serial shell getprop ro.orangefox.boot 2>&1) | Out-String).Trim(); if ($LASTEXITCODE -ne 0) { throw 'Could not read recovery identity.' }; if ($mode -ne 'recovery' -and $fox -ne '1') { throw 'The selected device is not confirmed in recovery/OrangeFox. Return to recovery first.' }; [IO.File]::WriteAllText($env:R8Q_READY_INFO, $serial, [Text.Encoding]::ASCII); Write-Output 'One ready device verified in recovery/OrangeFox.'; exit 0 } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }" >"%R8Q_COMMAND_LOG%" 2>&1
set "R8Q_COMMAND_EXIT=%ERRORLEVEL%"
type "%R8Q_COMMAND_LOG%"
type "%R8Q_COMMAND_LOG%" >>"%R8Q_STATUS%"
if not "%R8Q_COMMAND_EXIT%"=="0" goto readiness_failed
if not exist "%R8Q_READY_INFO%" goto readiness_failed
set /p "R8Q_SERIAL=" <"%R8Q_READY_INFO%"
if not defined R8Q_SERIAL goto readiness_failed
rem Delete only this host-side readiness selector; no adb rm is used.
del /q "%R8Q_READY_INFO%" >nul 2>&1

set "R8Q_REMOTE=/tmp/recovery.log"
set "R8Q_LOCAL=%R8Q_OUTPUT_DIR%\recovery.log"
call :pull_file

set "R8Q_REMOTE=/proc/last_kmsg"
set "R8Q_LOCAL=%R8Q_OUTPUT_DIR%\last_kmsg"
call :pull_file

set "R8Q_MOUNT_POINT=/metadata"
call :mount_if_needed
set "R8Q_REMOTE=/metadata/r8q-bootdiag-v4"
set "R8Q_LOCAL=%R8Q_OUTPUT_DIR%\r8q-bootdiag-v4"
call :pull_file

set "R8Q_MOUNT_POINT=/vendor"
call :mount_if_needed
set "R8Q_REMOTE=/vendor/etc/ueventd.rc"
set "R8Q_LOCAL=%R8Q_OUTPUT_DIR%\ueventd-aplicado.rc"
call :pull_file

rem Pstore is optional; absence does not invalidate the other collected files.
set "R8Q_OPTIONAL=1"
set "R8Q_REMOTE=/sys/fs/pstore"
set "R8Q_LOCAL=%R8Q_OUTPUT_DIR%\pstore"
call :pull_file
set "R8Q_OPTIONAL=0"
rem Command output has already been appended to COLLECTION-STATUS.txt.
del /q "%R8Q_COMMAND_LOG%" >nul 2>&1

echo.
echo Checking collected files and creating the archive...
"%R8Q_PS%" -NoProfile -Command "try { $ErrorActionPreference = 'Stop'; $dir = $env:R8Q_OUTPUT_DIR; $recovery = Join-Path $dir 'recovery.log'; if (-not (Test-Path -LiteralPath $recovery -PathType Leaf)) { throw 'Missing critical recovery.log. No archive will be created.' }; if ((Get-Item -LiteralPath $recovery).Length -le 0) { throw 'Critical recovery.log is empty. No archive will be created.' }; $files = @(Get-ChildItem -LiteralPath $dir -Recurse -File -Force); if ($files.Count -eq 0) { throw 'The output folder contains no files. No archive will be created.' }; $partial = $env:R8Q_COLLECT_PARTIAL -ne '0'; $last = Join-Path $dir 'last_kmsg'; if (-not (Test-Path -LiteralPath $last -PathType Leaf)) { $partial = $true } elseif ((Get-Item -LiteralPath $last).Length -le 0) { $partial = $true }; $capture = Join-Path $dir 'r8q-bootdiag-v4'; $captureFiles = @(Get-ChildItem -LiteralPath $capture -Recurse -File -ErrorAction SilentlyContinue); if ($captureFiles.Count -eq 0) { $partial = $true }; if ($partial) { $label = 'PARTIAL'; $zip = $dir + '-PARTIAL.zip' } else { $label = 'COMPLETE'; $zip = $dir + '.zip' }; if (Test-Path -LiteralPath $zip) { throw 'Archive path already exists; refusing to replace it.' }; [IO.File]::AppendAllText($env:R8Q_STATUS, ('Archive label: ' + $label + [Environment]::NewLine)); Compress-Archive -LiteralPath $dir -DestinationPath $zip -CompressionLevel Optimal -ErrorAction Stop; Add-Type -AssemblyName System.IO.Compression.FileSystem; $archive = [IO.Compression.ZipFile]::OpenRead($zip); try { $critical = @($archive.Entries | Where-Object { $_.FullName.Replace([char]92,[char]47) -match '(^|/)recovery\.log$' -and $_.Length -gt 0 }); if ($critical.Count -ne 1) { throw 'Archive verification failed: nonempty recovery.log was not found exactly once.' } } finally { $archive.Dispose() }; Write-Output ('Created ' + $label + ' archive:'); Write-Output $zip; if ($partial) { Write-Output 'Some requested evidence was unavailable. The folder and command errors are preserved. This is not a complete collection.'; exit 2 }; Write-Output 'Collection completed. This does not mean Android booted successfully.'; exit 0 } catch { [Console]::Error.WriteLine($_.Exception.Message); Write-Output ('Partial folder preserved: ' + $env:R8Q_OUTPUT_DIR); exit 1 }"
if errorlevel 3 goto zip_failed
if errorlevel 2 goto partial_done
if errorlevel 1 goto zip_failed
set "R8Q_EXIT=0"
echo Send the ZIP named above privately. Keep the folder until it has been reviewed.
goto finish

:pull_file
echo.
echo Reading %R8Q_REMOTE%
>>"%R8Q_STATUS%" echo INPUT %R8Q_REMOTE%
"%R8Q_ADB%" -s "%R8Q_SERIAL%" pull "%R8Q_REMOTE%" "%R8Q_LOCAL%" >"%R8Q_COMMAND_LOG%" 2>&1
set "R8Q_COMMAND_EXIT=%ERRORLEVEL%"
type "%R8Q_COMMAND_LOG%"
type "%R8Q_COMMAND_LOG%" >>"%R8Q_STATUS%"
>>"%R8Q_STATUS%" echo adb pull exit: %R8Q_COMMAND_EXIT%
if "%R8Q_COMMAND_EXIT%"=="0" exit /b 0
if "%R8Q_OPTIONAL%"=="1" goto optional_unavailable
set "R8Q_COLLECT_PARTIAL=1"
echo WARNING: this pull failed. Its error and any partial files were preserved.
exit /b 1

:optional_unavailable
echo Optional pstore evidence is unavailable. Other evidence is still preserved.
exit /b 0

:mount_if_needed
echo.
echo Checking the ordinary recovery mount for %R8Q_MOUNT_POINT%
>>"%R8Q_STATUS%" echo MOUNT CHECK %R8Q_MOUNT_POINT%
"%R8Q_ADB%" -s "%R8Q_SERIAL%" shell "if grep -q ' %R8Q_MOUNT_POINT% ' /proc/mounts; then exit 0; else mount %R8Q_MOUNT_POINT%; fi" >"%R8Q_COMMAND_LOG%" 2>&1
set "R8Q_COMMAND_EXIT=%ERRORLEVEL%"
type "%R8Q_COMMAND_LOG%"
type "%R8Q_COMMAND_LOG%" >>"%R8Q_STATUS%"
>>"%R8Q_STATUS%" echo recovery mount exit: %R8Q_COMMAND_EXIT%
if "%R8Q_COMMAND_EXIT%"=="0" exit /b 0
set "R8Q_COLLECT_PARTIAL=1"
echo WARNING: mount check failed. The following pull may also be unavailable.
exit /b 1

:partial_done
set "R8Q_EXIT=2"
echo.
echo PARTIAL collection only. Send the PARTIAL ZIP and mention the displayed errors.
goto finish

:readiness_failed
set "R8Q_EXIT=1"
echo.
echo ADB/recovery verification failed. No archive was created.
echo Any diagnostic output remains in:
echo "%R8Q_OUTPUT_DIR%"
goto finish

:zip_failed
set "R8Q_EXIT=1"
echo.
echo Archive creation or verification failed. Do not treat an archive as complete.
echo The partial output folder remains available:
echo "%R8Q_OUTPUT_DIR%"
goto finish

:output_failed
set "R8Q_EXIT=1"
echo Could not create a fresh output folder next to this script.
goto finish

:finish
echo.
pause
popd
exit /b %R8Q_EXIT%

:missing_adb
echo Put Collect-R8Q-V4.cmd in the SAME folder as adb.exe, then run it again.
pause
exit /b 1

:missing_powershell
echo Windows PowerShell was not found. Windows 10 or 11 with PowerShell 5 is required.
pause
exit /b 1

:missing_directory
echo Could not open the folder containing this script.
pause
exit /b 1
