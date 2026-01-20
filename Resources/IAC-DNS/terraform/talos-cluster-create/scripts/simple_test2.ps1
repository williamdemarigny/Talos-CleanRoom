# Simple test - NO Content-Type header

$ApiUrl = "https://opnsense-fw-01.knowledgeondemand.net:443/api"
$ApiKey = "Ox7ppxtmaDSj2SJ8PaPkc/c4Al8zxL2s7zXQOvNn4CJvi5s9afVI/txvSYVFji5SUWLA7NBfW3vSGll3"
$ApiSecret = "njOb3puW5TpasNdeKG99NzOEIFzgUsLH+JAj2pBDZeNPIgR1Dx0MV3lg1D+K8Uwx4Ec1OJf2K8+SU2Fs"

# SSL bypass
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy3 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy3
} catch {
    Write-Host "Type already exists" -ForegroundColor Yellow
}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# Build auth
$AuthString = "${ApiKey}:${ApiSecret}"
$AuthBytes = [System.Text.Encoding]::UTF8.GetBytes($AuthString)
$AuthBase64 = [System.Convert]::ToBase64String($AuthBytes)

# Headers WITHOUT Content-Type
$Headers = @{
    "Authorization" = "Basic $AuthBase64"
}

Write-Host "Test 1: Without Content-Type header..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "$ApiUrl/core/firmware/status" -Method POST -Headers $Headers -UseBasicParsing
    Write-Host "SUCCESS: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Test 2: With Content-Type header..." -ForegroundColor Cyan
$Headers2 = @{
    "Authorization" = "Basic $AuthBase64"
    "Content-Type" = "application/json"
}
try {
    $response = Invoke-WebRequest -Uri "$ApiUrl/core/firmware/status" -Method POST -Headers $Headers2 -UseBasicParsing
    Write-Host "SUCCESS: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Test 3: GET request (no POST)..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "$ApiUrl/core/system/status" -Method GET -Headers $Headers -UseBasicParsing
    Write-Host "SUCCESS: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
