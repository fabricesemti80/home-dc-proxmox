# Standalone Proxmox VE host

This repository manages **one** Proxmox VE 9 host, `pve-00`, using Ansible for host configuration only. Guest VMs and LXCs are provisioned separately with OpenTofu in the sibling [`home-dc-terraform`](../home-dc-terraform/) repository; the active Ansible playbook has no guest-creation tasks. No cluster, Ceph, Beszel agent, HA, or backup jobs are configured. The installer-provided `vmbr0` and default file storage `local` remain untouched. Proxmox ZFS storage IDs are `local-nvme` and `local-hdd`; the underlying pools remain `rpool/data` and `slow`. The NAS at `10.0.40.2` supplies template, ISO, and backup NFS exports. The backup export is for existing VZDump archives; PBS is not configured.

The incoming generic controller in [`standalone/`](standalone/README.md) remains available **only as a separate, explicitly invoked workflow** through `scripts/standalone-host.sh` with its own inventory/config. It is not included by `site.yml` or `task apply`; do not run both controllers against `pve-00` without reconciling their storage, repository, and GPU policies. The archived `legacy/` cluster material is not an active entry point.

## Logical overview

![Logical overview of Ansible host configuration, Proxmox storage and hardware, and OpenTofu guest ownership](docs/architecture.svg)

The diagram separates host configuration from guest provisioning and shows the LAN, NFS, storage, and GPU relationships. P2000 passthrough is enabled and was verified after the operator's reboot. A [detailed offline host diagram](docs/layout.html) is also available. See [storage details](docs/storage.md) for disk identities and content assignments, and the [hardware inventory](docs/hardware.md) for the observed disks, partition layouts, boot path, and free expansion points.

For physical upgrades, see the [motherboard allocation diagram](docs/motherboard.html): the operator-confirmed CPU-side order of the five PCIe positions is empty → NVMe → P2000 → GT 710 → empty. It also records CPU and DIMM occupancy. The empty connectors' electrical widths remain to be checked against their board labels.

## GPU passthrough

The BIOS selects the GT 710 as primary display (`0000:02:00.0`, `boot_vga=1`); the P2000 (`0000:5b:00.0`, `boot_vga=0`) is reserved for a guest. The enabled GPU role checks those assumptions. After the prior apply and reboot, both P2000 functions were verified bound to `vfio-pci` in isolated IOMMU group 2 while the GT 710 remained on `nouveau` in group 36. Future GPU hardware changes require rechecking those IDs. See [GPU passthrough notes](docs/gpu-passthrough.md).

## Alerts and local certificate

`pve-00.krapulax.home` is internal-only. Certificate automation is deferred; browsers will continue to warn until a trusted CA or public-domain name is chosen. The [mail setup](docs/mail.md) reads the Gmail app password from the `GMAIL_APP_PASSWORD` secret in Doppler project `home-dc-proxmox` (config `prd`) to relay queued Proxmox and ZFS/system alerts. Initial Proxmox and local-root mail tests both reached the recipient inbox. The mail role does not change networking or require a reboot.

## Playbook and roles

`site.yml` selects the single `pve` inventory host, checks its Debian version, and composes the roles in order:

Immediately after repository setup, `proxmox_packages` installs configurable host utilities
(`wireless-regdb`, `iw`, `usbutils`, `ethtool`), then `proxmox_wireless_regulatory`
optionally sets the wireless country. Both have separate role banners and tags.
The latter defaults to disabled with country `GB`; `host_vars/pve-00.yml` explicitly
opts this host into GB. See [host packages and wireless regulation](docs/host-packages.md).

