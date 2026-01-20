# Standalone OPNSense API Test Script
# Run this directly to debug API connectivity issues

# Configuration - update these values as needed
$ApiHost = "opnsense-fw-01.knowledgeondemand.net"
$ApiPort = 443
$ApiKey = "Ox7ppxtmaDSj2SJ8PaPkc/c4Al8zxL2s7zXQOvNn4CJvi5s9afVI/txvSYVFji5SUWLA7NBfW3vSGll3"
$ApiSecret = "njOb3puW5TpasNdeKG99NzOEIFzgUsLH+JAj2pBDZeNPIgR1Dx0MV3lg1D+K8Uwx4Ec1OJf2K8+SU2Fs"
$SkipCert = $true

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "OPNSense API Debug Test" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# Setup SSL bypass for PowerShell 5.1
if ($SkipCert -and $PSVersionTable.PSVersion.Major -lt 6) {
    Write-Host "Configuring SSL bypass for PowerShell $($PSVersionTable.PSVersion)..." -ForegroundColor Yellow
    Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
    public bool CheckValidationResult(
        ServicePoint srvPoint, X509Certificate certificate,
        WebRequest request, int certificateProblem) {
        return true;
    }
}
"@
    [System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Write-Host "SSL bypass configured." -ForegroundColor Green
}

Write-Host ""
Write-Host "API Configuration:" -ForegroundColor Yellow
Write-Host "  Host: $ApiHost" -ForegroundColor Gray
Write-Host "  Port: $ApiPort" -ForegroundColor Gray
Write-Host "  API Key (first 20 chars): $($ApiKey.Substring(0, [Math]::Min(20, $ApiKey.Length)))..." -ForegroundColor Gray
Write-Host "  API Secret (first 20 chars): $($ApiSecret.Substring(0, [Math]::Min(20, $ApiSecret.Length)))..." -ForegroundColor Gray
Write-Host ""

# Test 1: Basic connectivity (no auth)
Write-Host "Test 1: Basic HTTPS connectivity..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "https://${ApiHost}:${ApiPort}/" -UseBasicParsing -Method GET -TimeoutSec 10
    Write-Host "  PASSED - Status: $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  Response received - Status: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Yellow
    Write-Host "  (This is expected - we're not authenticated)" -ForegroundColor Gray
}
Write-Host ""

# Test 2: API endpoint with Basic Auth (standard format)
Write-Host "Test 2: API with Basic Auth (Key:Secret)..." -ForegroundColor Cyan
$AuthString = "${ApiKey}:${ApiSecret}"
$AuthBytes = [System.Text.Encoding]::UTF8.GetBytes($AuthString)
$AuthBase64 = [System.Convert]::ToBase64String($AuthBytes)

Write-Host "  Auth header (first 50 chars): Basic $($AuthBase64.Substring(0, [Math]::Min(50, $AuthBase64.Length)))..." -ForegroundColor Gray

$Headers = @{
    "Authorization" = "Basic $AuthBase64"
}

try {
    $response = Invoke-WebRequest -Uri "https://${ApiHost}:${ApiPort}/api/core/firmware/status" -UseBasicParsing -Method POST -Headers $Headers -TimeoutSec 30
    Write-Host "  PASSED - Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "  Response: $($response.Content.Substring(0, [Math]::Min(200, $response.Content.Length)))..." -ForegroundColor Gray
} catch {
    Write-Host "  FAILED - $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "  Status Code: $statusCode" -ForegroundColor Gray

        # Try to read error response body
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $errorBody = $reader.ReadToEnd()
            Write-Host "  Error Body: $errorBody" -ForegroundColor Gray
        } catch {
            Write-Host "  Could not read error body" -ForegroundColor Gray
        }
    }
}
Write-Host ""

# Test 3: Try different API endpoints
Write-Host "Test 3: Testing various API endpoints..." -ForegroundColor Cyan

$endpoints = @(
    @{ Method = "GET"; Path = "/api/diagnostics/interface/getInterfaceNames" },
    @{ Method = "GET"; Path = "/api/core/system/status" },
    @{ Method = "POST"; Path = "/api/core/firmware/status" },
    @{ Method = "GET"; Path = "/api/core/menu/search" }
)

foreach ($ep in $endpoints) {
    Write-Host "  $($ep.Method) $($ep.Path)..." -NoNewline
    try {
        $params = @{
            Uri = "https://${ApiHost}:${ApiPort}$($ep.Path)"
            UseBasicParsing = $true
            Method = $ep.Method
            Headers = $Headers
            TimeoutSec = 30
        }
        $response = Invoke-WebRequest @params
        Write-Host " OK ($($response.StatusCode))" -ForegroundColor Green
    } catch {
        $statusCode = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "N/A" }
        Write-Host " FAILED ($statusCode)" -ForegroundColor Red
    }
}
Write-Host ""

# Test 4: Try with credential object instead of header
Write-Host "Test 4: API with PSCredential object..." -ForegroundColor Cyan
$SecureSecret = ConvertTo-SecureString $ApiSecret -AsPlainText -Force
$Credential = New-Object System.Management.Automation.PSCredential($ApiKey, $SecureSecret)

try {
    $response = Invoke-WebRequest -Uri "https://${ApiHost}:${ApiPort}/api/core/firmware/status" -UseBasicParsing -Method POST -Credential $Credential -TimeoutSec 30
    Write-Host "  PASSED - Status: $($response.StatusCode)" -ForegroundColor Green
} catch {
    $statusCode = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "N/A" }
    Write-Host "  FAILED - Status: $statusCode - $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# Test 5: Check if maybe the key/secret are swapped or URL-encoded differently
Write-Host "Test 5: Testing with URL-decoded credentials..." -ForegroundColor Cyan
$DecodedKey = [System.Web.HttpUtility]::UrlDecode($ApiKey)
$DecodedSecret = [System.Web.HttpUtility]::UrlDecode($ApiSecret)

if ($DecodedKey -ne $ApiKey -or $DecodedSecret -ne $ApiSecret) {
    Write-Host "  Credentials contain URL-encoded characters" -ForegroundColor Yellow
    $AuthString2 = "${DecodedKey}:${DecodedSecret}"
    $AuthBytes2 = [System.Text.Encoding]::UTF8.GetBytes($AuthString2)
    $AuthBase642 = [System.Convert]::ToBase64String($AuthBytes2)

    $Headers2 = @{
        "Authorization" = "Basic $AuthBase642"
    }

    try {
        $response = Invoke-WebRequest -Uri "https://${ApiHost}:${ApiPort}/api/core/firmware/status" -UseBasicParsing -Method POST -Headers $Headers2 -TimeoutSec 30
        Write-Host "  PASSED with decoded credentials!" -ForegroundColor Green
    } catch {
        $statusCode = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "N/A" }
        Write-Host "  FAILED - Status: $statusCode" -ForegroundColor Red
    }
} else {
    Write-Host "  No URL encoding detected in credentials" -ForegroundColor Gray
}
Write-Host ""

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Debug test complete" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If all tests failed with 400/401, check:" -ForegroundColor Yellow
Write-Host "  1. API key and secret are correct (regenerate in OPNSense if needed)" -ForegroundColor Gray
Write-Host "  2. API access is enabled for the user in OPNSense" -ForegroundColor Gray
Write-Host "  3. The user has appropriate permissions (e.g., 'Effective Privileges')" -ForegroundColor Gray
Write-Host "  4. No IP-based access restrictions in OPNSense" -ForegroundColor Gray
Write-Host ""
