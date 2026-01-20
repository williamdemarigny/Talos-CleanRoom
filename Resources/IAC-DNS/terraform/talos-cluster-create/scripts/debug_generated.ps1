# Debug script that mirrors the generated script exactly

# Configuration - credentials are base64 encoded to avoid escaping issues
$ApiUrl = "https://opnsense-fw-01.knowledgeondemand.net:443/api"
$ApiKeyB64 = "T3g3cHB4dG1hRFNqMlNKOFBhUGtjL2M0QWw4enhMMnM3elhRT3ZObjRDSnZpNXM5YWZWSS90eHZTWVZGamk1U1VXTEE3TkJmVzN2U0dsbDM="
$ApiSecretB64 = "bmpPYjNwdVc1VHBhc05kZUtHOTlOek9FSUZ6Z1VzTEgrSkFqMnBCRFplTlBJZ1IxRHgwTVYzbGcxRCtLOFV3eDRFYzFPSmYySzgrU1UyRnM="
$SkipCert = [System.Convert]::ToBoolean("true")
$FwName = "opnsense-fw-01"

# Decode credentials from base64
$ApiKey = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiKeyB64))
$ApiSecret = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiSecretB64))

# Create credential for Basic Authentication - THIS IS THE GENERATED CODE
$AuthString = "${ApiKey}:${ApiSecret}"
$AuthBytes = [System.Text.Encoding]::UTF8.GetBytes($AuthString)
$AuthBase64 = [System.Convert]::ToBase64String($AuthBytes)

Write-Host "DEBUG INFO:" -ForegroundColor Yellow
Write-Host "ApiKey: $ApiKey" -ForegroundColor Gray
Write-Host "ApiSecret: $ApiSecret" -ForegroundColor Gray
Write-Host "AuthString: $AuthString" -ForegroundColor Gray
Write-Host "AuthBase64: $AuthBase64" -ForegroundColor Gray
Write-Host ""

# SSL bypass
if ($SkipCert) {
    if ($PSVersionTable.PSVersion.Major -lt 6) {
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
    }
}

# Test call
$Uri = "${ApiUrl}/core/firmware/status"
$Headers = @{
    "Authorization" = "Basic ${AuthBase64}"
    "Content-Type" = "application/json"
}

Write-Host "Making test call to: $Uri" -ForegroundColor Cyan
Write-Host "Auth Header: Basic $($AuthBase64.Substring(0, 50))..." -ForegroundColor Gray

try {
    $response = Invoke-WebRequest -Uri $Uri -Method POST -Headers $Headers -UseBasicParsing
    Write-Host "SUCCESS: $($response.StatusCode)" -ForegroundColor Green
    Write-Host $response.Content.Substring(0, 200) -ForegroundColor Gray
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "Status: $statusCode" -ForegroundColor Gray
    }
}
