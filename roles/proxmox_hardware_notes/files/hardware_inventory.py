#!/usr/bin/env python3
"""Read-only inventory of what the host does with its GPUs and disks.

Prints one JSON object:
  {"gpus":  [{"address", "id", "name", "driver", "vms": [{"vmid", "vm"}]}],
   "usage": {"<kernel disk name>": {"vms": [...], "zfs": {...}|null,
                                    "mounts": [...], "swap": bool}}}

Model, size and media type of the disks come from Ansible facts; this helper only
answers what Ansible facts do not cover (PCI driver binding, VM passthrough
references, ZFS pool membership, mounts). It never writes anything.
"""
import glob
import json
import os
import re
import subprocess

QEMU_DIR = "/etc/pve/qemu-server"
PCI_MAPPING = "/etc/pve/mapping/pci.cfg"
STORAGE_CFG = "/etc/pve/storage.cfg"
PROC_MOUNTS = "/proc/mounts"
PROC_SWAPS = "/proc/swaps"

SD_LIKE = re.compile(r"^((?:sd|vd|hd)[a-z]+)\d*$")
NVME = re.compile(r"^(nvme\d+n\d+)(?:p\d+)?$")
FULL_SLOT = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")
SLOT_NO_FUNCTION = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}$")
TRAILING_ID = re.compile(r"\s*\[([0-9a-f]{4})\]$")


def run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 127, ""
    return done.returncode, done.stdout


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def current_lines(text):
    """Lines of the active VM configuration only: stop at [PENDING] or a snapshot section."""
    lines = []
    for line in text.splitlines():
        if line.startswith("["):
            break
        lines.append(line)
    return lines


def disk_of(device_name):
    """Kernel disk name for a disk or partition name, or None for anything else."""
    for pattern in (SD_LIKE, NVME):
        match = pattern.match(device_name)
        if match:
            return match.group(1)
    return None


def disk_of_path(path, resolve=os.path.realpath):
    real = resolve(path)
    return disk_of(os.path.basename(real)) if real.startswith("/dev/") else None


def normalise_slot(slot):
    slot = slot.strip().lower()
    return "0000:" + slot if slot.count(":") == 1 else slot


def parse_lspci(text):
    """Parse `lspci -D -vmm -nn -k` into GPUs (PCI class 03xx)."""
    gpus = []
    for block in text.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
        class_match = re.search(r"\[([0-9a-f]{4})\]$", fields.get("Class", ""))
        if not class_match or not class_match.group(1).startswith("03"):
            continue
        vendor_id = (TRAILING_ID.search(fields.get("Vendor", "")) or [None, ""])[1]
        device_id = (TRAILING_ID.search(fields.get("Device", "")) or [None, ""])[1]
        gpus.append(
            {
                "address": normalise_slot(fields.get("Slot", "")),
                "id": f"{vendor_id}:{device_id}",
                "name": gpu_name(fields.get("Vendor", ""), fields.get("Device", "")),
                "driver": fields.get("Driver", ""),
            }
        )
    return gpus


def gpu_name(vendor, device):
    vendor = TRAILING_ID.sub("", vendor)
    vendor = re.sub(r"[ ,]+(Corporation|Corp\.?|Inc\.?)$", "", vendor)
    device = TRAILING_ID.sub("", device)
    inner = re.findall(r"\[([^\]]+)\]", device)
    model = inner[-1] if inner else device
    return f"{vendor} {model}".strip()


def parse_pci_mappings(text):
    """name -> list of PCI paths from /etc/pve/mapping/pci.cfg."""
    mappings, name = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            name = line.strip()
            mappings[name] = []
        elif name and line.strip().startswith("map "):
            fields = dict(part.split("=", 1) for part in line.strip()[4:].split(",") if "=" in part)
            if fields.get("path"):
                mappings[name].append(normalise_slot(fields["path"]))
    return mappings


def spec_matches(slot, spec):
    if FULL_SLOT.match(spec):
        return slot == spec
    if SLOT_NO_FUNCTION.match(spec):
        return slot.startswith(spec + ".")
    return False


def read_vms(qemu_dir=QEMU_DIR):
    vms = []
    for path in sorted(glob.glob(os.path.join(qemu_dir, "*.conf"))):
        vmid = os.path.basename(path)[: -len(".conf")]
        lines = current_lines(read_text(path))
        name = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("name:")), "")
        vms.append({"vmid": vmid, "name": name, "lines": lines})
    return vms


