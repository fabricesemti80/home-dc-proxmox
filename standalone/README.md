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

## Go Task and parent inclusion

From this repository, run `task standalone:validate INVENTORY=/absolute/inventory.yml CONFIG=/absolute/host.yml HOST=pve-app`. Every standalone task requires all three explicit values and absolute input paths. The `plan`, `apply` and `check` aliases use the same validated standalone entry point.

A parent can include the root Taskfile under a namespace:

```yaml
includes:
  proxmox:
    taskfile: ./components/proxmox/Taskfile.yml
    dir: ./components/proxmox
    optional: true
```

The parent then runs `task proxmox:standalone:validate` with the same explicit variables. Optional inclusion lets parent-only setup commands work before the submodule is initialised; it does not provide a fallback implementation of host tasks.

Commands resolve the standalone script from the defining Taskfile directory, not the parent's root. No Taskfile automatically loads `.env` or installs dependencies. Review and export SSH settings explicitly. Debian bootstrap is historical material under `legacy/bootstrap/`, not an exported task or a supported installation path; use the official ISO installation guide for a new host.
