# Standalone Proxmox installation

Install one Dell Precision 7820 from the Proxmox VE ISO, replacing Windows on the Samsung NVMe. Start with a single-disk ZFS root pool and add a second NVMe as a bootable mirror later.

This is a human-operated installation guide, not authorisation for an agent to change firmware, install an OS, erase disks or operate infrastructure. The operator must approve the exact target disk before installation. Do not run the legacy cluster, Ceph, Keepalived or bulk deployment tasks from this repository on the new host.

## Confirm the hardware

Windows Device Manager identified these devices during preparation:

| Device | Observed role |
|---|---|
| Samsung NVMe, model prefix `MZVKW1T0` | Intended OS disk. The prefix identifies a 1 TB model; confirm its reported capacity and serial before erasure. |
| HGST `HDS724040ALE640` | 4 TB SATA HDD. Leave it untouched during this installation. |
| SanDisk Ultra USB 3.0 | Ventoy installation media. Never select it as the installation target. |
| ODD-0 | Optical-drive port, not the NVMe disk. |

The received HDD is 4 TB, not the 8 TB previously recorded from the listing. Use observed models, capacities and serials rather than the listing or assumptions about Linux device names. CPU, RAM and GPU specifications still need physical or system-inventory verification.

Before replacing Windows, this read-only PowerShell command records disk identities and boot roles:

```powershell
Get-Disk | Select-Object Number, FriendlyName, SerialNumber, BusType, Size, IsBoot, IsSystem | Format-List
```

Back up any data that must survive. Installing onto the Samsung removes its Windows installation and other existing partitions. The HDD's eventual storage role is a separate decision.

## BIOS checklist

Press **F2** at the Dell logo. Record the BIOS version and photograph existing settings before changing them. Menu wording can vary by firmware version.

| Menu | Setting | Value |
|---|---|---|
| General > Boot Sequence | Boot List Option | UEFI |
| General > Advanced Boot Options | Enable Legacy Option ROMs / Enable Attempt Legacy Boot | Disabled for this UEFI-only installation |
| Secure Boot | Secure Boot Enable | Disabled for the current Ventoy installation path |
| System Configuration > SATA Operation | SATA mode | AHCI |
| System Configuration > USB Configuration | USB Boot Support and ports in use | Enabled |
| Virtualization Support | Intel Virtualization Technology | Enabled |
| Virtualization Support | VT for Direct I/O | Enabled for future PCI passthrough |
| Virtualization Support | Trusted Execution | Disabled |
| Performance | Multi Core Support | All |
| Performance | Hyper-Thread Control | Enabled |
| System Configuration | Memory Map IO above 4GB | Enabled for the planned PCI/GPU passthrough |
| System Configuration | SMART Reporting | Enabled |

Leave SpeedStep, Turbo Boost, C-states, fan settings and Intel VMD at their existing defaults initially. For automatic restart after power returns, deliberately select Power Management > AC Recovery > Power On. Otherwise leave that policy unchanged.

RAID On is a controller mode, not proof that an array exists. The identified hardware has one SATA HDD and one NVMe. AHCI exposes SATA disks individually and avoids an unnecessary firmware RAID dependency. Changing SATA mode can prevent the old Windows installation from booting. If an existing RAID volume or separate MegaRAID controller is discovered, stop and identify its members before changing the storage configuration. Do not initialise or delete arrays.

Do not clear the TPM or delete Secure Boot keys. Current Proxmox supports Secure Boot; disabling it here is a choice for this installation path, not a general Proxmox requirement.

Run **F12 > Diagnostics** before installation to check the newly arrived hardware. Do not attempt GPU binding or passthrough preparation during OS installation. Preserve working display output and physical recovery access.

## Boot the correct installer

The installer prepared for this handoff is the **Proxmox VE 9.2-1 Intel/AMD ISO**, `proxmox-ve_9.2-1.iso`. Obtain installers from the official download page and verify their published SHA-256 checksum before use. Do not choose the ARM64 image for this Xeon host.

The Proxmox ISO includes Debian and Proxmox packages. Do not first install Debian from its separate netinst ISO for this workflow. The standard Debian guided installer does not offer ZFS root installation. An ext4/LVM installation does not become a ZFS-root mirror merely by adding another disk later.

1. Insert the Ventoy USB into the Dell.
2. Restart and repeatedly press **F12** to open the one-time boot menu.
3. Select the **UEFI USB** entry, not Windows Boot Manager.
4. In Ventoy, select `proxmox-ve_9.2-1.iso`, not a Debian, Talos or other ISO.
5. Choose **Install Proxmox VE (Graphical)**. If graphics fail, use **Install Proxmox VE (Terminal UI)**.
6. Accept the licence and continue to the target-disk screen.

Saving BIOS settings alone does not select the USB for the next boot. If it is missing from the F12 menu, try a rear USB port directly without a hub. Stop rather than changing unrelated disk settings.

## Select the single-NVMe ZFS layout

At **Target Harddisk**, open **Options** and review every selected device.

