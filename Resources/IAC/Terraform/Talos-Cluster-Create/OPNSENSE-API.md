# OPNSense API Configuration

This document explains how to configure OPNSense API access for Terraform-based firewall configuration.

## Overview

After deploying OPNSense VMs from the template, you can use the OPNSense API to automate firewall configuration. This Terraform module now includes support for storing and accessing OPNSense API credentials.

## Generating OPNSense API Keys

### Step 1: Access OPNSense Web Interface

1. Navigate to your OPNSense firewall: `https://<opnsense-ip>`
2. Log in with your credentials
3. For each deployed firewall:
   - opnsense-fw-01: `https://10.83.3.5`
   - opnsense-fw-02: `https://10.83.3.6`

### Step 2: Create API User (Recommended)

1. Go to **System > Access > Users**
2. Click **Add** to create a new user:
   - Username: `terraform` (or your preferred name)
   - Password: Set a strong password
   - Full Name: `Terraform API User`
   - Group Membership: Add to `admins` group (or create custom group with specific permissions)
3. Click **Save**

### Step 3: Generate API Key

1. Go to **System > Access > Users**
2. Click the **edit** icon (pencil) next to your API user
3. Scroll down to **API keys** section
4. Click **+** to generate a new API key
5. **Important**: Copy both the **API Key** and **API Secret** immediately
   - API Key: Long alphanumeric string (e.g., `6M8uQ5qvZ...`)
   - API Secret: Long alphanumeric string (e.g., `7N9vR6rwA...`)
6. Click **Save**

**Note**: The API secret is only shown once. Store it securely.

## Configuring Terraform

### Add Credentials

Edit `credentials.auto.tfvars` and add your OPNSense API credentials:

```hcl
# OPNSense API Configuration
opnsense_api_key      = "6M8uQ5qvZ..."  # Your API Key
opnsense_api_secret   = "7N9vR6rwA..."  # Your API Secret
opnsense_api_insecure = true            # Set to false if using valid SSL certificates
```

### Available Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `opnsense_api_key` | string (sensitive) | `""` | API key for authentication |
| `opnsense_api_secret` | string (sensitive) | `""` | API secret for authentication |
| `opnsense_api_port` | number | `443` | Port for API access |
| `opnsense_api_protocol` | string | `"https"` | Protocol (`http` or `https`) |
| `opnsense_api_insecure` | bool | `false` | Skip SSL certificate verification |

## Terraform Outputs

After running `terraform apply`, you can access OPNSense API connection information.

**Note**: These outputs are marked as sensitive and won't be displayed by default.

### View API Endpoints

```bash
# Use -json to view sensitive outputs
terraform output -json opnsense_api_endpoints | jq
```

Example output:
```hcl
{
  "opnsense-fw-01" = {
    "ip"       = "10.83.3.5"
    "name"     = "opnsense-fw-01"
    "port"     = 443
    "protocol" = "https"
    "url"      = "https://10.83.3.5:443"
    "insecure" = true
  }
  "opnsense-fw-02" = {
    "ip"       = "10.83.3.6"
    "name"     = "opnsense-fw-02"
    "port"     = 443
    "protocol" = "https"
    "url"      = "https://10.83.3.6:443"
    "insecure" = true
  }
}
```

### Check API Configuration Status

```bash
# Use -json to view sensitive output
terraform output -json opnsense_api_configured
```

Returns `true` if both API key and secret are configured, `false` otherwise.

## Using OPNSense API with Terraform

### Example: Using Local Values

You can reference the OPNSense API configuration in other Terraform resources or modules:

```hcl
# Access API configuration for a specific firewall
locals {
  fw01_api = local.opnsense_api_config["opnsense-fw-01"]
}

# Example: Using with external provider or script
resource "null_resource" "configure_opnsense_fw01" {
  provisioner "local-exec" {
    command = <<-EOT
      curl -k -u "${local.fw01_api.api_key}:${local.fw01_api.api_secret}" \
        "${local.fw01_api.url}/api/core/firmware/status"
    EOT
  }

  depends_on = [proxmox_virtual_environment_vm.opnsense]
}
```