def gpu_vms(gpu, vms, mappings):
    owners = []
    for vm in vms:
        for line in vm["lines"]:
            match = re.match(r"^hostpci\d+:\s*(\S+)", line)
            if not match:
                continue
            first = match.group(1).split(",")[0]
            if first.startswith("mapping="):
                specs = mappings.get(first[len("mapping="):], [])
            else:
                specs = [normalise_slot(part) for part in first.split(";")]
            if any(spec_matches(gpu["address"], spec) for spec in specs):
                owners.append({"vmid": vm["vmid"], "vm": vm["name"]})
                break
    return owners


def parse_zpool_status(text, resolve=os.path.realpath):
    """disk name -> pool name, from `zpool status -P`."""
    disks, pool = {}, None
    for line in text.splitlines():
        match = re.match(r"^\s*pool:\s*(\S+)", line)
        if match:
            pool = match.group(1)
            continue
        match = re.match(r"^\s+(/dev/\S+)\s+\S+", line)
        if match and pool:
            disk = disk_of_path(match.group(1), resolve)
            if disk:
                disks[disk] = pool
    return disks


def parse_zfs_storages(text):
    """root pool name -> list of Proxmox zfspool storage IDs from storage.cfg."""
    storages, current = {}, None
    for line in text.splitlines():
        header = re.match(r"^(\w+):\s*(\S+)", line)
        if header:
            current = header.group(2) if header.group(1) == "zfspool" else None
            continue
        match = re.match(r"^\s+pool\s+(\S+)", line)
        if match and current:
            storages.setdefault(match.group(1).split("/")[0], []).append(current)
    return storages


def vm_disk_references(vms, resolve=os.path.realpath):
    refs = {}
    for vm in vms:
        for line in vm["lines"]:
            match = re.match(r"^((?:scsi|sata|virtio|ide)\d+):\s*(/dev/[^,\s]+)", line)
            if not match:
                continue
            disk = disk_of_path(match.group(2), resolve)
            if disk:
                refs.setdefault(disk, []).append({"vmid": vm["vmid"], "vm": vm["name"], "iface": match.group(1)})
    return refs


def mounts_by_disk(mounts_text, resolve=os.path.realpath):
    result = {}
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("/dev/"):
            disk = disk_of_path(parts[0], resolve)
            if disk:
                result.setdefault(disk, []).append(parts[1])
    return result


def swap_disks(swaps_text, resolve=os.path.realpath):
    disks = set()
    for line in swaps_text.splitlines()[1:]:
        parts = line.split()
        if parts and parts[0].startswith("/dev/"):
            disk = disk_of_path(parts[0], resolve)
            if disk:
                disks.add(disk)
    return disks


def build_usage(vms, zpool_text, storage_cfg, mounts_text, swaps_text, resolve=os.path.realpath):
    usage = {}

    def entry(disk):
        return usage.setdefault(disk, {"vms": [], "zfs": None, "mounts": [], "swap": False})

    storages = parse_zfs_storages(storage_cfg)
    for disk, refs in vm_disk_references(vms, resolve).items():
        entry(disk)["vms"] = refs
    for disk, pool in parse_zpool_status(zpool_text, resolve).items():
        entry(disk)["zfs"] = {"pool": pool, "storages": storages.get(pool, [])}
    for disk, mounted in mounts_by_disk(mounts_text, resolve).items():
        entry(disk)["mounts"] = mounted
    for disk in swap_disks(swaps_text, resolve):
        entry(disk)["swap"] = True
    return usage


def main():
    vms = read_vms()
    mappings = parse_pci_mappings(read_text(PCI_MAPPING))
    rc, lspci = run(["lspci", "-D", "-vmm", "-nn", "-k"])
    gpus = parse_lspci(lspci) if rc == 0 else []
    for gpu in gpus:
        gpu["vms"] = gpu_vms(gpu, vms, mappings)
    _, zpool_text = run(["zpool", "status", "-P"])
    usage = build_usage(
        vms,
        zpool_text,
        read_text(STORAGE_CFG),
        read_text(PROC_MOUNTS),
        read_text(PROC_SWAPS),
    )
    print(json.dumps({"gpus": gpus, "usage": usage}, sort_keys=True))


if __name__ == "__main__":
    main()
