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

Every action requires `--inventory ABS --config ABS`. Optional `--host ALIAS` confirms the inventory's unique literal host. Without it, the controller infers that alias only after rejecting empty or multi-host inventories, patterns and unsupported fields. All SSH actions require deployment_enabled true. Missing/disabled NFS and backup entries are unmanaged, never deletion or disable requests. No implicit reboot, VM assignment or local storage creation occurs.

## Optional direct invocation

The root `Taskfile.yml` is already assigned to the deployed `pve-00` roles; it does **not** expose this alternative component's actions. To use this component independently, prepare an isolated Python environment from `requirements.txt` and invoke the wrapper with reviewed absolute input paths:

```sh
bash /absolute/repo/scripts/standalone-host.sh validate --inventory /absolute/inventory.yml --config /absolute/host.yml --host HOST
```

Replace `validate` with `discover`, `plan`, `apply`, `verify`, a GPU action, or `reboot` only after reviewing that action's contract. The wrapper resolves its own `standalone/ansible.cfg`, playbook and module paths and never loads `.env`. Do not run it against `pve-00` alongside the root roles without reconciling their policies. Debian bootstrap under `legacy/bootstrap/` remains historical, not an exported task.
