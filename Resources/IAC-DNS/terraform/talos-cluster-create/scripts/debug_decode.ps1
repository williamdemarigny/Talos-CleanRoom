# Debug script to test base64 decoding
$ApiKeyB64 = "T3g3cHB4dG1hRFNqMlNKOFBhUGtjL2M0QWw4enhMMnM3elhRT3ZObjRDSnZpNXM5YWZWSS90eHZTWVZGamk1U1VXTEE3TkJmVzN2U0dsbDM="
$ApiSecretB64 = "bmpPYjNwdVc1VHBhc05kZUtHOTlOek9FSUZ6Z1VzTEgrSkFqMnBCRFplTlBJZ1IxRHgwTVYzbGcxRCtLOFV3eDRFYzFPSmYySzgrU1UyRnM="

Write-Host "Base64 Key: $ApiKeyB64"
Write-Host "Base64 Secret: $ApiSecretB64"

$ApiKey = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiKeyB64))
$ApiSecret = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiSecretB64))

Write-Host ""
Write-Host "Decoded ApiKey: $ApiKey"
Write-Host "Decoded ApiSecret: $ApiSecret"

# Show what the auth string looks like using the generated script's syntax
$AuthString1 = "${ApiKey}:${ApiSecret}"
Write-Host ""
Write-Host "AuthString with curly braces syntax: $AuthString1"

# Show what it should be
$AuthString2 = "$ApiKey`:$ApiSecret"
Write-Host "AuthString with proper syntax: $AuthString2"

# Compare
if ($AuthString1 -eq $AuthString2) {
    Write-Host "Strings match!" -ForegroundColor Green
} else {
    Write-Host "Strings do NOT match!" -ForegroundColor Red
    Write-Host "Length1: $($AuthString1.Length), Length2: $($AuthString2.Length)"
}
