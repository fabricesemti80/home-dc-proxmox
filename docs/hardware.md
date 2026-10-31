# `pve-00` physical hardware inventory

Read-only inventory of the physical host, captured from `pve-00` by `lsblk`, `lspci`, `dmidecode`, `zpool status`, `sfdisk`, `smartctl` and `proxmox-boot-tool`. The complementary physical slot and DIMM map is in [motherboard.html](motherboard.html); this document records what the machine actually contains today.

Nothing in this document is a change record. Physical work — adding disks, opening the case, altering firmware — is operator-performed.

## Chassis, firmware, and compute

| Item | Observed value |
|---|---|
| System | Dell Precision 7820 Tower (`dmidecode -t system`), board `0G7W4R` revision `A00` |
| Firmware | American Megatrends 5.14, UEFI 2.70; Secure Boot disabled; TPM 2.0 present |
| CPU | 2 × Intel Xeon Gold 6152 (22 cores / 44 threads each) — 88 logical CPUs total |
| Memory | 128 GB installed: 8 × 16 GB Micron `18ASF2G72PDZ-2G6D1` at 2666 MT/s; 4 DIMM sockets empty (`DIMM3`/`DIMM4` on each CPU) |
| Networking | Intel I219-LM onboard NIC (`0000:00:1f.6`) on `nic0`; bridges `vmbr0` (untagged, carries the two LXC veths and the VM tap devices), `vmbr0v40` over `nic0.40`, and `vmbr0v70` over `nic0.70` |
| Graphics | Quadro P2000 `0000:5b:00.0/.1` (guest, `vfio-pci` after apply + reboot); GeForce GT 710 `0000:02:00.0/.1` (host console, firmware primary display) |

GPU link state as sampled on the running kernel: the P2000 has an x16 link with capability and target speed 8 GT/s, but both the card and its root port `0000:5a:00.0` read 2.5 GT/s. VM 4095 was running at the time and owns both P2000 functions through `hostpci0`/`hostpci1`. This is a single sample taken without GPU load, and the cause is not established. It is consistent with idle link-speed power management, but that was not tested. Do not treat 2.5 GT/s as a fault or as the card's usable bandwidth until it is re-sampled under load. The GT 710 runs x1 at 5 GT/s (capability 5 GT/s x8). Drivers in use: `vfio-pci` on the P2000, `nouveau` on the GT 710.

## Block devices

| Device | Model | Capacity | Interface | Persistent ID | Role |
|---|---|---:|---|---|---|
| `nvme0n1` | Samsung `MZVKW1T0HMLH-000L7` | 953.9 GiB | NVMe, `10001:01:00.0`, x4 @ 8 GT/s, behind Intel VMD `0000:9d:05.5` | `nvme-eui.002538c571b0249f`, serial `S3DPNX0J500635` | Boot device and `rpool` member |
| `sda` | HGST `HDS724040ALE640` | 3.6 TiB (4 TB) | SATA, `pci-0000:00:17.0-ata-2`, 6 Gbps link, 512e (512 logical / 4096 physical) | `wwn-0x5000cca23dd4bfa4`, serial `PK2334PBHGMYWR` | `slow` pool member |
| `sr0` | PLDS `DVD+/-RW DU-8A5LH` | 1024 MiB | SATA, `ata-7`, 1.5 Gbps | `PNDVVPLC0091S5K8VA00` | Optical drive |
| `sdb` | Generic SD/MMC reader | 0 B | USB | `28203008282014000` | Card reader, no media |
| `zd*` | — | 1 MiB–100 GiB | ZFS zvols | — | Guest disks on `rpool/data` and `slow` |

SMART self-assessment passed on both data disks. The NVMe reports 0 % used, 100 % spare, and 0 media/data-integrity errors; the HDD reports 0 reallocated and 0 pending sectors. The HDD has 81 945 power-on hours and 15 701 start/stop cycles.

### Partition layout

`nvme0n1` (GPT):

| Partition | Size | Type | Notes |
|---|---:|---|---|
| `nvme0n1p1` | 1 MiB | BIOS boot | Legacy BIOS boot partition |
| `nvme0n1p2` | 1 GiB | EFI System Partition | vfat, filesystem UUID `A0FB-76C4`, PARTUUID `a5065f71-abfd-47ff-92b9-15d646486840` |
| `nvme0n1p3` | 952 GiB | ZFS member | `rpool`, label UUID `16001804364190520235` |

