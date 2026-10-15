#!/bin/bash
set -e

# Configuration
SSH_KEY=~/.ssh/fs_home_rsa
SSH_USER="root"
ALL_NODES=("10.0.40.10" "10.0.40.11" "10.0.40.12")
HEALTHY_NODE="10.0.40.10" # Default node to fetch keys from

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

check_ssh() {
    local node=$1
    if ! ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=5 $SSH_USER@$node "exit"; then
        log_err "Cannot connect to $node via SSH."
        return 1
    fi
    return 0
}

cleanup_backups() {
    local target_node=$1
    local target_id=""

    # Determine ID from IP (simple mapping for this lab)
    if [[ "$target_node" == "10.0.40.10" ]]; then target_id="pve-0"; fi
    if [[ "$target_node" == "10.0.40.11" ]]; then target_id="pve-1"; fi
    if [[ "$target_node" == "10.0.40.12" ]]; then target_id="pve-2"; fi

    if [[ -z "$target_id" ]]; then
        log_err "Could not determine Node ID for IP $target_node. (Expected 10.0.40.10-12)"
        exit 1
    fi

    log_info "Removing backup directories for $target_id on $target_node..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        rm -rf /var/lib/ceph/mon/ceph-$target_id.bak.*
    "
    log_info "Done."
}

remove_monitor() {
    local target_node=$1
    local target_id=""

    # Determine ID from IP (simple mapping for this lab)
    if [[ "$target_node" == "10.0.40.10" ]]; then target_id="pve-0"; fi
    if [[ "$target_node" == "10.0.40.11" ]]; then target_id="pve-1"; fi
    if [[ "$target_node" == "10.0.40.12" ]]; then target_id="pve-2"; fi

    if [[ -z "$target_id" ]]; then
        log_err "Could not determine Node ID for IP $target_node. (Expected 10.0.40.10-12)"
        exit 1
    fi

    log_warn "WARNING: This will REMOVE the Ceph Monitor '$target_id' ($target_node) from the cluster."
    log_warn "This is IRREVERSIBLE. Make sure you have a quorum before proceeding!"
    read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted."
        exit 0
    fi

    log_info "Removing monitor '$target_id' from cluster..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "
        ceph mon remove $target_id
    "

    log_info "Stopping ceph-mon service on $target_node..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        systemctl stop ceph-mon@$target_id.service || true
        systemctl disable ceph-mon@$target_id.service || true
    "

    log_info "Cleaning up monitor data directory on $target_node..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        rm -rf /var/lib/ceph/mon/ceph-$target_id
    "

    log_info "Monitor '$target_id' removed successfully."
    log_info "Run 'ceph -s' on $HEALTHY_NODE to verify cluster health."
}

get_target_id() {
    local target_node=$1
    local target_id=""
    
    # Check for management IPs (10.0.40.x) - only these have SSH access
    if [[ "$target_node" == "10.0.40.10" ]]; then target_id="pve-0"; fi
    if [[ "$target_node" == "10.0.40.11" ]]; then target_id="pve-1"; fi
    if [[ "$target_node" == "10.0.40.12" ]]; then target_id="pve-2"; fi

    echo "$target_id"
}

