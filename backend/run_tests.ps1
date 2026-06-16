<#
.SYNOPSIS
    Run the ClassifyOS backend test suite via the project venv.

.DESCRIPTION
    Calls the venv's Python directly (no activation needed, so it works regardless of
    PowerShell execution policy) and runs pytest from the backend directory. Any extra
    arguments are forwarded to pytest, so the usual pytest flags / paths work.

.EXAMPLE
    ./run_tests.ps1
        Run the whole suite verbosely (tests/ -v).

.EXAMPLE
    ./run_tests.ps1 tests/test_tuning.py -q
        Run just the tuning tests, quietly.

.EXAMPLE
    ./run_tests.ps1 -q --durations=10
        Run the whole suite quietly and show the 10 slowest tests.
#>

# Resolve paths relative to THIS script, so it works from any working directory.
$BackendDir = $PSScriptRoot
$Python = Join-Path $BackendDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Error "venv Python not found at $Python. Create it first:`n" +
        "    python -m venv .venv`n" +
        "    .\.venv\Scripts\Activate.ps1`n" +
        "    pip install -r requirements.txt"
    exit 1
}

# Default to the whole suite (verbose) when no arguments are given; otherwise forward
# everything the caller passed straight through to pytest.
$PytestArgs = if ($args.Count -gt 0) { $args } else { @("tests/", "-v") }

Push-Location $BackendDir
try {
    & $Python -m pytest @PytestArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $exitCode
