# Compare auth strings between working and non-working approaches

# Method 1: Direct credentials (WORKING in test_opnsense_api.ps1)
$ApiKey1 = "Ox7ppxtmaDSj2SJ8PaPkc/c4Al8zxL2s7zXQOvNn4CJvi5s9afVI/txvSYVFji5SUWLA7NBfW3vSGll3"
$ApiSecret1 = "njOb3puW5TpasNdeKG99NzOEIFzgUsLH+JAj2pBDZeNPIgR1Dx0MV3lg1D+K8Uwx4Ec1OJf2K8+SU2Fs"
$AuthString1 = "${ApiKey1}:${ApiSecret1}"
$AuthBase641 = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($AuthString1))

# Method 2: Base64 decoded credentials (NOT WORKING)
$ApiKeyB64 = "T3g3cHB4dG1hRFNqMlNKOFBhUGtjL2M0QWw4enhMMnM3elhRT3ZObjRDSnZpNXM5YWZWSS90eHZTWVZGamk1U1VXTEE3TkJmVzN2U0dsbDM="
$ApiSecretB64 = "bmpPYjNwdVc1VHBhc05kZUtHOTlOek9FSUZ6Z1VzTEgrSkFqMnBCRFplTlBJZ1IxRHgwTVYzbGcxRCtLOFV3eDRFYzFPSmYySzgrU1UyRnM="
$ApiKey2 = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiKeyB64))
$ApiSecret2 = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($ApiSecretB64))
$AuthString2 = "${ApiKey2}:${ApiSecret2}"
$AuthBase642 = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($AuthString2))

Write-Host "Method 1 (Direct):" -ForegroundColor Cyan
Write-Host "  ApiKey: $ApiKey1"
Write-Host "  ApiSecret: $ApiSecret1"
Write-Host "  AuthString: $AuthString1"
Write-Host "  AuthBase64: $AuthBase641"
Write-Host ""

Write-Host "Method 2 (Base64 Decoded):" -ForegroundColor Cyan
Write-Host "  ApiKey: $ApiKey2"
Write-Host "  ApiSecret: $ApiSecret2"
Write-Host "  AuthString: $AuthString2"
Write-Host "  AuthBase64: $AuthBase642"
Write-Host ""

Write-Host "Comparison:" -ForegroundColor Yellow
Write-Host "  Keys match: $($ApiKey1 -eq $ApiKey2)"
Write-Host "  Secrets match: $($ApiSecret1 -eq $ApiSecret2)"
Write-Host "  AuthStrings match: $($AuthString1 -eq $AuthString2)"
Write-Host "  AuthBase64 match: $($AuthBase641 -eq $AuthBase642)"
Write-Host ""

# Check for hidden characters
Write-Host "Key1 bytes:" ([System.Text.Encoding]::UTF8.GetBytes($ApiKey1) | ForEach-Object { $_.ToString("X2") }) -join " "
Write-Host "Key2 bytes:" ([System.Text.Encoding]::UTF8.GetBytes($ApiKey2) | ForEach-Object { $_.ToString("X2") }) -join " "