`sda` (GPT):

| Partition | Size | Type | Notes |
|---|---:|---|---|
| `sda1` | 3.6 TiB | ZFS member | `slow`, label name `zfs-c673dfdfec0bbe5f` |
| `sda9` | 8 MiB | ZFS reserved | ZFS label area |

## ZFS pools

OpenZFS `2.4.4-pve1`; both pools are single-disk vdevs with `ashift=12` and no redundancy.

| Pool | Size | Allocated | Member | Mountpoint / datasets |
|---|---:|---:|---|---|
| `rpool` | 944 GiB | 7.62 GiB | `nvme-eui.002538c571b0249f-part3` | `/rpool`; `rpool/ROOT/pve-1` is the root filesystem, `rpool/data` holds LXC 4020 and VM 4090, `rpool/var-lib-vz` backs Proxmox `local` |
| `slow` | 3.62 TiB | 34.4 GiB | `wwn-0x5000cca23dd4bfa4-part1` | `/slow`; holds CT 9007/9008 and VM 4095/4096/4097 disks |

Proxmox storage IDs map onto these pools: `local` is the `rpool/var-lib-vz` directory, `local-nvme` is the `rpool/data` dataset (`images,rootdir`), `local-hdd` is the `slow` pool (`images,rootdir`). See [storage.md](storage.md) for content assignments and NFS exports.

## Boot path

| Item | Value |
|---|---|
| Bootloader | systemd-boot 257.13 managed by `proxmox-boot-tool` (`System currently booted with uefi`) |
| Synced ESP list | `/etc/kernel/proxmox-boot-uuids` contains exactly one entry: `A0FB-76C4` (the ESP on `nvme0n1p2`) |
| Firmware pointers | `LoaderDevicePartUUID` = `a5065f71-abfd-47ff-92b9-15d646486840` (`nvme0n1p2` PARTUUID). `BootOrder` lists handles `0002` then `0000`; `BootCurrent` is `0002` |
| Boot entries | `Boot0002` = "Linux Boot Manager" → `\EFI\systemd\systemd-bootx64.efi` on that ESP, and it is the entry the firmware booted. `Boot0000` = a leftover "Windows Boot Manager" → `\EFI\Microsoft\Boot\bootmgfw.efi`, referring to the pre-Proxmox installation; no `EFI/Microsoft` directory exists on the ESP, so that entry cannot boot |
| Kernel | `7.0.14-26-pve`, cmdline `root=ZFS=rpool/ROOT/pve-1 boot=zfs intel_iommu=on` |

Only one ESP exists, only one entry in the synced-ESP list, and only `Boot0002` is bootable. The host therefore depends on a single NVMe for booting, independently of pool redundancy. `proxmox-boot-tool refresh` syncs the loader and kernel entries to every ESP listed in `proxmox-boot-uuids`, so a second disk becomes independently bootable only after its ESP is added to that list and a firmware entry points at it.

## Free expansion points

| Interface | State |
|---|---|
| AHCI SATA (`0000:00:17.0`, 8 ports implemented) | `ata-2` carries the HGST HDD, `ata-7` the optical drive; `ata-1`, `ata-3`, `ata-4`, `ata-5`, `ata-6`, `ata-8` report link down and are free |
| PCIe root ports | `0000:00:1c.0` (chipset) is free. `10000:00:02.0` and `10000:00:03.0` are free and sit behind the **second** Intel VMD controller `0000:17:05.5`, which owns PCI domain `10000`; the Samsung NVMe hangs off `10001:00:03.0` behind VMD `0000:9d:05.5` (domain `10001`). `0000:00:1c.4` carries the GT 710, `0000:00:1c.7` carries the Texas Instruments XIO2001 PCIe-to-PCI bridge that serves the legacy PCI position, and `0000:5a:00.0` carries the P2000 |

Connector electrical widths for the empty positions are **not** established; SMBIOS reports every slot as "Available" regardless of occupancy. Confirm the printed Dell SLOT label and lane width on-site before selecting a card. See [motherboard.html](motherboard.html).

