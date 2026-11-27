# Running this repository from AWX

**Status:** first version (2026-11-26). The playbook still runs locally with `task`; AWX is an additional way to run it, not a replacement. Keep the local path as the break-glass route: if the app cluster or `pve-00` is down you cannot repair them from AWX.

## Scope

AWX provides check-mode plans and a gated updates workflow; see the templates below. Reboot, shutdown, and storage/passthrough changes remain local because AWX runs on VMs hosted by `pve-00`. Credential roles that write to Doppler stay local: the AWX job token is read-only.

## Verified 2026-11-26

Job template `pve-00 check (safe tags)` (check mode, diff on, tags `packages,mail,hardware-monitoring`, limit `pve-00`) ran successfully in AWX with the execution environment `home-dc-proxmox EE` (the published image, pinned by digest in AWX): `ok=28, changed=0, failed=0, skipped=17`. The Doppler reads in the `mail` and `hardware-monitoring` roles completed using the `home-dc-awx/prd` token. The hardware-monitoring tasks that were skipped are the role's own conditions; the reason was not investigated. Job pods reach `pve-00` from the allowed worker IPs, and the pinned host key is accepted.

The AWX objects were initially created via the API. `awx/config.json` and `scripts/reconcile-awx.py` now describe and reconcile them; the scoped Doppler token is reissued during recovery as described in the secrets inventory. Template extra variables point Doppler reads at `home-dc-awx`.

The declared templates are `pve-00 check (safe tags)` (`packages,mail,hardware-monitoring`), `pve-00 plan (full, check)` (all roles except the two Doppler-writing credential roles), `pve-00 updates (check)` and `pve-00 updates (APPLY)`. Workflow `pve-00 updates (gated)` links the update check to a manual approval and only then the apply template. The apply template itself is launchable by AWX administrators; restrict AWX permissions accordingly. This configuration does not change the Proxmox update role. Merge and verify the detached-upgrade fix before approving an actual upgrade.

## Configuration as code

`awx/config.json` declares the inventory, host/group, project, execution environment, credentials, templates and gated updates workflow. `task awx-plan` reads the AWX API and reports drift; `task awx-apply` reconciles objects by name. Neither launches a job, deletes other objects or approves an upgrade. A partial installation is reported in plan mode; unexpected workflow nodes, bypass edges, or a non-approval node at the approval gate fail closed and require operator inspection. Run after the AWX operator makes its API available; provision the execution-environment image separately and update its pinned digest when publishing a new image. Requires Python 3 with PyYAML, Ansible and Doppler CLI on the operator machine. The second apply should report no changes.

By default the script uses `http://awx.krapulax.home` and reads `AWX_ADMIN_PASSWORD` from Doppler `home-dc-kubernetes/apps` using the operator's Doppler login. `AWX_URL` and `AWX_ADMIN_PASSWORD` can override these defaults in the shell; never put the password in a command line or Git. On a fresh AWX, set `AWX_DOPPLER_TOKEN` to a **new** read-only service token scoped to `home-dc-awx/prd`. The script reads `AWX_PVE_SSH_PRIVATE_KEY` from Doppler `home-dc-awx/prd` unless supplied as an environment variable. Once credentials exist, ordinary reconciliation does not read or overwrite masked values. `python3 scripts/reconcile-awx.py --apply --rotate` explicitly replaces both inputs; revoke the previous token after checking the new one. Do not pass privileged `home-dc-proxmox/prd` tokens into AWX. For a rebuilt instance, preserve the SSH public-key authorization on `pve-00` or install the matching dedicated key separately.

Assumptions: this public Git repository needs no deploy key; the pinned `pve-00` ED25519 host key remains valid; the dedicated private key is escrowed in `home-dc-awx/prd`; the operator has an AWX administrator password and Doppler access. Verify the host-key fingerprint out of band before changing the pin. Validation: reconcile twice, inspect the four templates and three workflow nodes, then launch a **check-mode** job. Do not approve an upgrade to test provisioning.

Rollback: stop reconciliation and remove only the managed AWX objects through the UI/API if desired. Local `task` commands remain available. Revoking the machine key or Doppler token is separate; a database restore retains objects until reconciliation runs again.

## Components

| Piece | Where |
| --- | --- |
| Execution environment image | `ghcr.io/fabricesemti80/home-dc-proxmox-awx-ee`, built from `execution-environment/Dockerfile` by `.github/workflows/awx-execution-environment.yml` (base: AWX EE 24.6.1 pinned by digest, plus the pinned Doppler CLI). |
| Project | This public repository, branch `main`. No deploy key needed. |
| Inventory | `pve` group with `pve-00` (10.0.40.10) |
| Credentials | `pve-00 root (AWX)` (machine, dedicated key), `Doppler (home-dc-awx/prd, read-only)` (custom type injecting `DOPPLER_TOKEN`). Values: see [secrets inventory](secrets-and-env-vars.md). |

## Security

- AWX holds a root key for the hypervisor and a read-only token for `home-dc-awx/prd`. A compromise of AWX therefore reaches `pve-00`. The key is restricted by source IP (the three app-cluster workers) but not by command, because Ansible needs a shell.
- AWX is reachable at `awx.krapulax.home` and, through Cloudflare Access with Google sign-in, at `awx.krapulax.dev`. Whether to keep the external route is an open decision (see the `home-dc-kubernetes` AWX design).
- The Doppler token is scoped to the separate project `home-dc-awx`, which holds only the Gmail app password, the hardware-monitoring certificates (as references) and the AWX SSH key. It cannot read `home-dc-proxmox/prd`, so jobs cannot obtain the Terraform administrator token. A branch config would not isolate this, because branch configs inherit every root secret. Whoever can run a job with the Doppler credential can still read those few values, and the SSH key is readable by any job using either credential.

## Rollback

Delete the AWX job template, project and credentials; revoke the Doppler token `awx-jobs-readonly`; remove the `awx-home-dc-proxmox` line from `/root/.ssh/authorized_keys` on `pve-00`; delete the Doppler project `home-dc-awx`. Local runs are unaffected.
