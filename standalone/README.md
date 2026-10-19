# Standalone host component

See [design and operator runbook](../docs/standalone-host.md) for the exact contract, schema, staged GPU preparation, recovery filenames and offline/live validation boundary. Inputs under examples are inert and contain documentation addresses only. Dependencies in requirements.txt belong in an isolated controller environment.

| Action | Operation |
| --- | --- |
| validate | Offline schema, literal inventory and syntax checks |
| discover | Read-only platform, storage, network, CPU, disks and PCI inspection |
| plan / apply / verify | Preview, configure, or assert baseline plus explicit NFS and backup policy |
| gpu-discover | Read-only PCI functions, groups, drivers, console and boot state |
| gpu-plan / gpu-prepare | Preview or prepare staged next-boot IOMMU/VFIO settings |
| gpu-verify | Read-only active kernel, isolation and vfio-pci checks |
| reboot | Explicit reboot/reconnect and read-only baseline/GPU verification |

Every action requires `--inventory ABS --config ABS --host ALIAS`. All SSH actions require deployment_enabled true. Missing/disabled NFS and backup entries are unmanaged, never deletion or disable requests; to retire schedules use a separate reviewed Proxmox change. No implicit reboot, VM assignment or local storage creation occurs.
