param([int]$Rounds = 20, [string]$User = "user0")

$base = "http://localhost:8000"
$token = (Invoke-RestMethod -Method Post "$base/auth/token" -Body @{ username = $User; password = "password" }).token
$headers = @{ Authorization = "Token $token" }

$paths = @(
    "/memories",
    "/memories?since=2026-01-01",
    "/memories?q=meeting",
    "/memories?q=zqxjvk",
    "/memories?page=5000"
)
foreach ($i in 1..$Rounds) {
    foreach ($p in $paths) { Invoke-RestMethod -Headers $headers "$base$p" | Out-Null }
}
"done: $($Rounds * $paths.Count) requests"