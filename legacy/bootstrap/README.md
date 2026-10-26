# Archived Debian bootstrap experiment

These files are historical reference, not a supported installation or storage-management interface. No root or parent Taskfile exports them. Do not run them against the standalone host.

The original experiment installed Proxmox packages on Debian and created a separate data mirror. That storage playbook does not attach a second NVMe to the installed ZFS root pool or prepare a bootable root mirror.

Use the [official-ISO installation guide](../../docs/standalone-installation.md) for a fresh host and the [standalone operator runbook](../../docs/standalone-host.md) for approved post-install configuration. The installation guide also records the separate review required before attaching a future bootable NVMe mirror.

The playbooks and inert examples are retained here to preserve their history. Restoring any bootstrap or disk-provisioning workflow requires a separately reviewed change with explicit targets and execution approval.
