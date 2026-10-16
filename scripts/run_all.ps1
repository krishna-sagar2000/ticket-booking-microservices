# Opens one PowerShell window per service. Run from the repo root.
$services = @(
  @{ dir = "booking-service";      port = 8001 },
  @{ dir = "seat-service";         port = 8002 },
  @{ dir = "payment-service";      port = 8003 },
  @{ dir = "notification-service"; port = 8004 },
  @{ dir = "mock-gateway";         port = 8005 }
)
foreach ($s in $services) {
  $path = Join-Path (Get-Location) ("services\" + $s.dir)
  Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$path'; .\.venv\Scripts\activate; uvicorn app.main:app --port $($s.port)"
}
