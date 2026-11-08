# SSD passthrough preparation (Longhorn disks)

Three unused Crucial MX500 500 GB SATA SSDs (465.76 GiB) on `pve-00` are reserved as raw, whole-disk passthrough devices for the Talos app-cluster workers. Talos then uses them for Longhorn (see `home-dc-kubernetes`). They are **not** a Proxmox storage and **not** a ZFS/LVM member; the host never formats or mounts them.

This repository only prepares and guards the host (`roles/proxmox_ssd_passthrough/`). Attaching the disks to VMs is done by OpenTofu in `home-dc-terraform`; Talos configuration lives in `home-dc-kubernetes`. **Nothing here changes a VM, and nothing was applied live when this was written.**

## Assignment (single source of truth: role defaults `proxmox_ssd_passthrough_disks`)

| VMID | VM | Stable host path (`/dev/disk/by-id/…`) | Serial | Guest interface |
|---|---|---|---|---|
| 4095 | `k8s-wrkr-01-gpu` | `ata-CT500MX500SSD1_2344E8836BF7` | `2344E8836BF7` | `scsi2` |
| 4096 | `k8s-wrkr-02` | `ata-CT500MX500SSD1_2344E8836D00` | `2344E8836D00` | `scsi2` |
| 4097 | `k8s-wrkr-03` | `ata-CT500MX500SSD1_2349E8875927` | `2349E8875927` | `scsi2` |

Never use `sdX` names; they were `sdd`, `sda`, `sdc` at inspection time and can change at any boot. The old contents (GPT, EFI vfat, ext4, swap; two disks carry identical GPT and partition UUIDs) are obsolete. One disk has 3 pending sectors; the owner accepted it and all three are used unconditionally. Each guest sees about 465 GiB next to its 55 GiB system disk (`scsi0`) and 100 GiB `local-path` data disk (`scsi1`), so Talos selectors must discriminate by size.

## What the role does

Everything below runs on every `task apply` / `task ssd-passthrough-plan`, in check mode as well, and is read-only except where stated:

1. **Identity**: each by-id path must exist, be a block device, match the serial, contain `MX500` in the model and be exactly 500107862016 bytes. Anything else aborts.
2. **Host-use guard** (always): refuse if any partition is mounted or active swap, has a device-mapper/LVM/md holder, is in a `zpool status -P` pool, is named in `/etc/fstab`, `/etc/pve/storage.cfg` or any LXC config, or is referenced by a VM config other than its assigned VMID. Matching covers by-id/WWN/UUID links, the serial, partition and table UUIDs and kernel names, so reuse of the duplicated UUIDs is caught.
3. **udev rule** `/etc/udev/rules.d/99-pve-passthrough-ssd.rules` sets `UDISKS_IGNORE=1` for the three serials (defence against desktop-style automounters). After writing the rule the role reloads udev, replays a `change` event only for block devices with these serials (`udevadm trigger --action=change --property-match=ID_SERIAL_SHORT=…`, disks and partitions) and waits for `udevadm settle`, so it is active immediately rather than at the next reboot. Nothing is triggered in check mode or when the rule file is unchanged. It is not the primary protection; the primary protection is that no host config references the disks and the guard above fails the run if one ever does. No LVM or ZFS configuration is edited.
4. **Guarded wipe** (default **off**), see below.
5. **SMART**: `smartctl` must be able to read each disk (a command/open error fails the run; the pending-sector warning does not). The pending/reallocated counts are printed. Ongoing monitoring reuses the existing hardware-monitoring role: its `prometheus-node-exporter-smartmon` timer scans all SATA disks, so the SSDs appear automatically as `smartmon_*` series on the mTLS listener, and the infra-cluster `DiskBadSectors` / `DiskWear*` rules already match `job="pve-host-hardware"` (see `home-dc-kubernetes/.../victoriametrics/config/rules.yaml`). Expect `DiskBadSectors` to fire for the disk with pending sectors; that is the known, accepted condition. The role additionally writes `ssd_passthrough.prom` (`pve_passthrough_disk_assignment_info{vmid,vm,serial_number,interface}`) into the node-exporter textfile directory (only if it exists) so a SMART series can be joined to its VM on `serial_number`. No alert rule is changed in this repository.