1. `roles/proxmox_updates/` — disable subscription-only sources, enable no-subscription PVE, upgrade packages. Repository URL and suite are in `defaults/main.yml`.
2. `roles/proxmox_storage/` — verify the HDD identity, create `slow` ZFS pool if absent, register descriptive Proxmox IDs `local-nvme` and `local-hdd`. Disk WWN, expected serial, pool and storage names are in `defaults/main.yml`. The default `local` ID is never changed.
3. `roles/proxmox_nfs/` — register NAS template, ISO, and backup exports with Proxmox content restrictions. The backup share is limited to VZDump archives; no PBS datastore is mapped.
4. `roles/proxmox_gpu_passthrough/` — verifies GPU identity and firmware primary display, enables Intel IOMMU, and prepares selective VFIO binding for the P2000. PCI IDs are in its defaults.
5. `roles/proxmox_mail/` — configure the existing loopback-only Postfix as a Gmail smarthost, root mail alias, and Proxmox root alert recipient. The app password comes from Doppler; sender and recipient addresses are non-secret defaults.
6. `roles/proxmox_terraform_credentials/` — create a full-administrator Terraform API identity and store its one-time token in Doppler (`PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET`) on the next apply. See [Terraform credential setup](docs/terraform-credentials.md).
7. `roles/proxmox_monitoring_credentials/` — provision a privilege-separated, read-only monitoring token and store it in Doppler. See [monitoring credential setup](docs/monitoring-credentials.md).
8. `roles/proxmox_hardware_monitoring/` — install an unprivileged host metrics exporter restricted by mutual TLS. See [hardware monitoring](docs/hardware-monitoring.md).
9. `roles/proxmox_ssd_passthrough/` — verify and guard the three MX500 SSDs reserved for raw VM passthrough, optionally wipe their old signatures (default off), and publish the VMID↔disk mapping. See [SSD passthrough](docs/ssd-passthrough.md). Use `task ssd-passthrough-plan`/`task ssd-passthrough-apply`.
10. `roles/proxmox_hardware_notes/` — write an at-a-glance GPU and storage summary, generated from Ansible facts and the live VM configuration, to the SSH pre-login banner and the datacenter Notes. See [hardware notes](docs/hardware-notes.md). Use `task hardware-notes-plan`/`task hardware-notes-apply`.

Each role owns its tasks and defaults. `site.yml` does not duplicate their implementation. Use `task nfs-plan`/`task nfs-apply` for NFS-only changes and `task monitoring-credentials-plan`/`task monitoring-credentials-apply` for the monitoring identity; `task plan` previews all roles. The Terraform role is included by default: review its root-equivalent API access before `task apply`. Doppler-backed roles use the same Keychain-backed, config-scoped service token (`home-dc-proxmox/prd`, read/write); save it with `task doppler-token-save`; see [mail setup](docs/mail.md).

## What Ansible changes

- Removes subscription-only PVE and unused Ceph APT sources; adds the official `pve-no-subscription` repository for Debian trixie; updates APT metadata and performs a distribution upgrade. No Ceph installation or Ceph storage configuration.
- Installs host utilities without configuring a Wi-Fi connection. On opted-in hosts,
  persists and applies the wireless regulatory domain with cfg80211 and a boot-time
  systemd service; no host reboot, interface activation, bridge or route changes.
