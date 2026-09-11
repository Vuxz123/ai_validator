param(
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Branch,
    [Parameter(Mandatory)][string]$BuildScript,
    [string]$Profile = 'default',
    [string]$Target = 'HEAD',
    [string]$AgentCommand,
    [ValidateSet('codex', 'opencode')][string]$Backend,
    [string]$Model,
    [string]$DatabasePath
)

# Contract: BuildScript receives -TargetSha, builds that exact snapshot and exits
# with its build exit code. It runs in a separate PowerShell process in $Repo.
$validatorRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $validatorRoot '.venv/Scripts/python.exe'
if (-not $DatabasePath) { $DatabasePath = Join-Path $validatorRoot '.validator/state.db' }
$buildScriptPath = (Resolve-Path -LiteralPath $BuildScript -ErrorAction Stop).Path
$repositoryPath = (Resolve-Path -LiteralPath $Repo -ErrorAction Stop).Path
$powershellPath = (Get-Process -Id $PID).Path
$targetSha = & git -C $repositoryPath rev-parse --verify --end-of-options "$Target^{commit}"
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the commit to build.' }
$targetSha = $targetSha.Trim()
$buildId = $null

Push-Location $validatorRoot
try {
    try {
        $orderArgs = @('-m', 'validator', '--db', $databasePath, 'order',
            '--repo', $repositoryPath, '--branch', $Branch, '--profile', $Profile,
            '--target', $targetSha)
        if ($AgentCommand) { $orderArgs += @('--agent-command', $AgentCommand) }
        if ($Backend) { $orderArgs += @('--backend', $Backend) }
        if ($Model) { $orderArgs += @('--model', $Model) }
        $orderJson = & $pythonPath @orderArgs
        if ($LASTEXITCODE -ne 0) { throw 'Validator order failed.' }
        $order = $orderJson | ConvertFrom-Json
        $buildId = $order.build_id
        Write-Host "Validator build: $buildId; target: $targetSha"
        if ($order.launch_error) { Write-Warning $order.launch_error }
    } catch {
        Write-Warning "Validator unavailable; build continues: $_"
    }

    Push-Location $repositoryPath
    try {
        & $powershellPath -NoProfile -File $buildScriptPath -TargetSha $targetSha
        $buildExit = $LASTEXITCODE
    } finally { Pop-Location }

    if ($buildExit -eq 0 -and $buildId) {
        try {
            & $pythonPath -m validator --db $databasePath confirm $buildId
            if ($LASTEXITCODE -ne 0) { throw "Retry confirm manually for $buildId" }
        } catch {
            Write-Warning "Build succeeded but confirm failed: $_"
        }
    }
} finally { Pop-Location }
exit $buildExit
