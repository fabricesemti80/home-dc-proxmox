# Debian 13 bootstrap and local mirror

This supplements the tested standalone management interface in PR #3. Run it **once**, before standalone apply. The official Proxmox ISO remains a supported alternative and does not need this stage.

## Mac SSH and dependencies

```sh
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/id_ed25519_homelab
cat ~/.ssh/id_ed25519_homelab.pub | ssh YOUR_USER@SERVER_IP 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
ssh -i ~/.ssh/id_ed25519_homelab YOUR_USER@SERVER_IP 'sudo -v'
python3 -m venv .venv
. .venv/bin/activate
pip install -r standalone/requirements.txt
```

Install go-task separately. Clone this repo, copy `.env.example` to `.env`, and configure an inventory file outside the repository using `bootstrap/inventory.example.yml` as a guide. Export `ANSIBLE_PRIVATE_KEY_FILE` or let go-task load it from `.env`. Ensure SSH host keys are verified.

## Run

```sh
task bootstrap:ping BOOTSTRAP_INVENTORY=/absolute/path/inventory.yml
task bootstrap:plan BOOTSTRAP_INVENTORY=/absolute/path/inventory.yml -- -e pve_bootstrap_management_ip=10.0.40.10
task bootstrap:apply BOOTSTRAP_INVENTORY=/absolute/path/inventory.yml -- -e pve_bootstrap_management_ip=10.0.40.10
# First run installs kernel then stops; reboot manually into PVE kernel.
task bootstrap:apply BOOTSTRAP_INVENTORY=/absolute/path/inventory.yml -- -e pve_bootstrap_management_ip=10.0.40.10
```

After this, use the existing `standalone:validate/discover/plan/apply/verify` workflow and the documented explicit absolute config/inventory arguments. GPU preparation remains **disabled** by default; its discovery path can be used without a target VM.

## Mirror (optional)

The supplied 1TB boot NVMe must **not** be one of the selected disks. Inspect `lsblk -f`, `findmnt /`, `ls -l /dev/disk/by-id`, and `wipefs -n` on each intended new disk before proceeding. This playbook rejects drives with existing signatures and requires explicit confirmation; it does not wipe signatures or use force.

```sh
ansible-playbook -i /absolute/path/inventory.yml bootstrap/storage.yml \
  -e '{"mirror_disks":["/dev/disk/by-id/DRIVE_A","/dev/disk/by-id/DRIVE_B"],"mirror_confirm":"ERASE-TWO-SELECTED-DISKS"}'
```

**Networking:** keep the initial Debian IP working. Converting its management NIC to `vmbr0` is a separate console-assisted operation: the existing Debian NIC configuration must be removed/replaced, not duplicated. Do not blindly apply an SSH-based bridge change. Confirm the final bridge before Terraform creates VMs.

**Boundaries:** Bootstrap does not provision API tokens, NAS exports or backup jobs. These are managed by the existing standalone component where supported. Real hardware validation, reboot, bridge transition, restore tests and CI checks remain necessary.
