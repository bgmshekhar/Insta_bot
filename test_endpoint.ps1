Start-Sleep -Seconds 5

Write-Host "=== Testing https://bot.csydev.online ==="

# Health check
try {
    $r = Invoke-WebRequest -Uri "https://bot.csydev.online/health" -UseBasicParsing -TimeoutSec 15
    Write-Host "[PASS] Health endpoint: $($r.StatusCode) $($r.Content)"
} catch {
    Write-Warning "[FAIL] Health endpoint: $($_.Exception.Message)"
}

# Security: bad UUID should 404
try {
    $r2 = Invoke-WebRequest -Uri "https://bot.csydev.online/dl/fake-bad-uuid-000" -UseBasicParsing -TimeoutSec 15 -ErrorAction SilentlyContinue
    Write-Host "[CHECK] Bad UUID returned: $($r2.StatusCode) (expected 404)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 404) {
        Write-Host "[PASS] Security check: bad UUID correctly returns 404"
    } else {
        Write-Warning "[INFO] Bad UUID returned HTTP $code : $($_.Exception.Message)"
    }
}
