#!/usr/bin/python3
"""Reconcile one existing OSD label with monitor auth; never recreate storage."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CLUSTER_FSID = "a74bdf84-c6e5-4a3c-acf2-6c307f5c15a4"


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def validate(labels, osd_uuid):
    if len(labels) != 1:
        raise ValueError("Expected one existing BlueStore device")
    label = next(iter(labels.values()))
    if label.get("ceph_fsid") != CLUSTER_FSID or label.get("osd_uuid") != osd_uuid:
        raise ValueError("OSD identity does not match this cluster")
    return label


def recover(osd_id):
    directory = Path(f"/var/lib/ceph/osd/ceph-{osd_id}")
    device = str(directory / "block")
    osd_uuid = (directory / "fsid").read_text().strip()
    labels = json.loads(run("ceph-bluestore-tool", "show-label", "--dev", device))
    label = validate(labels, osd_uuid)
    key = run("ceph", "auth", "get-key", f"osd.{osd_id}").strip()
    if not key or key.startswith("/"):
        raise ValueError("Invalid monitor key")
    if label.get("osd_key") == key:
        return False
    backup_dir = Path("/root/ceph-recovery-backups")
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    with tempfile.NamedTemporaryFile(mode="w", prefix=f"osd.{osd_id}-label-",
                                     suffix=".json", dir=backup_dir, delete=False) as backup:
        json.dump(labels, backup)
    unit = f"ceph-osd@{osd_id}"
    run("systemctl", "stop", unit)
    try:
        run("ceph-bluestore-tool", "set-label-key", "--dev", device,
            "--key", "osd_key", "--value", key)
        updated = validate(json.loads(run("ceph-bluestore-tool", "show-label", "--dev", device)), osd_uuid)
        if updated.get("osd_key") != key:
            raise ValueError("Label verification failed")
    finally:
        run("systemctl", "start", unit)
    return True


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2 or not sys.argv[1].isdigit():
            raise ValueError("Expected an OSD number")
        print("changed" if recover(sys.argv[1]) else "ok")
    except Exception:
        # Subprocess arguments may contain a key; never print exceptions.
        print("OSD label recovery failed; inspect hardware, identity and monitor auth locally.", file=sys.stderr)
        sys.exit(1)
