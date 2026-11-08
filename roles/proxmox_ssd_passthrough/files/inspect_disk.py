#!/usr/bin/env python3
"""Read-only inspection of one host disk that is meant for VM passthrough.

Usage: inspect_disk.py /dev/disk/by-id/<id>
Prints one JSON object. Never writes to the disk or to any configuration.
"""
import glob
import json
import os
import re
import stat
import subprocess
import sys

QEMU_DIR = "/etc/pve/qemu-server"
LXC_DIR = "/etc/pve/lxc"
STORAGE_CFG = "/etc/pve/storage.cfg"
FSTAB = "/etc/fstab"


def run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 127, ""
    return done.returncode, done.stdout


def flatten(nodes):
    for node in nodes:
        yield node
        yield from flatten(node.get("children") or [])


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def active_lines(text):
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def references(text_lines, needles, real_paths):
    """True when any line names the disk by link, serial, UUID or kernel name."""
    path_res = [re.compile(re.escape(p) + r"(?![A-Za-z0-9])") for p in real_paths]
    for line in text_lines:
        if any(n in line for n in needles) or any(r.search(line) for r in path_res):
            return True
    return False


def main(by_id):
    result = {"by_id": by_id}
    if not os.path.exists(by_id):
        result["present"] = False
        print(json.dumps(result))
        return 0
    real = os.path.realpath(by_id)
    result["present"] = True
    result["real"] = real
    result["is_block"] = stat.S_ISBLK(os.stat(real).st_mode)

    rc, out = run(["lsblk", "-J", "-b", "-o",
                   "NAME,PATH,SIZE,MODEL,SERIAL,TYPE,PTTYPE,FSTYPE,UUID,PARTUUID,PTUUID,LABEL,MOUNTPOINTS", real])
    if rc != 0:
        result["lsblk_error"] = True
        print(json.dumps(result))
        return 0
    nodes = list(flatten(json.loads(out)["blockdevices"]))
    disk = nodes[0]
    descendants = nodes[1:]
    result.update(size=int(disk["size"]), model=(disk.get("model") or "").strip(),
                  serial=(disk.get("serial") or "").strip(), pttype=disk.get("pttype"))
    result["partitions"] = [n["path"] for n in descendants if n.get("type") == "part"]
    result["holders"] = sorted({n["path"] for n in descendants if n.get("type") not in ("part",)})
    result["fstypes"] = sorted({n["fstype"] for n in nodes if n.get("fstype")})

    mounts = []
    for n in nodes:
        for mp in n.get("mountpoints") or []:
            if mp:
                mounts.append(f"{n['path']}={mp}")
    _, swap_out = run(["swapon", "--noheadings", "--raw", "--show=NAME"])
    node_paths = {n["path"] for n in nodes} | {os.path.realpath(n["path"]) for n in nodes}
    swap_active = [s.strip() for s in swap_out.splitlines() if os.path.realpath(s.strip()) in node_paths]
    result["mounts"] = mounts
    result["swap_active"] = swap_active

    links, tokens = set(), set()
    for n in nodes:
        _, link_out = run(["udevadm", "info", "--query=symlink", f"--name={n['path']}"])
        links.update(os.path.basename(x) for x in link_out.split())
        tokens.update(n[k] for k in ("uuid", "partuuid", "ptuuid") if n.get(k))
    serial = result["serial"]
    needles = {x for x in links | tokens if len(x) >= 8}
    needles.add(os.path.basename(by_id))
    if len(serial) >= 8:
        needles.add(serial)
    real_paths = [n["path"] for n in nodes]

    zrc, zout = run(["zpool", "status", "-P"])
    zpool_text = zout if zrc == 0 else ""
    result["zfs_pool_member"] = references(zpool_text.splitlines(), needles | set(real_paths), [])
    result["zfs_member_signature"] = "zfs_member" in result["fstypes"]
    result["lvm_member_signature"] = "LVM2_member" in result["fstypes"]

    vm_refs, ct_refs = [], []
    for directory, sink in ((QEMU_DIR, vm_refs), (LXC_DIR, ct_refs)):
        for conf in sorted(glob.glob(os.path.join(directory, "*.conf"))):
            if references(read_text(conf).splitlines(), needles, real_paths):
                sink.append(os.path.basename(conf)[:-5])
    result["vm_references"] = vm_refs
    result["ct_references"] = ct_refs
    result["storage_cfg_reference"] = references(active_lines(read_text(STORAGE_CFG)), needles, real_paths)
    result["fstab_reference"] = references(active_lines(read_text(FSTAB)), needles, real_paths)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
