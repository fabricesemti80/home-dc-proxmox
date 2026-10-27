# Standalone storage layout

| Proxmox storage | Physical device | ZFS backing | Content | State |
|---|---|---|---|---|
| `local-nvme` (formerly `local-zfs`) | Samsung 1 TB NVMe | `rpool/data` | VM disks and container roots | Storage ID renamed; pool unchanged |
| `local` | Same NVMe | `/var/lib/vz` on `rpool` | ISO, CT templates, imports, backups | Installer-provided; retained |
| `local-hdd` (formerly `slow`) | HGST 4 TB HDD (`PK2334PBHGMYWR`) | Whole-disk `slow` pool | VM disks and container roots | Storage ID renamed; pool unchanged |
| `nfs-proxmox-template` | NAS `10.0.40.2:/proxmox-template` | NFS | CT templates (`vztmpl`), VM images/templates (`images`) | Added by NFS role |
| `nfs-proxmox-iso` | NAS `10.0.40.2:/proxmox-iso` | NFS | ISO images (`iso`), disk imports (`import`) | Added by NFS role |

The HDD was observed as `/dev/sda` with an existing GPT and three small partitions before the `slow` pool was created. The storage role addresses the disk by stable WWN path `/dev/disk/by-id/wwn-0x5000cca23dd4bfa4`, checks its serial, refuses a mounted disk, and creates the pool only if absent. As of the latest read-only inspection, `slow` is already present. On another fresh install, creating it **erases the whole HDD**; no NVMe partition is changed. Proxmox storage IDs are migrated from `local-zfs` to `local-nvme` and `slow` to `local-hdd` only when they contain no VM/CT volumes. The ZFS pools remain `rpool/data` and `slow`; the default `local` is untouched. Any external automation referencing the old Proxmox storage IDs must be updated.

`roles/proxmox_nfs/` registers only the template and ISO exports. NAS server, export paths and content assignments are in its defaults. CT templates use `vztmpl`; Proxmox VM templates share the `images` content type with VM disks, so the template share can also accept ordinary VM disks. The ISO share additionally accepts imported cloud disk images. The NAS also exports `/proxmox-backup` and `/proxmox-pbs-datastore`, but neither is mapped: backups can be configured through PBS later.

Select `local-nvme` for latency-sensitive guests and `local-hdd` for capacity-oriented VM or container disks. Neither pool is redundant; the NVMe and HDD are separate failure domains, not mirrors. Configure independent backups before placing irreplaceable data on either. After applying, check `zpool status slow` and `pvesm status`.
