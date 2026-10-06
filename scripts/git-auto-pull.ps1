# Keeps E:\Leprastack in sync with GitHub (origin/main) and deploys whatever
# changed. Runs on a schedule via Windows Task Scheduler (registered as the
# scheduled task LepraStack-GitAutoPull).
#
# Pull safety: `git pull --ff-only` NEVER creates a merge commit and NEVER
# touches/overwrites local changes. If there are uncommitted local edits
# that would conflict, or history has diverged, the pull just fails
# (logged) and nothing is touched.
#
# Deploy safety: only the sub-app(s) whose files actually changed are
# rebuilt/restarted. For a JS app, the service is only restarted if
# `npm run build` succeeds - a failed build leaves the previous .next/dist
# output (and the currently-running service) untouched, so a broken push
# cannot take the site down, it just logs a failure for a human to look at.
# For a Python app, changed .py files are syntax-checked (py_compile)
# before restarting, for the same reason.
#
# NOT done automatically, on purpose: `pip install` / `npm install` (a
# dependency change needs a human to review before installing), and
# drizzle DB migrations (schema changes must never auto-apply unattended).

$repoPath = 'E:\Leprastack'
$logPath  = Join-Path $repoPath 'logs\git-auto-pull.log'
$nodeDir  = 'C:\Program Files\nodejs'
if ($env:Path -notlike "*$nodeDir*") { $env:Path = "$nodeDir;$env:Path" }

New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logPath -Value "[$ts] $Message"
}

function Invoke-Native {
    param([string]$Exe, [string[]]$ArgList, [string]$WorkDir)
    Push-Location $WorkDir
    try {
        $output = & $Exe @ArgList 2>&1 | Out-String
        return [PSCustomObject]@{ Code = $LASTEXITCODE; Output = $output.Trim() }
    } finally {
        Pop-Location
    }
}

Set-Location $repoPath
$before = git rev-parse HEAD

$fetch = Invoke-Native -Exe 'git' -ArgList @('fetch', 'origin', 'main') -WorkDir $repoPath
if ($fetch.Code -ne 0) {
    Write-Log ("fetch FAILED (exit {0}): {1}" -f $fetch.Code, $fetch.Output)
    exit 1
}

$pull = Invoke-Native -Exe 'git' -ArgList @('pull', '--ff-only', 'origin', 'main') -WorkDir $repoPath
$after = git rev-parse HEAD

if ($pull.Code -ne 0) {
    Write-Log ("pull FAILED (exit {0}): {1}" -f $pull.Code, $pull.Output)
    exit 1
}

if ($before -eq $after) {
    Write-Log "No changes."
    exit 0
}

Write-Log ("Updated {0} -> {1}." -f $before, $after)
$changed = git diff --name-only $before $after

# --- Determine which sub-apps are affected -------------------------------
function Test-Touches {
    param([string]$Prefix)
    return [bool]($changed | Where-Object { $_ -like "$Prefix*" } | Select-Object -First 1)
}

$portalChanged     = (Test-Touches 'src/') -or (Test-Touches 'public/') -or ($changed -contains 'package.json') -or ($changed -contains 'next.config.ts')
$dimpleChanged     = Test-Touches 'lepra-foot-measurement-v2/'
$teleFrontChanged  = Test-Touches 'Lepra-Tele/frontend/'
$teleBackChanged   = Test-Touches 'Lepra-Tele/backend/'
$livelihoodChanged = Test-Touches 'lepra-india-livelihood-support/'
$drizzleChanged    = Test-Touches 'drizzle/'

if ($drizzleChanged) {
    Write-Log "drizzle/ changed - NOT auto-applying migrations. Review and run manually."
}

# --- Deploy helpers --------------------------------------------------------
function Deploy-JsApp {
    param([string]$Name, [string]$Dir, [hashtable]$EnvVars, [string]$Service)

    Write-Log "$Name changed - building..."
    Push-Location $Dir
    try {
        foreach ($key in $EnvVars.Keys) { Set-Item -Path "env:$key" -Value $EnvVars[$key] }
        $build = & npm run build 2>&1 | Out-String
        $code = $LASTEXITCODE
        foreach ($key in $EnvVars.Keys) { Remove-Item -Path "env:$key" -ErrorAction SilentlyContinue }

        if ($code -ne 0) {
            Write-Log ("{0} BUILD FAILED (exit {1}) - leaving {2} running on the old build. Output: {3}" -f $Name, $code, $Service, $build.Trim())
            return
        }
        Write-Log "$Name build OK."
    } finally {
        Pop-Location
    }

    try {
        Restart-Service -Name $Service -ErrorAction Stop
        Write-Log "$Name - restarted $Service."
    } catch {
        Write-Log ("{0} - FAILED to restart {1} - {2}" -f $Name, $Service, $_.Exception.Message)
    }
}

function Deploy-PyApp {
    param([string]$Name, [string]$Service, [string[]]$ChangedFiles)

    $pyFiles = $ChangedFiles | Where-Object { $_ -like '*.py' }
    if ($pyFiles) {
        Write-Log ("{0} changed - checking syntax of {1} file(s)..." -f $Name, $pyFiles.Count)
        foreach ($f in $pyFiles) {
            $full = Join-Path $repoPath $f
            if (-not (Test-Path $full)) { continue } # deleted file
            $check = Invoke-Native -Exe 'python' -ArgList @('-m', 'py_compile', $full) -WorkDir $repoPath
            if ($check.Code -ne 0) {
                Write-Log ("{0} SYNTAX ERROR in {1} - leaving {2} running on the old code. Output: {3}" -f $Name, $f, $Service, $check.Output)
                return
            }
        }
        Write-Log "$Name syntax OK."
    } else {
        Write-Log "$Name changed (non-.py files only) - restarting."
    }

    try {
        Restart-Service -Name $Service -ErrorAction Stop
        Write-Log "$Name - restarted $Service."
    } catch {
        Write-Log ("{0} - FAILED to restart {1} - {2}" -f $Name, $Service, $_.Exception.Message)
    }
}

# --- Run deploys ------------------------------------------------------------
if ($portalChanged) {
    Deploy-JsApp -Name 'Portal' -Dir $repoPath -EnvVars @{} -Service 'LepraPortal'
}
if ($teleFrontChanged) {
    Deploy-JsApp -Name 'Tele-Lepra frontend' -Dir (Join-Path $repoPath 'Lepra-Tele\frontend') `
        -EnvVars @{ TELEMEDICINE_BASE_PATH = '/telemedicine-app/'; VITE_API_BASE = '/telemedicine-api' } `
        -Service 'LepraTelemedicineApp'
}
if ($livelihoodChanged) {
    Deploy-JsApp -Name 'Livelihood' -Dir (Join-Path $repoPath 'lepra-india-livelihood-support') `
        -EnvVars @{ LIVELIHOOD_BASE_PATH = '/livelihood-app/' } `
        -Service 'LepraLivelihoodApp'
}
if ($dimpleChanged) {
    Deploy-PyApp -Name 'DIMPLE' -Service 'LepraDimpleBackend' -ChangedFiles $changed
}
if ($teleBackChanged) {
    Deploy-PyApp -Name 'Tele-Lepra backend' -Service 'LepraTelemedicineBackend' -ChangedFiles $changed
}

if (-not ($portalChanged -or $teleFrontChanged -or $livelihoodChanged -or $dimpleChanged -or $teleBackChanged)) {
    Write-Log "Changed files do not touch any deployable app (e.g. docs/config only) - nothing to deploy."
}
