# Secrets and environment variables

The inventory of every secret, credential and environment variable this repository reads or writes. Values never belong in Git; this file records **names, locations and purpose only**.

> **Keep this file current.** Any change that adds, renames, moves, rotates the source of, or removes a secret or environment variable must update this file in the same commit. See [`AGENTS.md`](../AGENTS.md).

## Doppler

| Project / config | Access | Used by |
| --- | --- | --- |
| `home-dc-proxmox` / `prd` | Read/write service token (named `ansible-pve-00` in Doppler) | All Doppler-backed Ansible roles |

The service token is held in the operator's macOS Keychain and saved with `task doppler-token-save`. It can read and change every secret in `home-dc-proxmox/prd` and nothing else.

## Secrets in Doppler `home-dc-proxmox/prd`

| Name | Written by | Read by | Function |
| --- | --- | --- | --- |
| `GMAIL_APP_PASSWORD` | Operator (manual) | `roles/proxmox_mail` | Gmail app password for the Postfix smarthost that relays Proxmox, ZFS and root alerts. See [mail setup](mail.md). |
| `PROXMOX_TOKEN_ID` | `roles/proxmox_terraform_credentials` (first apply) | `home-dc-terraform/prd` by Doppler reference | ID of the root-equivalent `terraform@pve!provisioning` API token. |
| `PROXMOX_TOKEN_SECRET` | `roles/proxmox_terraform_credentials` (first apply) | `home-dc-terraform/prd` by Doppler reference | Secret of the Terraform API token; expires one year after creation. See [Terraform credentials](terraform-credentials.md). |
| `PVE_MONITORING_TOKEN_ID` | `roles/proxmox_monitoring_credentials` | Role idempotency check | ID of the read-only `prometheus@pve!victoriametrics` (`PVEAuditor`) token. |
| `PVE_MONITORING_TOKEN_SECRET` | `roles/proxmox_monitoring_credentials` | `home-dc-kubernetes/infra` by Doppler reference → `pve-exporter` | Secret of the read-only monitoring token; expires after one year. See [monitoring credentials](monitoring-credentials.md). |
| `MONITORING_HW_CA_CERT` | `home-dc-kubernetes/scripts/monitoring-remote-pki.py` | `roles/proxmox_hardware_monitoring` | CA that signs the hardware exporter's client certificates (mTLS trust root on the host). |
| `MONITORING_HW_SERVER_CERT` | `home-dc-kubernetes/scripts/monitoring-remote-pki.py` | `roles/proxmox_hardware_monitoring` | TLS server certificate for the node exporter on `10.0.40.10:9100`. |
| `MONITORING_HW_SERVER_KEY` | `home-dc-kubernetes/scripts/monitoring-remote-pki.py` | `roles/proxmox_hardware_monitoring` | Private key for the server certificate. See [hardware monitoring](hardware-monitoring.md). |

## Local secrets (outside Doppler)

| Item | Location | Function |
| --- | --- | --- |
| Doppler service token | macOS Keychain, service `home-dc-doppler-proxmox`, account `$USER` | Authenticates every Doppler call from the Ansible controller. Written by `scripts/save-doppler-token.py`. |
| SSH key for `pve-00` | Operator's SSH agent / `~/.ssh` (alias `pve-00`) | Root SSH used by Ansible. |
| `files/root_pve_rsa`, `tokens/`, `.env`, `.envrc`, `.env.*` | Git-ignored | Legacy or local credential files. Not read by the active playbook; do not commit. |

## Environment variables

| Variable | Where it's read | Source | Function |
| --- | --- | --- | --- |
| `DOPPLER_TOKEN` | Role defaults of `proxmox_mail`, `proxmox_terraform_credentials`, `proxmox_monitoring_credentials`, `proxmox_hardware_monitoring` | Optional override; otherwise read from the Keychain item above | Doppler service token. Passed to `doppler` through the environment, never argv. |
| `USER` | Role defaults, `scripts/save-doppler-token.py` | Shell | Keychain account name. |
| `ANSIBLE_REMOTE_USER`, `ANSIBLE_PRIVATE_KEY_FILE` | `standalone/controller.py` | Operator shell (optional) | The only inherited `ANSIBLE_*` variables the standalone controller passes through. It **removes** every other inherited `ANSIBLE_*` variable before running `ansible-playbook`. |
| `ANSIBLE_CONFIG`, `ANSIBLE_ROLES_PATH`, `ANSIBLE_LIBRARY`, `ANSIBLE_MODULE_UTILS` | `ansible-playbook` (child of `standalone/controller.py`) | Written by the controller, pointing at `standalone/` | Pins config, roles, modules and module utils to the isolated standalone component. |
| `ANSIBLE_VARS_ENABLED` (`''`), `ANSIBLE_INVENTORY_ENABLED` (`yaml`), `ANSIBLE_FACT_CACHING` (`memory`) | `ansible-playbook` (child of the controller) | Written by the controller | Disables vars plugins, allows only the generated YAML inventory, and keeps facts in memory, so no host data is cached to disk. |
| `ANSIBLE_HOST_KEY_CHECKING` (`True`) | `ansible-playbook` (child of the controller) | Written by the controller | Forces SSH host-key verification for standalone runs. |
| `PROXMOX_PYTHON` | `scripts/standalone-host.sh` | Operator shell (optional, defaults to `python3`) | Absolute interpreter for the isolated standalone controller; its `bin/` also supplies `ansible-playbook`. |
| `DEBIAN_FRONTEND` | `standalone/library/standalone_host.py` | Set to `noninteractive` by the module | Non-interactive APT on the host. |

## Rotation notes

- `PROXMOX_TOKEN_*` exists in two places, the source here and a reference in `home-dc-terraform/prd`. Rotate the source and confirm the reference resolves.
- The roles never rotate tokens automatically. The host token and both Doppler values must all exist or all be absent; otherwise the role stops.
- `MONITORING_HW_*` is generated together with the client half in `home-dc-kubernetes/infra`. Regenerate both halves with `monitoring-remote-pki.py`.