## Extending the storage

Two separate goals must be decided first, because they are not the same operation:

- **Redundancy** — a second copy of the same data. Implemented by attaching a member to the existing vdev, so usable capacity stays at one member's size.
- **Capacity** — more usable space. Implemented by adding another top-level vdev, which adds no redundancy and does not protect the data.

A ZFS mirror preserves roughly one member's usable capacity. Neither goal is a backup, and neither provides host-level high availability.

### Mirror the HDD pool (`slow`) — lower risk

`slow` holds CT 9007/9008 and VM 4095/4096/4097 disks and is registered as Proxmox storage `local-hdd`. Mirroring it does not change the pool name, so `local-hdd` keeps working untouched.

1. Take and verify an independent backup first. The `nfs-proxmox-backup` export exists but **no backup job is scheduled**; schedule and verify one before touching the pool, and keep physical console access.
2. Install a 4 TB SATA disk with 4096-byte physical sectors (ashift 12) and an actual sector count equal to or larger than the HGST's. Prefer the same model, `HDS724040ALE640`. Plug it into a free AHCI port.
3. Identify it by `ls -l /dev/disk/by-id/ata-*` and confirm the serial with `smartctl -i /dev/sdX`. It must be empty and unmounted; a different model prefix changes the by-id name, so use the by-id path, never `/dev/sdX`.
4. Attach it as a mirror of the existing vdev — `zpool attach slow <new-disk-by-id> wwn-0x5000cca23dd4bfa4` — and **not** `zpool add`, which would create a second data vdev instead of a mirror.
5. Wait for the resilver to finish, then confirm both members are `ONLINE` with no errors: `zpool status slow`. Run `zpool scrub slow` afterwards.
6. The role in `roles/proxmox_storage/` needs no change: its disk-identity and pool-membership assertions still hold, and the pool and Proxmox storage ID are unchanged. Extending that role to manage a mirror member set (for example a future `zpool replace`) is separate, reviewed work.

### Mirror the boot NVMe (`rpool`) — higher risk

`rpool` carries the root filesystem, `rpool/data` (LXC 4020, VM 4090) and `rpool/var-lib-vz` (Proxmox `local`). Mirroring it protects data against disk failure but does **not** by itself make the second disk bootable.

1. Take and verify an independent backup, and confirm console access. The host boots from one ESP on one NVMe; a mistake during this work can leave it unbootable.
2. Install the second NVMe and confirm it enumerates before partitioning anything: `lspci -nn | grep -i non-volatile` and `lsblk`. Under Intel VMD the drive may appear only if the BIOS keeps that lane routed to the controller; a card in a chipset-attached slot normally enumerates directly. Resolve this first — an invisible disk is not a partitioned-disk problem.
3. Give the new disk a partition layout matching `nvme0n1`: a 1 MiB BIOS boot partition, a 1 GiB EFI System Partition, and a ZFS member partition covering the remainder, each with unique GUIDs.
4. Attach the ZFS member to the existing single-disk vdev — `zpool attach rpool <new-disk-part3> nvme-eui.002538c571b0249f-part3` — and **not** `zpool add`. Wait for the resilver and confirm both members are `ONLINE`.
5. Only then make the second disk bootable: register its ESP with `proxmox-boot-tool format <new-disk-part2>` so the UUID joins `/etc/kernel/proxmox-boot-uuids`, run `proxmox-boot-tool refresh` to sync the loader entries to every listed ESP, and add a firmware boot entry for the new ESP so the BIOS can select either disk. `proxmox-boot-tool status` must then list both ESPs.
6. In a maintenance window, verify the host boots from the second NVMe alone and that kernel updates reach both ESPs.

The design checklist for this work is already recorded in [standalone-installation.md](standalone-installation.md#add-the-second-nvme-later); this section reflects the live host state that plan was written against.

### Capacity instead of redundancy

A second 1 TB NVMe added as a top-level vdev would roughly double `rpool` to ~1.9 TiB, but that vdev has no redundancy and its failure takes the root filesystem and `local-nvme` with it. The same caution applies to a second top-level vdev on `slow`. If the goal is more space for guest disks rather than protection for the OS, a separate pool registered as additional Proxmox storage keeps the boot pool simple and the failure domains separate.
