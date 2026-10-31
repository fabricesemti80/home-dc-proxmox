# Standalone storage layout

| Proxmox storage | Physical device | ZFS backing | Content | State |
|---|---|---|---|---|
| `local-nvme` (formerly `local-zfs`) | Samsung 1 TB NVMe | `rpool/data` | VM disks and container roots | Storage ID renamed; pool unchanged |
| `local` | Same NVMe | `/var/lib/vz` on `rpool` | ISO, CT templates, imports, backups | Installer-provided; retained |
| `local-hdd` (formerly `slow`) | HGST 4 TB HDD (`PK2334PBHGMYWR`) | Whole-disk `slow` pool | VM disks and container roots | Storage ID renamed; pool unchanged |
| `nfs-proxmox-template` | NAS `10.0.40.2:/proxmox-template` | NFS | CT templates (`vztmpl`), VM images/templates (`images`) | Added by NFS role |
| `nfs-proxmox-iso` | NAS `10.0.40.2:/proxmox-iso` | NFS | ISO images (`iso`), disk imports (`import`), VM/cloud-init images (`images`) | Added by NFS role |
| `nfs-proxmox-backup` | NAS `10.0.40.2:/proxmox-backup` | NFS | VZDump archives (`backup`) only | Added by NFS role; existing archives preserved |

The HDD was observed as `/dev/sda` with an existing GPT and three small partitions before the `slow` pool was created. The storage role addresses the disk by stable WWN path `/dev/disk/by-id/wwn-0x5000cca23dd4bfa4`, checks its serial, refuses a mounted disk, and creates the pool only if absent. As of the latest read-only inspection, `slow` is already present. On another fresh install, creating it **erases the whole HDD**; no NVMe partition is changed. Proxmox storage IDs are migrated from `local-zfs` to `local-nvme` and `slow` to `local-hdd` only when they contain no VM/CT volumes. The ZFS pools remain `rpool/data` and `slow`; the default `local` is untouched. Any external automation referencing the old Proxmox storage IDs must be updated.

`roles/proxmox_nfs/` registers the template, ISO, and VZDump-backup exports. NAS server, export paths, and content assignments are in its defaults. CT templates use `vztmpl`; Proxmox VM templates share `images` content with VM disks. The ISO export accepts `iso`, imported disks (`import`), and VM/cloud-init images (`images`). The separate `/proxmox-pbs-datastore` export is mounted inside the PBS LXC by `home-dc-terraform/scripts/configure-pbs.sh`; it is not a PVE VZDump storage.

Select `local-nvme` for latency-sensitive guests and `local-hdd` for capacity-oriented VM or container disks. Neither pool is redundant; the NVMe and HDD are separate failure domains, not mirrors. Configure independent backups before placing irreplaceable data on either. After applying, check `zpool status slow` and `pvesm status`.

Both pools are single-disk ZFS vdevs with `ashift=12`. The exact disk models, serials, partition layouts, boot path and free expansion points are recorded in [hardware.md](hardware.md), which also covers mirroring the HDD pool and the boot NVMe.