### Example: Configuring Firewall Rules

```hcl
# Example using HTTP provider or external script
resource "null_resource" "add_firewall_rule" {
  for_each = local.opnsense_api_config

  provisioner "local-exec" {
    command = <<-EOT
      python3 scripts/configure_opnsense.py \
        --url "${each.value.url}" \
        --key "${each.value.api_key}" \
        --secret "${each.value.api_secret}" \
        --insecure "${each.value.insecure}"
    EOT
  }

  depends_on = [proxmox_virtual_environment_vm.opnsense]
}
```

## Testing API Access

### Using cURL

Test API connectivity with cURL:

```bash
# Replace with your actual credentials
API_KEY="your-api-key"
API_SECRET="your-api-secret"
OPNSENSE_IP="10.83.3.5"

# Test firmware status endpoint
curl -k -u "${API_KEY}:${API_SECRET}" \
  "https://${OPNSENSE_IP}/api/core/firmware/status"

# Test system information
curl -k -u "${API_KEY}:${API_SECRET}" \
  "https://${OPNSENSE_IP}/api/diagnostics/interface/getInterfaceNames"
```

### Using Python

```python
import requests
from requests.auth import HTTPBasicAuth

api_key = "your-api-key"
api_secret = "your-api-secret"
opnsense_url = "https://10.83.3.5"

# Disable SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings()

# Test API connection
response = requests.get(
    f"{opnsense_url}/api/core/firmware/status",
    auth=HTTPBasicAuth(api_key, api_secret),
    verify=False
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
```

## Security Best Practices

1. **Use Dedicated API User**: Create a separate user account for API access, not the root account
2. **Limit Permissions**: Create custom groups with only necessary permissions for API operations
3. **Rotate Keys**: Regularly rotate API keys and secrets
4. **Use HTTPS**: Always use HTTPS for API communication
5. **Valid Certificates**: In production, use valid SSL certificates and set `opnsense_api_insecure = false`
6. **Secure Storage**: Store API credentials securely:
   - Use environment variables for CI/CD pipelines
   - Use secret management tools (HashiCorp Vault, AWS Secrets Manager)
   - Never commit `credentials.auto.tfvars` to version control
7. **Network Segmentation**: Restrict API access to trusted networks via firewall rules

## OPNSense API Documentation

Official API documentation:
- **API Overview**: https://docs.opnsense.org/development/api.html
- **API Endpoints**: Available at `https://<opnsense-ip>/api/`
- **Core API**: https://docs.opnsense.org/development/api/core/

## Troubleshooting

### API Connection Refused

- Verify OPNSense VM is running: `terraform output opnsense_vms`
- Check network connectivity: `ping 10.83.3.5`
- Verify HTTPS is accessible: `curl -k https://10.83.3.5`

### Authentication Failed (401)

- Verify API key and secret are correct
- Check user has necessary permissions in OPNSense
- Ensure API key hasn't been revoked

### SSL Certificate Errors

- Set `opnsense_api_insecure = true` for self-signed certificates
- Or install valid SSL certificate on OPNSense
- Or add certificate to your system's trusted certificates

### API Endpoint Not Found (404)

- Verify the API endpoint exists in your OPNSense version
- Check OPNSense version: `curl -k https://<ip>/api/core/firmware/status`
- Consult OPNSense API documentation for correct endpoints

## Next Steps

1. Generate API keys in both OPNSense VMs
2. Add credentials to `credentials.auto.tfvars`
3. Run `terraform apply` to deploy VMs
4. Test API connectivity using examples above
5. Create automation scripts or Terraform modules for firewall configuration
6. Consider using Terraform providers like:
   - `terraform-provider-http` for direct API calls
   - Custom providers or scripts for complex configurations

## Additional Resources

- [OPNSense API Documentation](https://docs.opnsense.org/development/api.html)
- [OPNSense API How-To](https://docs.opnsense.org/development/how-tos/api.html)
- [Terraform HTTP Provider](https://registry.terraform.io/providers/hashicorp/http/latest/docs)
