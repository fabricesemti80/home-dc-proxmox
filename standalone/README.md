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

## Go Task and parent inclusion

Direct child tasks are `validate`, `discover`, `plan`, `apply`, `verify`, GPU actions and `reboot`. For example, run `task validate INVENTORY=/absolute/inventory.yml CONFIG=/absolute/host.yml`. There is no standalone task-name prefix or check alias. Plan uses `--check --diff`; apply uses the same playbook and reviewed inputs without check mode.

The control repository includes this Taskfile under a namespace and supplies its local input paths and prepared interpreter:

```yaml
includes:
  proxmox:
    taskfile: ./components/proxmox/Taskfile.yml
    dir: ./components/proxmox
    optional: true
    vars:
      INVENTORY: '{{.ROOT_DIR}}/config/proxmox/inventory.yml'
      CONFIG: '{{.ROOT_DIR}}/config/proxmox/host.yml'
      CONTROLLER_PYTHON: '{{.ROOT_DIR}}/.venv/bin/python3'
```

From control, run `task proxmox:init` once to synchronise main branches, install the declared controller requirements and prepare missing local inputs. Review those inputs, then use bare `task proxmox:plan` and `task proxmox:apply`. Neither operation resynchronises sources or installs dependencies. Ansible apply is a fresh execution, not a saved-plan replay; do not run another init or change inputs between review and apply.

Commands resolve their script from the defining Taskfile directory, not the parent's root. The parent-selected CONTROLLER_PYTHON is passed as PROXMOX_PYTHON; an absolute interpreter also selects ansible-playbook from its bin directory. Direct child use defaults to externally prepared python3. A missing selected interpreter fails instead of falling back. No Taskfile or launcher automatically loads `.env`. Debian bootstrap is historical material under `legacy/bootstrap/`, not an exported task or supported installation path.
