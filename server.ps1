param(
    [int]$Port = 8080
)

Write-Host "Starting Madhanraj Portfolio Backend Server on port $Port..." -ForegroundColor Cyan
python "$PSScriptRoot\server.py" --port $Port
