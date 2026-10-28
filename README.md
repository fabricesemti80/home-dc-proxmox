# Standalone Proxmox VE host

This repository manages **one** Proxmox VE 9 host, `pve-00`. No cluster, Ceph, Beszel agent, HA, or backup jobs are configured. The installer-provided `vmbr0` and default file storage `local` remain untouched. Proxmox ZFS storage IDs are `local-nvme` and `local-hdd`; the underlying pools remain `rpool/data` and `slow`. The NAS at `10.0.40.2` supplies template, ISO, and backup NFS exports. The backup export is for existing VZDump archives; PBS is not configured.

## Layout

```mermaid
flowchart LR
    operator[Ansible operator] -->|SSH alias pve-00| host
    lan[10.0.40.0/24 LAN] ---|nic0 / vmbr0| host
    nas[NAS · 10.0.40.2] -->|NFS template + ISO + backup exports| host
    subgraph host[pve-00 · Proxmox VE 9]
        zfs[NVMe · rpool/data → local-nvme]
        hdd[HDD · slow → local-hdd]
        console[GT 710 · host console]
        gpu[P2000 · VFIO after apply + reboot]
    end
```

The diagram shows storage allocation; P2000 passthrough is enabled and was verified after the operator's reboot. A [standalone diagram](docs/layout.html) is also available for offline viewing. See [storage details](docs/storage.md) for disk identities and content assignments.

For physical upgrades, see the [motherboard allocation diagram](docs/motherboard.html): the operator-confirmed CPU-side order of the five PCIe positions is empty → NVMe → P2000 → GT 710 → empty. It also records CPU and DIMM occupancy. The empty connectors' electrical widths remain to be checked against their board labels.

## GPU passthrough

The BIOS selects the GT 710 as primary display (`0000:02:00.0`, `boot_vga=1`); the P2000 (`0000:5b:00.0`, `boot_vga=0`) is reserved for a guest. The enabled GPU role checks those assumptions. After the prior apply and reboot, both P2000 functions were verified bound to `vfio-pci` in isolated IOMMU group 2 while the GT 710 remained on `nouveau` in group 36. Future GPU hardware changes require rechecking those IDs. See [GPU passthrough notes](docs/gpu-passthrough.md).

## Alerts and local certificate

`pve-00.krapulax.home` is internal-only. Certificate automation is deferred; browsers will continue to warn until a trusted CA or public-domain name is chosen. The [mail setup](docs/mail.md) uses an ignored `.env` created from [`.env_example`](.env_example) to relay queued Proxmox and ZFS/system alerts through the dedicated Gmail account. Initial Proxmox and local-root mail tests both reached the recipient inbox. The mail role does not change networking or require a reboot.

## Playbook and roles

`site.yml` selects the single `pve` inventory host, checks its Debian version, and composes the roles in order:

1. `roles/proxmox_updates/` — disable subscription-only sources, enable no-subscription PVE, upgrade packages. Repository URL and suite are in `defaults/main.yml`.
2. `roles/proxmox_storage/` — verify the HDD identity, create `slow` ZFS pool if absent, register descriptive Proxmox IDs `local-nvme` and `local-hdd`. Disk WWN, expected serial, pool and storage names are in `defaults/main.yml`. The default `local` ID is never changed.
3. `roles/proxmox_nfs/` — register NAS template, ISO, and backup exports with Proxmox content restrictions. The backup share is limited to VZDump archives; no PBS datastore is mapped.
4. `roles/proxmox_gpu_passthrough/` — verifies GPU identity and firmware primary display, enables Intel IOMMU, and prepares selective VFIO binding for the P2000. PCI IDs are in its defaults.
5. `roles/proxmox_mail/` — configure the existing loopback-only Postfix as a Gmail smarthost, root mail alias, and Proxmox root alert recipient. Credentials come solely from ignored `.env`.

Each role owns its tasks and defaults. `site.yml` does not duplicate their implementation. Use `ansible-playbook -i inventory site.yml --check --diff --tags mail` (or `--tags gpu` / `--tags nfs` / `--tags storage` / `--tags updates`) for a focused preview; `task plan` previews all active roles. The mail role requires a private `.env`, even in check mode; see [mail setup](docs/mail.md).

## What Ansible changes

- Removes subscription-only PVE and unused Ceph APT sources; adds the official `pve-no-subscription` repository for Debian trixie; updates APT metadata and performs a distribution upgrade. No Ceph installation or Ceph storage configuration.
- Migrates the empty Proxmox ZFS storage IDs `local-zfs` → `local-nvme` and `slow` → `local-hdd`, retaining the ZFS pools `rpool/data` and `slow` and all underlying data. Refuses to rename a storage with VM/CT volumes or a conflicting new ID. On a fresh host without the `slow` pool, creates it by **erasing the entire matching HDD**. Default `local` on the NVMe remains unchanged.
- Adds `nfs-proxmox-template` (`/proxmox-template`: `vztmpl,images`), `nfs-proxmox-iso` (`/proxmox-iso`: `iso,import`), and `nfs-proxmox-backup` (`/proxmox-backup`: `backup` only) from `10.0.40.2`. Existing archives are not changed, and no new backup job is scheduled. The separate `/proxmox-pbs-datastore` export is not mapped.
- Prepares passthrough for the P2000 graphics and audio functions only, without globally blacklisting the GT 710's driver. Changes become active after a separate reboot; no VM is created.
- Configures queued Gmail smarthost delivery for the existing Proxmox sendmail notification target and ZFS/root system mail. The app password is not shown in diffs; the operator verifies delivery after applying.
- Never reboots automatically during `task apply`. The separate operator-run `task reboot` uses Ansible's reboot module and waits for Proxmox and SSH to return. No role installs a guest VM, backup jobs, agent, or cluster services.

## Plan → apply → verify

Requires local Ansible and Task (`task`), working root SSH via the `pve-00` alias, a trusted SSH host key, and a mode-`0600` ignored `.env` with the Gmail app password (see [mail setup](docs/mail.md)). From the repository root:

```sh
ansible-playbook -i inventory site.yml --syntax-check
task plan       # check mode + diff; no host configuration applied
# Review the plan; on a fresh host lacking the slow ZFS pool, creation wipes the HDD:
task apply      # operator-run, modifies the host
# Reboot after GPU/IOMMU changes, in a maintenance window:
task reboot     # reboots pve-00; waits for Proxmox and Ansible reconnect
```

Check mode previews the Proxmox ZFS storage ID changes but does not perform them. Both currently contain no VM/CT volumes; if volumes are added before apply, the rename aborts. The underlying pools are not renamed. On a fresh replacement host, creating `slow` **erases the entire matching HDD**. Package candidates can change when the no-subscription repository is refreshed during apply. `task reboot` is independent of `task apply`, waits up to 15 minutes, then verifies Ansible connectivity.

After apply, verify with `ssh pve-00 'zpool status; pvesm status; pvesm list local-nvme; pvesm list local-hdd'`. Expect `local` to retain its default name and the two ZFS storages to use the new names. A single-disk pool has **no redundancy**; keep independent backups. After the separate reboot, verify both P2000 functions use `vfio-pci` and the GT 710 does not (commands in [GPU passthrough notes](docs/gpu-passthrough.md)); do not assign the GPU to a guest before that check.
