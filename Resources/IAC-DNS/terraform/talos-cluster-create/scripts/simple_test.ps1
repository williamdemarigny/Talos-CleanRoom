# Simple test - just make one API call

$ApiUrl = "https://opnsense-fw-01.knowledgeondemand.net:443/api"
$ApiKey = "Ox7ppxtmaDSj2SJ8PaPkc/c4Al8zxL2s7zXQOvNn4CJvi5s9afVI/txvSYVFji5SUWLA7NBfW3vSGll3"
$ApiSecret = "njOb3puW5TpasNdeKG99NzOEIFzgUsLH+JAj2pBDZeNPIgR1Dx0MV3lg1D+K8Uwx4Ec1OJf2K8+SU2Fs"

# SSL bypass
try {
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy2 : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy2
} catch {
    Write-Host "Type already exists, using existing" -ForegroundColor Yellow
}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# Build auth
$AuthString = "${ApiKey}:${ApiSecret}"
$AuthBytes = [System.Text.Encoding]::UTF8.GetBytes($AuthString)
$AuthBase64 = [System.Convert]::ToBase64String($AuthBytes)

$Headers = @{
    "Authorization" = "Basic $AuthBase64"
    "Content-Type" = "application/json"
}

Write-Host "Testing API call..." -ForegroundColor Cyan
Write-Host "Auth (first 50): Basic $($AuthBase64.Substring(0, 50))..."

try {
    $response = Invoke-WebRequest -Uri "$ApiUrl/core/firmware/status" -Method POST -Headers $Headers -UseBasicParsing
    Write-Host "SUCCESS: $($response.StatusCode)" -ForegroundColor Green
    Write-Host $response.Content.Substring(0, 100) -ForegroundColor Gray
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}
