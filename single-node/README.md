# Dell Precision 7820 — standalone Proxmox VE 9

This is the **new, isolated single-node provisioning path**. The repository root contains legacy 3-node/Ceph automation: **do not run root `task apply` on the Dell**.

## 0. Debian 13 installation

Install Debian 13 (trixie) minimal/server, SSH server, and a sudo-capable user. Install to the supplied **1TB NVMe**. Do not select the future ZFS mirror drives during installation. Configure a stable hostname and address; Proxmox requires the hostname to resolve to a non-loopback IP in `/etc/hosts` (for example `10.0.40.10 pve.home.arpa pve`). Ensure Debian repositories have the required components and that `sudo` works.

Proxmox VE 9 on Debian 13 requires a staged kernel installation and reboot. The first `task apply` intentionally stops after installing the Proxmox kernel; reboot and rerun it. Do not remove Debian's kernel until Proxmox is verified.

## 1. SSH from macOS

```bash
ssh-keygen -t ed25519 -a 64 -f ~/.ssh/id_ed25519_homelab -C "homelab-proxmox"
# macOS may not have ssh-copy-id; use brew install ssh-copy-id, or:
cat ~/.ssh/id_ed25519_homelab.pub | ssh YOUR_DEBIAN_USER@SERVER_IP 'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys'
ssh -i ~/.ssh/id_ed25519_homelab YOUR_DEBIAN_USER@SERVER_IP
sudo -v
```

Never disable password authentication until key-based login and sudo are verified. SSH host-key verification stays enabled.

## 2. Clone and configure

```bash
git clone https://github.com/fabricesemti80/home-dc-proxmox.git
cd home-dc-proxmox/single-node
cp .env.example .env
# edit .env, inventory/hosts.yml and inventory/group_vars/all.yml
task init
task ping
task inspect
task plan
task apply
# reboot target into Proxmox kernel, reconnect:
task apply
task verify
```

Install `ansible` and `go-task` on the Mac first. Run all commands from `single-node/`. Do not assume the old Doppler configuration, legacy RSA key, Ceph networks or three-node inventory applies.

## 3. Network

The bootstrap keeps the Debian management interface unchanged by default. Before enabling `task network-apply`, set `pve_management_interface`, address and gateway after `task inspect`. **Network bridge changes can interrupt SSH.** Perform the change with physical/iDRAC console access, confirm that the management IP is not simultaneously assigned to the physical NIC, and inspect `/etc/network/interfaces` for conflicting DHCP/static definitions. Do not run this step remotely without a recovery path.

## 4. ZFS mirror

The included 1TB NVMe remains the Proxmox OS disk. Once two new 1TB SN700 drives are physically installed and identified, configure their **stable** `/dev/disk/by-id/` paths in `pve_mirror_devices`.

The mirror is intentionally **not** created by `task apply`. It is destructive. Run `task inspect` and confirm the devices are not the OS drive, then run:

```bash
task storage-plan
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags storage -e pve_storage_apply=true -e pve_storage_confirm=ERASE-NEW-MIRROR-DRIVES
```

Never use `zpool create -f` to bypass disk safety checks. Proxmox ZFS storage is registered as `tank-vm`. NAS NFS exports are disabled until confirmed.

## 5. Remaining integration

The first iteration deliberately excludes API token generation and automatic SSH/network hardening, because the original implementation assumes an existing cluster and may expose tokens or lock out a fresh host. Terraform credentials, NFS export discovery, backup job idempotency, SMART/ZFS monitoring and GPU passthrough require verification before this is considered a **complete** build. Do not merge until the PR checklist and first-host validation are satisfied.
