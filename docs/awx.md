# Running this repository from AWX

**Status:** first version (2026-11-26). The playbook still runs locally with `task`; AWX is an additional way to run it, not a replacement. Keep the local path as the break-glass route: if the app cluster or `pve-00` is down you cannot repair them from AWX.

## Scope

AWX runs `site.yml` **in check mode only** for now, limited by tags to roles that cannot reboot the host or change storage. Not run from AWX: `updates`, `storage`, `nfs`, `gpu`/`passthrough`, `ssd-passthrough`, `reboot.yml` and `shutdown.yml` (the AWX workers are VMs on `pve-00`, so a reboot or storage change would kill the controller mid-run). The two credential roles that write to Doppler (`terraform-credentials`, `monitoring-credentials`) also stay local because the AWX token is read-only.

## Components

| Piece | Where |
| --- | --- |
| Execution environment image | `ghcr.io/fabricesemti80/home-dc-proxmox-awx-ee`, built from `execution-environment/Dockerfile` by `.github/workflows/awx-execution-environment.yml` (base: AWX EE 24.6.1 pinned by digest, plus the pinned Doppler CLI). |
| Project | This public repository, branch `main`. No deploy key needed. |
| Inventory | `pve` group with `pve-00` (10.0.40.10) |
| Credentials | `pve-00 root (AWX)` (machine, dedicated key), `Doppler (home-dc-proxmox/prd, read-only)` (custom type injecting `DOPPLER_TOKEN`). Values: see [secrets inventory](secrets-and-env-vars.md). |

## Security

- AWX holds a root key for the hypervisor and a read-only token for `home-dc-proxmox/prd`. A compromise of AWX therefore reaches `pve-00`. The key is restricted by source IP (the three app-cluster workers) but not by command, because Ansible needs a shell.
- AWX is reachable at `awx.krapulax.home` and, through Cloudflare Access with Google sign-in, at `awx.krapulax.dev`. Whether to keep the external route is an open decision (see the `home-dc-kubernetes` AWX design).
- The Doppler token reads the whole `prd` config (Gmail app password, Proxmox API token). A narrower scope needs a separate Doppler config.

## Rollback

Delete the AWX job template, project and credentials; revoke the Doppler token `awx-readonly`; remove the `awx-home-dc-proxmox` line from `/root/.ssh/authorized_keys` on `pve-00`; delete the `AWX_*` secrets in Doppler. Local runs are unaffected.