recover_monitor() {
    local target_node=$1
    local force=${2:-false}
    local target_id=$(get_target_id "$target_node")

    if [[ -z "$target_id" ]]; then
        log_err "Could not determine Node ID for IP $target_node. (Expected 10.0.40.10-12 - management IPs only)"
        log_err "Note: 10.0.70.x IPs are internal Ceph network with no SSH access."
        exit 1
    fi

    if [[ "$force" != "true" ]]; then
        log_warn "WARNING: This will WIPE and REBUILD the Ceph Monitor store on $target_id ($target_node)."
        read -p "Are you sure you want to proceed? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Aborted."
            exit 0
        fi
    fi

    log_info "Checking current mon status..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph mon dump 2>/dev/null | grep $target_id && echo \"Monitor exists in map\" || echo \"Monitor not in map\""

    log_info "Stopping ceph-mon@$target_id..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "systemctl stop ceph-mon@$target_id.service || true"

    # Check if mon exists in map but local data is corrupted/missing
    log_info "Checking for stale monmap entry..."
    local mon_in_map=$(ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph mon dump 2>/dev/null | grep -c $target_id" || echo "0")
    if [[ "$mon_in_map" -gt 0 ]]; then
        log_warn "Monitor $target_id exists in monmap but may have stale data. Removing stale entry first..."
        ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph mon remove $target_id"
        log_info "Removed stale monmap entry for $target_id"
    fi

    log_info "Backing up and cleaning existing store completely..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        rm -f /tmp/monmap /tmp/ceph.mon.keyring /tmp/ceph.client.admin.keyring /tmp/ceph.conf
        # Remove stale lock files and backup old store
        rm -rf /var/lib/ceph/mon/ceph-$target_id/store.db/*.lock /var/lib/ceph/mon/ceph-$target_id/store.db/LOCK
        # Backup and completely remove old store
        if [ -d /var/lib/ceph/mon/ceph-$target_id ]; then
            mv /var/lib/ceph/mon/ceph-$target_id /var/lib/ceph/mon/ceph-$target_id.bak.\$(date +%s)
        fi
        mkdir -p /var/lib/ceph/mon/ceph-$target_id
        chown ceph:ceph /var/lib/ceph/mon/ceph-$target_id
        chmod 750 /var/lib/ceph/mon/ceph-$target_id
    "

    log_info "Fetching fresh MonMap and Keyring from healthy node ($HEALTHY_NODE)..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        scp -o StrictHostKeyChecking=no $HEALTHY_NODE:/etc/ceph/ceph.client.admin.keyring /tmp/ceph.client.admin.keyring
        scp -o StrictHostKeyChecking=no $HEALTHY_NODE:/etc/ceph/ceph.conf /tmp/ceph.conf
        
        ceph --keyring /tmp/ceph.client.admin.keyring --name client.admin mon getmap -o /tmp/monmap
        ceph --keyring /tmp/ceph.client.admin.keyring --name client.admin auth get mon. -o /tmp/ceph.mon.keyring
        
        chown ceph:ceph /tmp/monmap /tmp/ceph.mon.keyring /tmp/ceph.conf
        chmod 644 /tmp/monmap /tmp/ceph.mon.keyring /tmp/ceph.conf
    "

    log_info "Re-initializing Monitor Store..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        sudo -u ceph ceph-mon --mkfs -i $target_id --monmap /tmp/monmap --keyring /tmp/ceph.mon.keyring -c /tmp/ceph.conf
        touch /var/lib/ceph/mon/ceph-$target_id/done
        chown ceph:ceph /var/lib/ceph/mon/ceph-$target_id/done
    "

    # Wait a moment for mkfs to complete fully
    sleep 2

    log_info "Starting Service..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        systemctl start ceph-mon@$target_id.service || {
            echo \"ERROR: Failed to start service. Checking logs...\"
            journalctl -u ceph-mon@$target_id.service --no-pager -n 30
        }
    "
    
    log_info "Cleaning up temp files..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        rm -f /tmp/monmap /tmp/ceph.mon.keyring /tmp/ceph.client.admin.keyring /tmp/ceph.conf 2>/dev/null || true
    "

    log_info "Waiting for service to stabilize..."
    sleep 5
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "systemctl status ceph-mon@$target_id.service --no-pager"
}

repair_inconsistent_pgs() {
    log_info "Finding inconsistent PGs..."
    local pgs=$(ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph health detail 2>/dev/null | grep -oP 'pg \K[0-9]+\.[0-9a-f]+(?=.*inconsistent)' | sort -u")
    
    if [[ -z "$pgs" ]]; then
        log_info "No inconsistent PGs found."
        return 0
    fi
    
    log_warn "Found inconsistent PGs: $pgs"
    read -p "Repair these PGs? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted."
        return 0
    fi
    
    for pg in $pgs; do
        log_info "Repairing PG $pg..."
        ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph pg repair $pg"
    done
    log_info "PG repair commands issued. Monitor with 'ceph -s'."
}

repair_osd() {
    local target_node=$1
    local target_id=$(get_target_id "$target_node")
    
    if [[ -z "$target_id" ]]; then
        log_err "Could not determine Node ID for IP $target_node."
        exit 1
    fi
    
    # Find OSD number for this host
    local osd_num=$(ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph osd tree 2>/dev/null | grep -A1 'host $target_id' | grep 'osd\.' | awk '{print \$4}' | sed 's/osd\.//'")
    
    if [[ -z "$osd_num" ]]; then
        log_err "Could not find OSD for host $target_id"
        exit 1
    fi
    
    log_info "Found osd.$osd_num on $target_id ($target_node)"
    log_warn "This will attempt to repair the BlueStore database for osd.$osd_num"
    read -p "Proceed? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted."
        return 0
    fi
    
    log_info "Stopping osd.$osd_num..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "systemctl stop ceph-osd@$osd_num"
    
    log_info "Running BlueStore repair..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "ceph-bluestore-tool repair --path /var/lib/ceph/osd/ceph-$osd_num"
    local repair_status=$?
    
    log_info "Starting osd.$osd_num..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "systemctl start ceph-osd@$osd_num"
    
    if [[ $repair_status -eq 0 ]]; then
        log_info "Repair completed successfully."
    else
        log_err "Repair failed. OSD may need to be recreated."
        log_info "To recreate: pveceph osd destroy $osd_num && pveceph osd create <device>"
    fi
}

recreate_osd() {
    local target_node=$1
    local target_id=$(get_target_id "$target_node")
    
    if [[ -z "$target_id" ]]; then
        log_err "Could not determine Node ID for IP $target_node."
        exit 1
    fi
    
    # Find OSD number for this host
    local osd_num=$(ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph osd tree 2>/dev/null | grep -A1 'host $target_id' | grep 'osd\.' | awk '{print \$4}' | sed 's/osd\.//'")
    
    if [[ -z "$osd_num" ]]; then
        log_err "Could not find OSD for host $target_id"
        exit 1
    fi
    
    log_warn "WARNING: This will DESTROY and RECREATE osd.$osd_num on $target_id"
    log_warn "All data on this OSD will be lost. Data will be recovered from other OSDs."
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Aborted."
        return 0
    fi
    
    log_info "Finding device for osd.$osd_num..."
    local osd_device=$(ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        lsblk -o NAME,TYPE | grep -E 'nvme|sd[a-z]' | grep disk | head -1 | awk '{print \"/dev/\" \$1}'
    ")
    
    if [[ -z "$osd_device" ]]; then
        log_err "Could not determine OSD device. Please specify manually."
        exit 1
    fi
    
    log_info "Using device: $osd_device"
    
    log_info "Stopping and removing osd.$osd_num..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        systemctl stop ceph-osd@$osd_num || true
        ceph osd out $osd_num
        ceph osd down $osd_num
        ceph osd rm $osd_num
        ceph auth del osd.$osd_num
        ceph osd crush rm osd.$osd_num
        rm -rf /var/lib/ceph/osd/ceph-$osd_num
    "
    
    log_info "Wiping device..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "
        # Remove LVM
        vgremove -f \$(pvs --noheadings -o vg_name $osd_device 2>/dev/null | tr -d ' ') 2>/dev/null || true
        pvremove -f $osd_device 2>/dev/null || true
        
        # Full wipe
        wipefs -af $osd_device
        sgdisk --zap-all $osd_device
        dd if=/dev/zero of=$osd_device bs=1M count=200 status=none
        partprobe $osd_device
        sleep 2
        
        # Reset systemd state
        systemctl reset-failed ceph-osd@$osd_num 2>/dev/null || true
    "
    
    log_info "Creating new OSD..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$target_node "pveceph osd create $osd_device"
    
    if [[ $? -eq 0 ]]; then
        log_info "OSD recreated successfully. Recovery will start automatically."
        log_info "Monitor with: ceph -s"
    else
        log_err "Failed to create OSD. Check 'journalctl -u ceph-osd@* -n 50' for details."
    fi
}

deep_scrub_all() {
    log_info "Initiating deep-scrub on all PGs..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "
        ceph osd deep-scrub all
    "
    log_info "Deep-scrub initiated. This runs in background. Check 'ceph -s' for progress."
}

set_scrub_window() {
    local begin=${1:-2}
    local end=${2:-6}
    log_info "Setting Ceph scrub window to ${begin}:00-${end}:00..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "
        ceph config set osd osd_scrub_begin_hour $begin
        ceph config set osd osd_scrub_end_hour $end
    "
    log_info "Scrub window set to ${begin}:00-${end}:00."
}

check_fragmentation() {
    log_info "Checking BlueStore fragmentation..."
    ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "
        ceph health detail 2>/dev/null | grep -A 10 BLUESTORE_FREE_FRAGMENTATION || echo 'No fragmentation warnings.'
    "
}

usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  --recover <IP>         Recover a corrupted monitor on a specific node IP."
    echo "  --force-recover <IP>   Force recover without confirmation."
    echo "  --remove-mon <IP>      Remove a stale/backup monitor from the cluster."
    echo "  --cleanup-backups <IP> Remove backup directories from a node."
    echo "  --status               Check cluster status."
    echo "  --repair-pgs           Find and repair inconsistent PGs."
    echo "  --repair-osd <IP>      Attempt BlueStore repair on OSD at given node."
    echo "  --recreate-osd <IP>    Destroy and recreate OSD on given node (data loss!)."
    echo "  --deep-scrub           Initiate deep-scrub on all PGs."
    echo "  --set-scrub-window [b] [e] Set scrub window (begin hour, end hour). Defaults 2-6."
    echo "  --fragmentation        Check BlueStore fragmentation health."
    echo "  --help                 Show this help message."
}

if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

case "$1" in
    --recover)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP to recover."
            exit 1
        fi
        recover_monitor $2 "false"
        ;;
    --force-recover)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP to recover."
            exit 1
        fi
        recover_monitor $2 "true"
        ;;
    --status)
        ssh -i $SSH_KEY -o StrictHostKeyChecking=no $SSH_USER@$HEALTHY_NODE "ceph -s"
        ;;
    --remove-mon)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP to remove."
            exit 1
        fi
        remove_monitor $2
        ;;
    --cleanup-backups)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP."
            exit 1
        fi
        cleanup_backups $2
        ;;
    --repair-pgs)
        repair_inconsistent_pgs
        ;;
    --repair-osd)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP."
            exit 1
        fi
        repair_osd $2
        ;;
    --recreate-osd)
        if [[ -z "$2" ]]; then
            log_err "Please specify the node IP."
            exit 1
        fi
        recreate_osd $2
        ;;
    --deep-scrub)
        deep_scrub_all
        ;;
    --set-scrub-window)
        set_scrub_window "${2:-2}" "${3:-6}"
        ;;
    --fragmentation)
        check_fragmentation
        ;;
    *)
        usage
        exit 1
        ;;
esac
