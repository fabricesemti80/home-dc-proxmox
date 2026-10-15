#!/usr/bin/python3
"""Fail unless the lab's full daemon fleet and all PGs are healthy."""
import json
import subprocess
import sys

EXPECTED = {"pve-0", "pve-1", "pve-2"}


def healthy(status, quorum, managers, filesystems, pgs):
    osds = status["osdmap"]
    pgs = pgs["pg_summary"]
    mgrs = {managers.get("active_name")} | {m["name"] for m in managers.get("standbys", [])}
    mds = {s["name"] for s in filesystems.get("standbys", [])}
    maps = [fs["mdsmap"] for fs in filesystems.get("filesystems", [])]
    for fs in maps:
        mds.update(m["name"] for m in fs["info"].values())
    return (
        status["health"]["status"] == "HEALTH_OK"
        and set(quorum["quorum_names"]) == EXPECTED
        and osds["num_osds"] == osds["num_up_osds"] == osds["num_in_osds"] == 3
        and managers.get("available") is True and mgrs == EXPECTED
        and mds == EXPECTED and len(maps) == 1
        and all(not fs.get("failed") and not fs.get("damaged")
                and len(fs["in"]) == fs["max_mds"]
                and len(fs["up"]) == fs["max_mds"]
                and all(m["state"] == "up:active" for m in fs["info"].values()) for fs in maps)
        and pgs["num_pgs"] > 0
        and sum(s["num"] for s in pgs["num_pg_by_state"] if s["name"] == "active+clean") == pgs["num_pgs"]
    )


if __name__ == "__main__":
    try:
        commands = [("status",), ("quorum_status",), ("mgr", "dump"), ("fs", "dump"), ("pg", "stat")]
        data = [json.loads(subprocess.run(["ceph", *cmd, "--format", "json"],
                check=True, capture_output=True, text=True, timeout=30).stdout) for cmd in commands]
        ok = healthy(*data)
        print("All daemons registered; all PGs active+clean; HEALTH_OK." if ok else
              "Recovery incomplete: require 3 monitors, 3 managers, 3 MDS, 3 OSDs up/in and all PGs clean.")
        sys.exit(0 if ok else 1)
    except (subprocess.SubprocessError, ValueError, KeyError, TypeError):
        print("Unable to verify complete Ceph recovery.", file=sys.stderr)
        sys.exit(1)
