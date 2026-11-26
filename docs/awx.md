# Running this repository from AWX

**Status:** first version (2026-11-26). The playbook still runs locally with `task`; AWX is an additional way to run it, not a replacement. Keep the local path as the break-glass route: if the app cluster or `pve-00` is down you cannot repair them from AWX.

## Scope

AWX runs `site.yml` **in check mode only** for now, limited by tags to roles that cannot reboot the host or change storage. Not run from AWX: `updates`, `storage`, `nfs`, `gpu`/`passthrough`, `ssd-passthrough`, `reboot.yml` and `shutdown.yml` (the AWX workers are VMs on `pve-00`, so a reboot or storage change would kill the controller mid-run). The two credential roles that write to Doppler (`terraform-credentials`, `monitoring-credentials`) also stay local because the AWX token is read-only.

## Verified 2026-11-26

Job template `pve-00 check (safe tags)` (check mode, diff on, tags `packages,mail,hardware-monitoring`, limit `pve-00`) ran successfully in AWX with the execution environment `home-dc-proxmox EE` (the published image, pinned by digest in AWX): `ok=28, changed=0, failed=0, skipped=17`. The Doppler reads in the `mail` and `hardware-monitoring` roles completed using the `home-dc-awx/prd` token. The hardware-monitoring tasks that were skipped are the role's own conditions; the reason was not investigated. Job pods reach `pve-00` from the allowed worker IPs, and the pinned host key is accepted.

The AWX objects (project, inventory, credentials, execution environment, job template) were created through the AWX API, not from Git. If AWX is rebuilt they must be recreated; the Doppler token is reissued as described in the secrets inventory. The template's extra variables set `proxmox_mail_doppler_project` and `proxmox_hardware_monitoring_doppler_project` to `home-dc-awx`.

## Job templates and the updates workflow

| AWX object | What it runs |
| --- | --- |
| `pve-00 check (safe tags)` | `site.yml --check --diff`, tags `packages,mail,hardware-monitoring` |
| `pve-00 plan (full, check)` | `site.yml --check --diff` for every role except `terraform-credentials` and `monitoring-credentials` (they need `home-dc-proxmox/prd`, which AWX cannot read). The AWX equivalent of `task plan`. |
| `pve-00 updates (check)` | `updates` role in check mode: reports whether a dist-upgrade is pending |
| `pve-00 updates (APPLY)` | The real `apt dist-upgrade`. Never launch it directly. |
| Workflow `pve-00 updates (gated)` | updates check, then a manual approval, then the apply template |

The upgrade restarts `pve-cluster`, which briefly unmounts `/etc/pve`; root's `authorized_keys` on `pve-00` is a symlink into it, so a new SSH login can fail during the upgrade. The role therefore runs the upgrade detached (`async`, `poll: 0`) and polls with retries that tolerate unreachable results. In check mode a separate, synchronous task still reports the pending upgrade (async tasks are skipped in check mode). The detached path has not yet been exercised by a real upgrade. If an apply job dies, run `dpkg --configure -a` and `apt -f install` on `pve-00` (locally over SSH), then re-run.

A pending **kernel or microcode** update needs a reboot to take effect, and running VMs keep the old QEMU until they restart. `reboot.yml` stays local: rebooting `pve-00` stops the VMs that host AWX.

## Components

| Piece | Where |
| --- | --- |
| Execution environment image | `ghcr.io/fabricesemti80/home-dc-proxmox-awx-ee`, built from `execution-environment/Dockerfile` by `.github/workflows/awx-execution-environment.yml` (base: AWX EE 24.6.1 pinned by digest, plus the pinned Doppler CLI). |
| Project | This public repository, branch `main`. No deploy key needed. |
| Inventory | `pve` group with `pve-00` (10.0.40.10) |
| Credentials | `pve-00 root (AWX)` (machine, dedicated key), `Doppler (home-dc-awx/prd, read-only)` (custom type injecting `DOPPLER_TOKEN`). Values: see [secrets inventory](secrets-and-env-vars.md). |

## Security

- AWX holds a root key for the hypervisor and a read-only token for `home-dc-proxmox/prd`. A compromise of AWX therefore reaches `pve-00`. The key is restricted by source IP (the three app-cluster workers) but not by command, because Ansible needs a shell.
- AWX is reachable at `awx.krapulax.home` and, through Cloudflare Access with Google sign-in, at `awx.krapulax.dev`. Whether to keep the external route is an open decision (see the `home-dc-kubernetes` AWX design).
- The Doppler token is scoped to the separate project `home-dc-awx`, which holds only the Gmail app password, the hardware-monitoring certificates (as references) and the AWX SSH key. It cannot read `home-dc-proxmox/prd`, so jobs cannot obtain the Terraform administrator token. A branch config would not isolate this, because branch configs inherit every root secret. Whoever can run a job with the Doppler credential can still read those few values, and the SSH key is readable by any job using either credential.

## Rollback

Delete the AWX job template, project and credentials; revoke the Doppler token `awx-jobs-readonly`; remove the `awx-home-dc-proxmox` line from `/root/.ssh/authorized_keys` on `pve-00`; delete the Doppler project `home-dc-awx`. Local runs are unaffected.
