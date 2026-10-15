# Ceph recovery

`task ceph-recovery` runs `recover_ceph.yml` against all three existing Proxmox hosts. This is recovery of the existing cluster, not provisioning or disk repair.

## Design and assumptions

- The existing cluster FSID is `a74bdf84-c6e5-4a3c-acf2-6c307f5c15a4`; pve-0/1/2 each have one existing OSD, numbered 0/1/2. Every host has an existing monitor, manager and MDS directory. Fail rather than create missing daemon identities or operate on another cluster.
- At least two monitors must already have quorum. Existing monitor auth records are authoritative. Reconcile manager, MDS and OSD keyrings with those records; never rotate keys or change capabilities.
- A readable OSD BlueStore label must match both the OSD UUID and cluster FSID. Only update its `osd_key` if different, while that OSD is stopped. Save root-only backups first. Never repair, zap, format, remove or recreate disks/OSDs.
- Recover one host at a time. Enable daemon targets and instances; start stopped services, and restart running daemons only when their keyring changed. Healthy monitors remain running.
- Reconcile the existing Proxmox CephFS secret and RBD keyring with `client.admin`, as configured in this lab. The shared pmxcfs files are updated once. Do not introduce additional capabilities or identities. Credentials and backups stay on the servers and Ansible suppresses secret task output/diffs.
- Success requires all three monitors in quorum, all three OSDs up/in, all three managers and MDS daemons registered, healthy CephFS ranks, `HEALTH_OK`, every PG `active+clean`, and both Proxmox Ceph storage entries active on every host. Time out with failure after 30 minutes; do not weaken replication or suppress warnings.
- Full inventory execution is required. `--limit` is rejected. `--check` is explicitly rejected because safe recovery and final health validation require real execution; use `--syntax-check` for offline validation.

## Usage and validation

```sh
task ceph-recovery
ansible-playbook -i inventory recover_ceph.yml --syntax-check
python3 -m unittest discover -s tests -p 'test_ceph_recovery.py'
```

The Taskfile uses the existing `run-playbook` wrapper and its Doppler/SSH configuration. No new dependency or automatic reboot is introduced. Run a second time to verify the repair is idempotent.

## Incident context (2026-10-15)

The pve-1 NVMe controller became inaccessible on 2026-10-14. The operator reboot restored the device, but the OSD could not authenticate: its keyring and persistent BlueStore `osd_key` contained a file path from the recent credential rotation. The manager/MDS parent targets were disabled, and the shared Proxmox CephFS secret was stale. Restoring daemon credentials, correcting the label offline, and enabling the targets restored daemon registration. Ceph reached `HEALTH_OK` with 145 `active+clean` PGs before Proxmox storage credential reconciliation.

The NVMe reported 73-74 C with historical thermal warning/critical time. Recovery does not establish hardware reliability. Inspect cooling/power/controller/drive if failures recur; software repair is inappropriate while the device is inaccessible.

## Rollback and limits

Ansible keyring/Proxmox storage copies use server-side backups; BlueStore label backups are root-only files under `/root/ceph-recovery-backups/`. Do not commit or print these files. If a repair is interrupted, rerun after verifying hardware access and monitor quorum. Before restoring a backup, stop only its affected daemon and confirm the monitor's current key: the previous values may already be invalid. Restore only the `osd_key`, never overwrite unrelated label metadata or cluster maps. Target enablement is intentional so all existing daemons return after reboot.

This task does not recover lost monitor quorum, damaged media, corrupted BlueStore, missing daemons, unrelated failed services, or application data. It fails for those conditions. Application endpoint checks, backup restore tests and a second host reboot remain separate checks. Existing kernel mounts can retain old credentials after the shared secret changes; the task deliberately fails its storage gate rather than forcibly detaching a mount with possible users. Reconnect affected snippet-only mounts after verifying no users, then rerun recovery.

## Legacy maintenance retirement

Kestra's live `homelab.ops` namespace contains the maintenance and recovery workflows. The old Sunday cron restarted all Ceph service targets without sequencing or health gates. Remove that cron and its installed executable on all hosts, remove its manual Taskfile/shell entry points, and keep the old role as cleanup-only so future provisioning cannot recreate it. Preserve historical log files and unrelated diagnostics/recovery commands. Roll back only by deliberately restoring the previous role and schedule; never re-enable it during a Kestra outage operation.

The live repair also reconnected the unused Proxmox CephFS mounts on pve-0 and pve-2 after credential reconciliation; pve-1 mounted normally. VM RBD disks were not unmounted.

## Completed verification (2026-10-15)

The second complete recovery run passed on all three hosts with `changed=0`, `failed=0`, and `unreachable=0`. All three monitors, managers, MDS daemons and OSDs registered; all 145 PGs were `active+clean`; both Proxmox Ceph storage entries were active on every host. The legacy maintenance cleanup subsequently removed the cron and executable on all three hosts. Five unit tests, playbook syntax checks, shell syntax and `git diff --check` passed.

A later live SMART check on pve-1 reported 78 C and `critical_warning=0x2` (temperature), with controller thresholds of 350 K (about 77 C warning) and 352 K (about 79 C critical). Cluster health does not establish drive reliability. Cooling and replacement assessment remain necessary; the exact cause of the controller failure is unproven.
