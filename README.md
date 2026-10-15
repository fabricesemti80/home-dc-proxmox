# Proxmox VE Cluster Automation

Ansible-based infrastructure automation for deploying and managing a 3-node Proxmox Virtual Environment cluster with Ceph storage, NFS integration, and Gmail SMTP notifications.

## Overview

This project automates the complete setup of a production-ready Proxmox cluster with:

- **3-node Proxmox VE cluster** with high availability
- **Keepalived HA** with floating VIP (10.0.40.15) for GUI access
- **Ceph distributed storage** using NVMe drives
- **Dual network configuration** (management + Ceph networks)
- **NFS storage integration** for backups, ISOs, and templates
- **Automated backup jobs** for VMs and templates with retention policies
- **Gmail SMTP notifications** for cluster alerts and backup status
- **API tokens** for automation tools (Packer, Terraform)
- **Resource pools** for organizing VMs and storage
- **Chrony NTP** time synchronization across all nodes
- **SSH key deployment** and security hardening

## Architecture

- **Nodes:** pve-0, pve-1, pve-2 (10.0.40.10-12)
- **Management Network:** 10.0.40.0/24 (vmbr0 bridge)
- **Ceph Network:** 10.0.70.0/24 (eth0 interface)
- **NFS Server:** 10.0.40.2
- **Base OS:** Debian 12

### Network Configuration

Each node has dual network interfaces:

- **vmbr0 (Management):** 10.0.40.x/24 - VM traffic, management, web UI
- **eth0 (Ceph):** 10.0.70.x/24 - Ceph cluster communication

### Storage Layout

- **Local storage:** VM images and containers on each node
- **Ceph cluster:** Distributed storage across all nodes using NVMe drives
- **NFS shares:**
  - `nfs-proxmox-backup` (10.0.40.2:/proxmox-backup) - Backup storage
  - `nfs-proxmox-iso` (10.0.40.2:/proxmox-iso) - ISO images
  - `nfs-proxmox-template` (10.0.40.2:/proxmox-template) - Container templates

## Prerequisites

### Hardware Requirements

- 3x Mini PCs or servers with:
  - NVMe drive for OS and Ceph storage
  - 2x network interfaces (or USB-Ethernet adapter)
  - Minimum 8GB RAM (16GB+ recommended)

### Software Requirements

- **Local machine:**
  - Ansible 2.9+
  - Task (go-task) for build automation
  - direnv for environment management
- **Target nodes:**
  - Fresh Debian 12 installation
  - SSH access with root password authentication (temporary)

### Network Requirements

- NFS server at 10.0.40.2 with required exports
- Internet access for package downloads
- Static IP assignments for all nodes

## Server Preparation

### 1. Install Debian 12

1. Download [Debian 12 ISO](https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/)
2. Install with these settings:
   - Use entire NVMe disk
   - Configure `enp2s0` interface with DHCP (will be changed to static later)
   - No domain name
   - Deselect "Desktop environment" and "GNOME"
   - Select "SSH server"

### 2. Configure Network Interfaces

```bash
# Backup current config
sudo cp /etc/network/interfaces /etc/network/interfaces.backup

# Edit network configuration
sudo nano /etc/network/interfaces
```

Example configuration for pve-0:

```bash
auto lo
iface lo inet loopback

# Physical interface (manual, used by bridge)
iface enp2s0 inet manual

# Management network bridge
auto vmbr0
iface vmbr0 inet static
    address 10.0.40.10/24
    gateway 10.0.40.1
    bridge-ports enp2s0
    bridge-stp off
    bridge-fd 0

# Ceph network (USB-Ethernet or second interface)
auto eth0
iface eth0 inet static
    address 10.0.70.10/24
```

Restart networking:

```bash
sudo systemctl restart networking
# or reboot if needed
sudo reboot
```

### 3. Enable SSH Access

Enable password authentication temporarily:

```bash
# Backup SSH config
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Uncomment and set:
PasswordAuthentication yes
PermitRootLogin yes

# Restart SSH
sudo systemctl restart sshd
```

### 4. Clean Up Previous Ceph Installation (if needed)

If you're reinstalling on nodes that previously had Ceph:

```bash
# Stop Ceph services
systemctl stop ceph-osd@*

# Install LVM tools if needed
apt update && apt install -y lvm2 gdisk

# Check for Ceph volumes
lsblk

# Remove LVM volumes (adjust names as needed)
lvremove ceph-<uuid>/osd-block-<uuid>
vgremove ceph-<uuid>
pvremove /dev/nvme0n1

# Wipe disk completely
sgdisk --zap-all /dev/nvme0n1
```

## Setup and Deployment

