# Wrapper invoked by Windows Task Scheduler: once daily at the local-clock
# equivalent of 8:30am ET, or (via the task's StartWhenAvailable setting)
# as soon as the machine is next turned on if it was off/asleep at that
# time. Decides whether it's actually appropriate to run the premarket
# gappers scan, then runs it if so. The weekday/window/already-ran checks
# below are a safety net independent of exactly when Task Scheduler invokes
# this — e.g. if StartWhenAvailable fires a catch-up run well into the
# afternoon, the market-close check still catches that and skips it.
#
# Conditions, all of which must hold:
#   - Weekday (Mon-Fri) in America/New_York
#   - Current time in America/New_York is >= 8:30 AM
#   - Current time in America/New_York is < 4:00 PM (market close) --
#     past this, premarket data is considered stale and we skip rather
#     than produce a misleading "premarket" report from mid-afternoon data
#   - Today's report file doesn't already exist (so a normal 8:30am run
#     and a later catch-up run on the same day never double-fire)
#
# This does NOT try to keep the machine awake. If the laptop is asleep at
# 8:30am, nothing runs; Task Scheduler's StartWhenAvailable setting causes
# the next-missed occurrence to fire once the machine is next on and this
# script is invoked, at which point the checks above decide whether it's
# still an appropriate time to run.

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$logFile = Join-Path $scriptDir "wrapper.log"
function Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
    Add-Content -Path $logFile -Value $line
}

try {
    $etNow = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, "Eastern Standard Time")
} catch {
    Log "ERROR: failed to resolve Eastern Standard Time zone: $_"
    exit 1
}

$dow = $etNow.DayOfWeek
if ($dow -eq [DayOfWeek]::Saturday -or $dow -eq [DayOfWeek]::Sunday) {
    Log "Skip: weekend ($dow) in ET."
    exit 0
}

$todayEt = $etNow.ToString("yyyy-MM-dd")
$outfile = Join-Path $scriptDir "premarket_gappers_$todayEt.json"
if (Test-Path $outfile) {
    Log "Skip: already ran today ($outfile exists)."
    exit 0
}

$marketOpenCheck = New-Object DateTime($etNow.Year, $etNow.Month, $etNow.Day, 8, 30, 0)
$marketCloseCheck = New-Object DateTime($etNow.Year, $etNow.Month, $etNow.Day, 16, 0, 0)

if ($etNow -lt $marketOpenCheck) {
    Log "Skip: before 8:30am ET (current ET: $($etNow.ToString('HH:mm')))."
    exit 0
}
if ($etNow -ge $marketCloseCheck) {
    Log "Skip: at/after market close (4:00pm ET); premarket data would be stale (current ET: $($etNow.ToString('HH:mm')))."
    exit 0
}

Log "Conditions met (ET $($etNow.ToString('yyyy-MM-dd HH:mm')), $dow). Running premarket gappers scan..."

$bash = "C:\Program Files\Git\bin\bash.exe"
if (-not (Test-Path $bash)) {
    $bash = (Get-Command bash.exe -ErrorAction SilentlyContinue).Source
}
if (-not $bash) {
    Log "ERROR: could not locate bash.exe"
    exit 1
}

$jqDir = "C:\Users\User\AppData\Local\Microsoft\WinGet\Packages\jqlang.jq_Microsoft.Winget.Source_8wekyb3d8bbwe"
$bashCmd = "export PATH=`"`$PATH:$($jqDir -replace '\\','/' -replace '^C:','/c')`"; cd '$($scriptDir -replace '\\','/' -replace '^C:','/c')'; ./premarket_gappers.sh"

& $bash -lc $bashCmd *>> $logFile
$exitCode = $LASTEXITCODE

Log "premarket_gappers.sh exited with code $exitCode."
exit $exitCode
