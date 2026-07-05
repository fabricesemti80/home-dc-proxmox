# Proxmox API Tokens Role

This Ansible role generates API tokens for Packer and Terraform users in Proxmox VE and creates configuration files for easy integration.

## Features

- **Automated Token Generation** - Creates API tokens for automation users
- **Configuration Files** - Generates ready-to-use Packer and Terraform configs
- **Secure Storage** - Stores tokens in git-ignored directory with restrictive permissions
- **Template Configurations** - Provides example configurations for both tools

## Requirements

- Proxmox VE cluster with API access
- Users `packer@pve` and `terraform@pve` must exist
- Appropriate permissions for token creation

## What This Role Does

1. Creates a `tokens/` directory in the project root
2. Generates API tokens for specified users
3. Creates configuration files:
   - `{user}-{token}.token` - Raw token information
   - `packer-config.pkr.hcl` - Packer configuration template
   - `terraform-config.tf` - Terraform configuration template

## Generated Files

```
tokens/
├── packer@pve-automation.token      # Packer token details
├── terraform@pve-automation.token   # Terraform token details
├── root@pam-terraform-root.token    # Terraform root token for privileged LXC feature flags
├── packer-config.pkr.hcl            # Packer configuration
└── terraform-config.tf              # Terraform configuration
```

## Configuration

### Default Token Settings
```yaml
api_tokens:
  - user: "packer@pve"
    token_name: "automation"
    comment: "Packer automation token"
    expire: 0  # Never expire
    privsep: 0  # Disable privilege separation (required for automation)
    
  - user: "terraform@pve"
    token_name: "automation"
    comment: "Terraform automation token"
    expire: 0  # Never expire
    privsep: 0  # Disable privilege separation (required for automation)

  - user: "root@pam"
    token_name: "terraform-root"
    comment: "Terraform root token for privileged LXC feature flags"
    expire: 0  # Never expire
    privsep: 0  # Disable privilege separation (required for automation)
```

### Token Storage
```yaml
token_storage:
  directory: "tokens"  # Directory name
  file_mode: "0600"    # File permissions
```

## Usage

### Running the Role
```bash
# Generate tokens only
task tokens-only

# Full deployment (includes token generation)
task apply
```

### Using Generated Tokens

#### For Packer
1. Copy the token secret from Proxmox UI (Datacenter → Permissions → API Tokens)
2. Set environment variable:
   ```bash
   export PKR_VAR_proxmox_token="your-actual-token-secret"
   ```
3. Use the generated `packer-config.pkr.hcl` as a starting point

#### For Terraform
1. Copy the token secret from Proxmox UI
2. Set environment variable:
   ```bash
   export TF_VAR_proxmox_token_secret="your-actual-token-secret"
   ```
3. Use the generated `terraform-config.tf` as a starting point

## Security Notes

- **Token Directory** - Automatically excluded from git via `.gitignore`
- **File Permissions** - Token files created with `0600` (owner read/write only)
- **Token Secrets** - Must be manually copied from Proxmox UI for security
- **Environment Variables** - Use env vars to pass secrets to tools

## Token Management

### Viewing Tokens
```bash
# List all tokens for a user
pvesh get /access/users/packer@pve/token

# View specific token details
pvesh get /access/users/packer@pve/token/automation
```

### Regenerating Tokens
```bash
# Delete existing token
pvesh delete /access/users/packer@pve/token/automation

# Re-run the role to create new token
task tokens-only
```

### Revoking Tokens
```bash
# Disable token
pvesh set /access/users/packer@pve/token/automation --enable 0

# Delete token completely
pvesh delete /access/users/packer@pve/token/automation
```

## Integration Examples

### Packer Build
```bash
cd tokens/
export PKR_VAR_proxmox_token="$(cat packer-token-secret)"
packer build packer-config.pkr.hcl
```

### Terraform Deployment
```bash
cd tokens/
export TF_VAR_proxmox_token_secret="$(cat terraform-token-secret)"
terraform init
terraform apply
```

## Troubleshooting

### Token Creation Fails
- Verify users exist: `pvesh get /access/users`
- Check permissions: User must have token creation rights
- Ensure no existing token with same name

### Token Not Working
- Verify token is enabled: `pvesh get /access/users/{user}/token/{name}`
- Check token permissions match user permissions
- Ensure API endpoint is accessible

### Configuration Issues
- Verify Proxmox URL and node names in generated configs
- Check network connectivity to Proxmox API
- Validate SSL/TLS settings (insecure_skip_tls_verify)