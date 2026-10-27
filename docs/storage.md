# Standalone storage layout

| Proxmox storage | Physical device | ZFS backing | Content | State |
|---|---|---|---|---|
| `local-zfs` (fast) | Samsung 1 TB NVMe | `rpool/data` | VM disks and container roots | Installer-provided; retained |
| `local` | Same NVMe | `/var/lib/vz` on `rpool` | ISO, CT templates, imports, backups | Installer-provided; retained |
| `slow` | HGST 4 TB HDD (`PK2334PBHGMYWR`) | Whole-disk `slow` pool | VM disks and container roots | Already present; retained |
| `nfs-proxmox-template` | NAS `10.0.40.2:/proxmox-template` | NFS | CT templates (`vztmpl`), VM images/templates (`images`) | Added by NFS role |
| `nfs-proxmox-iso` | NAS `10.0.40.2:/proxmox-iso` | NFS | ISO images (`iso`), disk imports (`import`) | Added by NFS role |

The HDD was observed as `/dev/sda` with an existing GPT and three small partitions before the `slow` pool was created. The storage role addresses the disk by stable WWN path `/dev/disk/by-id/wwn-0x5000cca23dd4bfa4`, checks its serial, refuses a mounted disk, and creates the pool only if absent. As of the most recent read-only inspection, `slow` is registered in Proxmox. Re-running the role does not recreate the pool. On another fresh install, creating `slow` **erases the whole HDD**; no NVMe partition is changed.

`roles/proxmox_nfs/` registers only the template and ISO exports. NAS server, export paths and content assignments are in its defaults. CT templates use `vztmpl`; Proxmox VM templates share the `images` content type with VM disks, so the template share can also accept ordinary VM disks. The ISO share additionally accepts imported cloud disk images. The NAS also exports `/proxmox-backup` and `/proxmox-pbs-datastore`, but neither is mapped: backups can be configured through PBS later.

Select `local-zfs` for latency-sensitive guests and `slow` for capacity-oriented VM or container disks. Neither pool is redundant; the NVMe and HDD are separate failure domains, not mirrors. Configure independent backups before placing irreplaceable data on either. After applying, check `zpool status slow` and `pvesm status`.
