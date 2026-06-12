# run_tests.ps1 — ClassifyOS backend test runner
# Place in repo root (C:\Projects\classifyos\run_tests.ps1)
#
# Run it from a PowerShell terminal in the repo root with:
#     powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
# or, if your session already allows scripts:
#     .\run_tests.ps1
#
# Optional: pass a filter to run only matching tests, e.g.
#     .\run_tests.ps1 split        -> runs only tests with "split" in the name

param([string]$Filter = "")

Set-Location -Path "$PSScriptRoot\backend"
& ".\.venv\Scripts\Activate.ps1"

if ($Filter -ne "") {
    pytest tests/ -v -k $Filter
} else {
    pytest tests/ -v
}

Set-Location -Path $PSScriptRoot