| Setting | Choice |
|---|---|
| Filesystem | ZFS (RAID0) |
| Selected disk | Samsung NVMe only, matched by model and capacity |
| Every other disk selector | Do not use, or the equivalent unselected option |
| ashift | 12 |
| Compression | On |
| Checksum | On / installer default |
| Copies | 1 |
| ARC maximum size | Leave the installer default |
| hdsize | Leave the full-disk default |

With only one disk selected, the RAID0 option creates a single-disk ZFS pool. It does not provide redundancy. Do not select RAID1 before the second NVMe exists, and do not include the HGST HDD as a temporary mirror member.

The installer creates the boot partitions, the `rpool` ZFS root pool and the `rpool/data` VM-storage dataset. The normal ZFS storage entry is `local-zfs`. Do not assume an ext4/LVM installation's `local-lvm` entry will exist. No manual EFI, `/boot`, LVM or swap partitioning is needed for this path.

Until a mirror is attached and fully resilvered, failure of the single NVMe loses the installation and any VM data stored on it. Keep backups independent of that disk.

## Location, credentials and network

Select the actual country, timezone and keyboard layout. Set a strong root password and an email address monitored for notifications. Never record passwords, private keys or tokens in Git, screenshots or agent handoffs.

| Network field | Choice |
|---|---|
| Management interface | Ethernet port connected to the intended management LAN |
| Hostname/FQDN | Stable host name, for example `pve-app.home.arpa`; use the site's chosen naming scheme |
| IP address/CIDR | Unused, stable management address on the actual LAN |
| Gateway | Router address for that subnet |
| DNS server | Working LAN DNS server |

Review values obtained automatically. Keep the management address outside the DHCP allocation range or reserve/exclude it in the DHCP server. Do not copy legacy cluster addresses or invent network values. Confirm the intended endpoint before installation.

## Final destructive-action check

Before clicking **Install**, confirm all of these on the summary screen:

- The Samsung NVMe is the only selected installation disk.
- Its identity and capacity match the intended Windows replacement target.
- The filesystem is ZFS, not ext4.
- The 4 TB HGST HDD and SanDisk USB are excluded.
- The hostname, management interface, IP/CIDR, gateway and DNS are correct.
- Required data has been backed up and the operator approves erasure of the Samsung.

If the selection or summary is ambiguous, stop and inspect it before writing changes. Do not select all disks or run an additional wipe command.

After installation, remove the USB when prompted and boot the internal NVMe. From a laptop on the management network, open `https://<management-IP>:8006`. Log in as `root` using the **Linux PAM** realm. The initial certificate is self-signed; confirm the endpoint before accepting it.

Record the installed Proxmox version, actual hardware identities and management endpoint in the approved local inventory. Confirm `rpool` is healthy and `local-zfs` is available before provisioning anything. Installation does not authorise VM creation, Talos bootstrap, GPU binding, Ceph changes or workload migration. Updates and later host configuration need their own reviewed execution scope.

## Add the second NVMe later

This is a design and safety checklist, not an executable migration procedure. Do not run disk-partitioning or ZFS attachment commands until the new device and current pool have been inspected and the exact targets approved.

1. Take independent backups and verify recovery access before changing the boot pool.
2. Identify both NVMes by persistent device ID, model, serial and exact capacity. The new disk must accommodate the existing partition layout and ZFS member. The same advertised capacity does not guarantee the same usable sector count; an equal-or-larger actual device is required.
3. Prepare the new disk's boot and ZFS partitions without overwriting the original NVMe or the HDD. Give the new disk and partitions unique identifiers.
4. **Attach** its ZFS partition to the existing single-disk vdev to form a mirror. Do not use a pool **add** operation, which would create another top-level data vdev rather than mirror the original.
5. Wait for resilvering to finish and confirm both mirror members are online with no pool errors.
6. Prepare the new EFI System Partition using the installed host's verified bootloader and `proxmox-boot-tool` procedure. Register and refresh it as required. Do not guess the bootloader from file presence alone.
7. Under an approved maintenance window, verify the host can boot independently from either NVMe and that both are managed correctly for future kernel updates.

Mirroring the ZFS member alone does not make the second disk independently bootable. A mirror preserves roughly one member's usable capacity, not the sum of both disks. It improves disk-failure tolerance but is not a backup and does not provide physical-host high availability.

## References

- [Proxmox VE installation guide](https://pve.proxmox.com/pve-docs/chapter-pve-installation.html)
- [Official Proxmox VE ISO downloads](https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso)
- [Proxmox ZFS administration](https://pve.proxmox.com/wiki/ZFS_on_Linux)
- [Proxmox host bootloader and EFI management](https://pve.proxmox.com/wiki/Host_Bootloader)
- [OpenZFS device attachment and mirror conversion](https://openzfs.github.io/openzfs-docs/man/master/8/zpool-attach.8.html)
- [Dell Precision 7820 BIOS system configuration](https://www.dell.com/support/manuals/en-us/precision-7820-workstation/precision_7820_om_pub/system-configuration?guid=guid-2e6f0d4e-9226-42ef-8cad-d396bfa96abd&lang=en-us)