### Guarded wipe

`proxmox_ssd_passthrough_wipe_signatures` defaults to `false`; with it off the role neither wipes nor fails. To erase the old signatures (once, before the first attach):

```sh
ansible-playbook -i inventory site.yml --tags ssd-passthrough --check --diff \
  -e proxmox_ssd_passthrough_wipe_signatures=true        # preview: "Would wipe …", nothing written
task ssd-passthrough-apply -- -e proxmox_ssd_passthrough_wipe_signatures=true   # operator-run, destructive
```

It only touches the explicit by-id list in the defaults, and additionally refuses when a disk is referenced by **any** VM config (including its own VMID), or still carries a ZFS or LVM member signature. It runs `wipefs --all --force` on the partitions and then on the disk (removing both GPT copies and the protective MBR); it never creates a partition table or filesystem. After the first successful wipe the step is a no-op. Never enable it after the disks are attached to running VMs; the guard refuses, so do not work around it.

## Validation

Without touching the host: `ansible-playbook -i inventory site.yml --syntax-check`. The role logic (identity, mount/VM-reference/own-VM guards, wipe refusal, check-mode preview, real wipe and idempotence) was exercised against a throw-away loop device in a Debian 13 container, never against the real disks. Against the host, `task ssd-passthrough-plan` shows only the udev rule and assignment metric as pending creations on the first run; with the wipe off no disk change or failure appears.

After a real apply, verify: `lsblk -o NAME,SIZE,SERIAL,FSTYPE,MOUNTPOINTS` shows no mounts, `zpool status` and `swapon --show` do not list the disks, `ls /etc/udev/rules.d/99-pve-passthrough-ssd.rules`, `smartctl -H /dev/disk/by-id/…` passes, and a second `task ssd-passthrough-plan` reports no changes.

## Assumptions

- The by-id names and serials above are correct and stable (checked read-only earlier by the owner; the role re-checks every run).
- Debian 13/PVE 9 `lsblk` supports JSON and `MOUNTPOINTS`; `smartmontools` and `python3` are present (the hardware-monitoring role and Ansible already rely on them).
- PVE 9 has no LVM or ZFS use of these disks; the guard turns any contrary finding into a failure instead of an edit.
- While a guest owns the disk, the host kernel still sees the device and its partitions but never mounts them. Do not run host tools (fsck, wipefs, mount) on a device a running VM owns.

## Operator steps for the later live rollout

Order matters; each step is a separate, reviewed action.

1. Merge and apply this role: `task ssd-passthrough-plan`, then `task ssd-passthrough-apply` (wipe off). Review the printed SMART counts.
2. Optionally wipe old signatures with the explicit opt-in command above, after confirming with `lsblk` the disks are the three listed serials and VMs do not reference them.
3. Apply the `home-dc-terraform` change that adds `scsi2` to VMs 4095–4097 (root@pam is required by Proxmox for host block devices; see that repository's PR). A VM stop/start may be needed to attach; do one worker at a time and drain/cordon its Kubernetes node first so Longhorn and workloads are not disrupted.
4. Merge the `home-dc-kubernetes` Talos change (extensions, size-based selectors) and upgrade/apply nodes one at a time, then deploy Longhorn.
5. Verify in each guest that exactly one ~465 GiB disk is visible and that the `local-path` user volume still selects only the 100 GiB disk.

## Rollback

- Before attachment: delete `/etc/udev/rules.d/99-pve-passthrough-ssd.rules` (`udevadm control --reload`) and `/var/lib/prometheus/node-exporter/ssd_passthrough.prom`, then revert the role. No data on the disks was needed.
- After attachment: detach `scsi2` via OpenTofu (revert the PR) with the VM stopped; the disk then belongs to the host again unused. Wiped signatures cannot be restored; they were obsolete.
- The role never changes ZFS pools, `storage.cfg`, LVM, fstab, or VM definitions.