- Migrates the empty Proxmox ZFS storage IDs `local-zfs` → `local-nvme` and `slow` → `local-hdd`, retaining the ZFS pools `rpool/data` and `slow` and all underlying data. Refuses to rename a storage with VM/CT volumes or a conflicting new ID. On a fresh host without the `slow` pool, creates it by **erasing the entire matching HDD**. Default `local` on the NVMe remains unchanged.
- Adds `nfs-proxmox-template` (`/proxmox-template`: `vztmpl,images`), `nfs-proxmox-iso` (`/proxmox-iso`: `iso,import,images`), and `nfs-proxmox-backup` (`/proxmox-backup`: `backup` only) from `10.0.40.2`. The ISO share stores boot ISOs and VM/cloud-init images. Existing VZDump archives are preserved and no backup job is scheduled. The separate `/proxmox-pbs-datastore` export is mounted inside the PBS LXC by `home-dc-terraform/scripts/configure-pbs.sh`.
- Prepares passthrough for the P2000 graphics and audio functions only, without globally blacklisting the GT 710's driver. Changes become active after a separate reboot; no VM is created.
- Configures queued Gmail smarthost delivery for the existing Proxmox sendmail notification target and ZFS/root system mail. The app password is not shown in diffs; the operator verifies delivery after applying.
- On the first `task apply`, provisions a root-equivalent, privilege-separated Proxmox Terraform API token and stores the secret in Doppler. Never exposes the token in Ansible output or rotates it on subsequent runs.
- Provisions a separate read-only, privilege-separated PVE monitoring token; see [monitoring credentials](docs/monitoring-credentials.md) for validation and rotation.
- Verifies the three reserved SSDs by `/dev/disk/by-id`, refuses if the host uses them, installs an ignore-udev rule and an assignment metric; erases old signatures **only** with the explicit `proxmox_ssd_passthrough_wipe_signatures=true` opt-in. It never attaches a disk to a VM (OpenTofu/operator does) and never stops or starts a VM.
- Writes `/etc/ssh/pve-hardware-banner`, an sshd drop-in that serves it as the pre-login banner (shown to anyone who connects; models and sizes only, no serials), and a marker-delimited block in the datacenter Notes (existing notes are preserved). The text is regenerated on every apply, so added, moved or re-assigned drives and GPUs are reflected. It reloads sshd only when the drop-in changes.
- Never reboots automatically during `task apply`. The separate operator-run `task reboot` uses Ansible's reboot module and waits for Proxmox and SSH to return. No role installs a guest VM, backup jobs or cluster services.

## Secrets and environment variables

Every Doppler secret, local credential and environment variable used by this repository is listed in [docs/secrets-and-env-vars.md](docs/secrets-and-env-vars.md).

## Plan → apply → verify

Requires local Ansible and Task (`task`), working root SSH via the `pve-00` alias, a trusted SSH host key, the Doppler CLI, and a `home-dc-proxmox/prd` service token stored via `task doppler-token-save` in macOS Keychain (see [mail setup](docs/mail.md)). From the repository root:

```sh
ansible-playbook -i inventory site.yml --syntax-check
task plan       # check mode + diff; no host configuration applied
# Review the plan; on a fresh host lacking the slow ZFS pool, creation wipes the HDD:
task apply      # operator-run, modifies the host
# Reboot after GPU/IOMMU changes, in a maintenance window:
task reboot     # reboots pve-00; waits for Proxmox and Ansible reconnect
# Preview discovered guests, then gracefully stop them and power off pve-00:
task shutdown-plan
task shutdown   # requires every guest to report stopped; otherwise host stays on
```

`task shutdown-plan` lists registered Proxmox guests with their live status in check mode and does not stop them or power off the host. `task shutdown` uses Proxmox's stop-all operation with forced stops disabled and a 10-minute per-guest timeout. Before poweroff, it rediscovers the guests and polls each VM with `qm status --verbose` and each container with `pct status --verbose`, requiring the live status to be exactly `stopped`; it does not use cached cluster status for this gate. If a guest remains paused or otherwise not stopped, the play fails and leaves the host on. This is an explicit operation, separate from `task apply`; SSH will disconnect when host poweroff begins.

Check mode previews the Proxmox ZFS storage ID changes but does not perform them. Both currently contain no VM/CT volumes; if volumes are added before apply, the rename aborts. The underlying pools are not renamed. On a fresh replacement host, creating `slow` **erases the entire matching HDD**. Package candidates can change when the no-subscription repository is refreshed during apply. `task reboot` is independent of `task apply`, waits up to 15 minutes, then verifies Ansible connectivity.

After apply, verify with `ssh pve-00 'zpool status; pvesm status; pvesm list local-nvme; pvesm list local-hdd'`. Expect `local` to retain its default name and the two ZFS storages to use the new names. A single-disk pool has **no redundancy**; keep independent backups. After the separate reboot, verify both P2000 functions use `vfio-pci` and the GT 710 does not (commands in [GPU passthrough notes](docs/gpu-passthrough.md)); do not assign the GPU to a guest before that check.
