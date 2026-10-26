# Standalone Proxmox VE host configuration

Configure a previously installed official-ISO PVE 9 / Debian 13 host through a single validated entry point. The private parent owns inventory and reviewed configuration; this public component has inert examples only.

For a fresh Dell Precision 7820, start with the [standalone installation guide](docs/standalone-installation.md). It covers BIOS settings, replacing Windows on the Samsung NVMe with a single-disk ZFS installation, preserving the 4 TB HDD, and planning a later bootable NVMe mirror.

Read the [design and operator runbook](docs/standalone-host.md), [action reference](standalone/README.md) and [example inputs](standalone/examples). Install controller dependencies externally in an isolated environment using standalone/requirements.txt, then:

```sh
bash /absolute/home-dc-proxmox/scripts/standalone-host.sh validate \
  --inventory /absolute/home-dc-proxmox/standalone/examples/inventory.yml \
  --config /absolute/home-dc-proxmox/standalone/examples/host.yml --host pve-app
```

Supported actions: validate, discover, plan, apply, verify, gpu-discover, gpu-plan, gpu-prepare, gpu-verify, reboot. Every action requires explicit absolute inputs and one literal host. Root site.yml fails closed; Task defaults list commands. Optional NFS and explicit backup jobs are managed without touching disks, pools or unrelated jobs. GPU preparation is staged, never reboots automatically and never assigns devices to VMs.

The legacy cluster entry points are archived in legacy/ for historical reference. Remaining root specialist playbooks, inventory, roles and hack scripts also belong to that legacy implementation. None is used by standalone; they are not suitable for this host and may be destructive. Do not use legacy instructions to prepare a standalone installation.

Offline checks:

```sh
python3 -m unittest discover -s tests -p 'test_standalone*.py' -v
```

No host operation, NAS test, backup or reboot is implied by offline validation.