### 1. Credentials Configuration

Create environment file for sensitive credentials:

```bash
# Copy example file
cp .envrc.example .envrc

# Edit with your credentials
nano .envrc
```

Configure your local environment in `.envrc`:

```bash
# Optional Ansible SSH overrides for Proxmox nodes
export ANSIBLE_USER="root"
export ANSIBLE_SSH_PRIVATE_KEY_FILE="$HOME/.ssh/fs_home_rsa"

# Gmail SMTP Configuration for notifications
export GMAIL_SMTP_USERNAME="your-email@gmail.com"
export GMAIL_SMTP_PASSWORD="your-gmail-app-password"  # 16-character app password
export GMAIL_SMTP_TEST="false"  # Set to 'true' to test after deployment
```

Load environment variables:

```bash
# Allow direnv to load variables
direnv allow

# Or manually export if not using direnv
source .envrc
```

### 2. Gmail App Password Setup

1. Enable 2FA on your Gmail account
2. Go to [Google Account Settings](https://myaccount.google.com/apppasswords)
3. Generate an App Password for "Mail"
4. Use the 16-character password in `GMAIL_SMTP_PASSWORD`

### 3. Install Dependencies

```bash
# Install Ansible Galaxy requirements
task init
```

### 4. Deploy the Cluster

```bash
# Dry run to preview changes
task plan

# Full deployment
task apply
```

## Available Tasks

```bash
# Setup & Initialization
task init                         # Install Ansible Galaxy requirements
task setup                        # Same as init

# Main Deployment
task plan                         # Preview full deployment changes
task check                        # Alias for plan
task apply                        # Apply full deployment
task apply-verbose                # Apply with verbose output
task apply-no-ssh                 # Apply while skipping ssh_cluster_config

# Role-scoped runs against site.yml tags
task role-plan -- beszel_agent    # Preview only the Beszel agent role
task role-apply -- beszel_agent   # Apply only the Beszel agent role
task role-plan -- gmail_smtp      # Preview Gmail SMTP changes
task role-apply -- backup         # Apply backup role changes
task role-apply -- pools          # Apply Proxmox pool changes

# Optional extra ansible-playbook flags after --
task role-apply -- beszel_agent -e "_beszel_state=absent"

# Standalone playbooks
task network-configure-secondary
task ceph-remove-storage-plan
task ceph-remove-storage-apply

# Recover existing Ceph daemons and verify storage
task ceph-recovery
```

These commands use SSH key auth by default.
This repo resolves `ansible_user` and `ansible_ssh_private_key_file` in [inventory](/Users/fs/Documents/repositories/ansible/infra-ansible-home-proxmoxhosts/inventory), defaulting to `root` and `~/.ssh/fs_home_rsa`.
For Beszel, `BESZEL_HUB` can be set as `10.0.40.50:8090`, `http://10.0.40.50:8090`, or a full `ws://`/`wss://` URL; the role converts it to the agent's expected WebSocket `/ws` endpoint.

## Post-Deployment Configuration

### Gmail SMTP Testing

Test email functionality after deployment:

```bash
# Send test email via Ansible
task role-apply -- gmail_smtp -e '{"proxmox_notification_test": true}'

# Manual test from any Proxmox node
ssh root@10.0.40.10
echo "Test message" | mail -s "Test from $(hostname)" your-email@gmail.com
```

### Proxmox Web UI Integration

Configure notifications in Proxmox web interface:

1. Go to **Datacenter → Notifications**
2. Add new **SMTP** endpoint:
   - Server: `localhost`
   - Port: `25`
   - From: `your-email@gmail.com`
3. Test the notification

### API User Setup

The deployment creates API users for automation tools:

- **packer@pve** - For Packer image building
- **terraform@pve** - For Terraform infrastructure management

Both users are in the `api-automation` group with appropriate permissions.

### Backup Configuration

The deployment automatically configures backup jobs:

- **VM Backup:** Runs Sunday 1:00 AM, backs up VMs 1020, 1021
- **Template Backup:** Runs Sunday 2:00 AM, backs up template 6006
- **Storage:** Uses NFS share `nfs-proxmox-backup`
- **Retention:** 7 daily, 4 weekly, 3 monthly backups for VMs
- **Notifications:** Email alerts on backup completion/failure

To customize backup configuration, edit `group_vars/pve01`:

```yaml
vm_backup:
  vm_ids: [1020, 1021, 1030]  # Add/remove VM IDs
  schedule: "23:00"            # Change time
  dow: "sat"                   # Change day

template_backup:
  vm_ids: [6006, 6007]         # Add/remove template IDs
  schedule: "01:00"            # Change time
  dow: "sun"                   # Change day
```

Monitor backups via Proxmox web UI: **Datacenter → Backup**

### Ceph Recovery

Run `task ceph-recovery` to recover existing daemons and verify the complete cluster.
It restores current monitor-issued credentials, corrects persisted OSD keys offline
when needed, enables existing services, and waits for all daemons, clean PGs and
Proxmox Ceph storage access. It does not recreate disks or reboot hosts.

See [recovery design, validation and rollback](docs/ceph-recovery.md).

### Maintenance ownership

Maintenance is orchestrated by the `homelab.ops` workflows in `home-kestra`.
The old Sunday Ceph restart cron, its installed executable, the maintenance
Taskfile commands and `fix-ceph.sh --maintenance` have been retired. The
`proxmox_ceph_maintenance` role now only removes that cron and executable so a
future `site.yml` run cannot reinstall them. Existing maintenance logs remain.
Use `task ceph-recovery` for a daemon/storage recovery without a host outage.

### High Availability Access

The cluster uses Keepalived with VRRP to provide a floating VIP for GUI access:

- **Floating VIP:** `10.0.40.15`
- **HA Access URL:** `https://10.0.40.15:8006`
- **Failover:** Automatic failover between nodes

This ensures you can always access the Proxmox web UI via the same IP, regardless of which node is currently master.

### Resource Pools

Resource pools can be configured to organize VMs and storage:

```bash
# Create/update pools
task api-pools

# Preview changes
task api-pools-check
```

Configure pools in `group_vars/pve01`:

```yaml
pve_pools:
  - name: "production"
    comment: "Production VMs"
    vms: [100, 101]
    storage: ["local-lvm", "ceph1"]
```

## Project Structure

```
├── ansible.cfg              # Ansible configuration
├── site.yml                 # Main playbook
├── inventory                # Host definitions (uses env vars)
├── Taskfile.yml            # Task automation
├── .envrc.example          # Environment variables template
├── group_vars/
│   ├── all                 # Global variables (NTP, timezone)
│   └── pve01               # Cluster-specific variables
├── templates/
│   └── interfaces-pve01.j2 # Network interface template
├── files/
│   └── root_pve_rsa*       # SSH key pair
├── tokens/                 # Generated API tokens (git-ignored)
├── roles/
│   ├── requirements.yml    # External role dependencies
│   ├── chrony/             # NTP time synchronization role
│   ├── keepalived/         # HA floating VIP configuration
│   ├── proxmox_api_tokens/ # API token generation for Packer/Terraform
│   ├── proxmox_backup/     # Backup job configuration role
│   ├── proxmox_gmail_smtp/ # Gmail SMTP configuration role
│   └── proxmox_pools/      # Resource pool management role
└── hack/
    ├── clean_ceph_services.sh
    └── clean_ceph_volumes.sh
```

## Technology Stack

- **Ansible** - Infrastructure automation and configuration management
- **Proxmox VE** - Virtualization platform and hypervisor
- **Ceph** - Distributed storage system
- **Debian 12** - Base operating system
- **Task** - Build automation tool (Taskfile.yml)
- **NFS** - Network file system for shared storage
- **Postfix** - SMTP relay for Gmail notifications
- **Keepalived** - High availability with VRRP floating VIP
- **Chrony** - NTP time synchronization

### Key Dependencies

- `lae.proxmox` - Proxmox VE installation and configuration
- `bridge-utils` - Network bridge management
- `keepalived` - VRRP-based high availability
- `chrony` - Modern NTP client/server

## Security

- **Credentials:** Stored in `.envrc` (git-ignored)
- **SSH:** Key-based authentication after deployment
- **Gmail:** App passwords (safer than regular passwords)
- **Network:** Isolated Ceph traffic on dedicated network
- **Ansible Vault:** Support for additional encrypted secrets

## Troubleshooting

### Common Issues

1. **Missing sudo on Debian 12:**
   ```bash
   # Install sudo if missing
   su -
   apt update && apt install sudo
   usermod -aG sudo your-username
   ```

2. **Network interface names:**
   - Check actual interface names with `ip link show`
   - Update templates if your interfaces have different names

3. **Ceph cleanup:**
   - Use provided scripts in `hack/` directory for cleanup
   - Always backup data before cleanup operations

4. **SSH connection issues:**
   - Ensure PasswordAuthentication is enabled initially
   - Check firewall settings on target nodes

### Validation

After deployment, verify:

```bash
# Check cluster status
pvecm status

# Check Ceph health
ceph -s

# Check storage
pvesm status

# Test email
echo "Test" | mail -s "Proxmox Test" your-email@gmail.com
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and test thoroughly
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
