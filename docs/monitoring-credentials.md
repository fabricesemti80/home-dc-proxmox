# Read-only PVE monitoring identity

Decision: provision a dedicated `prometheus@pve` API-only user and privilege-separated `victoriametrics` token. Grant the built-in `PVEAuditor` role at `/` to both user and token. This permits infrastructure inventory and metrics reads without granting VM, storage or host modification. This identity is independent of Terraform's administrator credential.

The Ansible role creates the token once and writes its ID and one-time value to `home-dc-proxmox/prd` in Doppler over the controller's scoped service token; it never logs the value or passes it in a process argument. A pre-existing host token and both stored values must either all exist or all be absent. Ambiguous or partial state stops the role instead of rotating an unknown credential. The token expires after one year; operators must rotate it before expiry.

## Assumptions and validation

- `pve-00` runs Proxmox VE 9 and the existing read/write `home-dc-proxmox/prd` service token is available through macOS Keychain, as in [Terraform credentials](terraform-credentials.md).
- `PVEAuditor` includes the reads required by the selected exporter. Verify the actual API endpoints and metrics after deployment; some hardware, ZFS or PBS metrics may need separate collectors.
- Before apply, run `task monitoring-credentials-plan`. Check mode never creates a token. Review user, token and `/` ACL changes; apply using `task monitoring-credentials-apply`.
- After apply, run the plan again and confirm no changes, then inspect `pveum user token permissions prometheus@pve victoriametrics --output-format json` without printing secrets. Confirm the account has no unrelated ACL grants. Confirm only the secret names are present in Doppler.
- The monitoring deployment must use TLS verification against the independently obtained Proxmox CA, restrict the API endpoint to trusted networks and sync the token into only the exporter namespace. Do not reuse the Terraform token.

## Rotation and revocation

Create a second privilege-separated token with its own ID and `PVEAuditor` grant; store its one-time value securely in Doppler, update the exporter reference and verify successful scrapes before revoking the old token. Rotate before expiry. Revoke immediately with `pveum user token delete prometheus@pve <token-id>` if compromised; remove its token ACL and replace the Doppler secret. Deleting the monitoring user or token does not affect Terraform. For failed provisioning, inspect token and Doppler secret *presence*, not values, before a manual recovery; the role fails closed when the state is ambiguous.
