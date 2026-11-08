import importlib.util
from pathlib import Path
import re
import unittest

import jinja2

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/proxmox_hardware_notes'
spec = importlib.util.spec_from_file_location('hardware_inventory', ROLE / 'files/hardware_inventory.py')
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

LSPCI = """Slot:\t0000:02:00.0
Class:\tVGA compatible controller [0300]
Vendor:\tNVIDIA Corporation [10de]
Device:\tGK208B [GeForce GT 710] [128b]
Driver:\tnouveau
Module:\tnouveau

Slot:\t0000:5b:00.0
Class:\tVGA compatible controller [0300]
Vendor:\tNVIDIA Corporation [10de]
Device:\tGP106GL [Quadro P2000] [1c30]
Driver:\tvfio-pci

Slot:\t0000:5b:00.1
Class:\tAudio device [0403]
Vendor:\tNVIDIA Corporation [10de]
Device:\tGP106 High Definition Audio Controller [10f1]
Driver:\tvfio-pci

Slot:\t0000:00:1f.2
Class:\tSATA controller [0106]
Vendor:\tIntel Corporation [8086]
Device:\t8 Series SATA Controller [8c02]
Driver:\tahci
"""

MAPPING = """# comment
gpu-p2000
\tmap id=10de:1c30,iommugroup=2,node=pve-00,path=0000:5b:00,subsystem-id=10de:11b3
"""

VM_GPU = """name: k8s-wrkr-01-gpu
hostpci0: mapping=gpu-p2000,pcie=1
scsi2: /dev/disk/by-id/ata-CT500MX500SSD1_AAA,ssd=1,backup=0
[PENDING]
scsi3: /dev/disk/by-id/ata-PENDING_ONLY
[snap]
hostpci1: 0000:02:00.0
"""

VM_PLAIN = """name: k8s-wrkr-02
hostpci0: 0000:02:00.0,pcie=1
scsi1: local-hdd:vm-4096-disk-1,size=100G
"""

ZPOOL = """  pool: rpool
 state: ONLINE
config:

\tNAME                                              STATE     READ WRITE CKSUM
\trpool                                             ONLINE       0     0     0
\t  /dev/disk/by-id/nvme-eui.0025-part3             ONLINE       0     0     0

  pool: slow
 state: ONLINE
config:

\tNAME                                              STATE     READ WRITE CKSUM
\tslow                                              ONLINE       0     0     0
\t  /dev/disk/by-id/ata-HGST_X-part1                ONLINE       0     0     0

errors: No known data errors
"""

STORAGE = """dir: local
\tpath /var/lib/vz
\tcontent iso

zfspool: local-nvme
\tpool rpool/data
\tcontent images,rootdir

zfspool: local-hdd
\tpool slow
\tcontent images,rootdir
"""

LINKS = {
    '/dev/disk/by-id/ata-CT500MX500SSD1_AAA': '/dev/sda',
    '/dev/disk/by-id/ata-PENDING_ONLY': '/dev/sdd',
    '/dev/disk/by-id/nvme-eui.0025-part3': '/dev/nvme0n1p3',
    '/dev/disk/by-id/ata-HGST_X-part1': '/dev/sdb1',
    '/dev/nvme0n1p2': '/dev/nvme0n1p2',
}


def resolve(path):
    return LINKS.get(path, path)


class InventoryTests(unittest.TestCase):
    def test_only_gpus_are_selected_and_named(self):
        gpus = inv.parse_lspci(LSPCI)
        self.assertEqual(
            [(g['address'], g['name'], g['driver']) for g in gpus],
            [('0000:02:00.0', 'NVIDIA GeForce GT 710', 'nouveau'), ('0000:5b:00.0', 'NVIDIA Quadro P2000', 'vfio-pci')],
        )

    def test_gpu_owner_resolves_pci_mapping_and_plain_address(self):
        vms = [
            {'vmid': '4095', 'name': 'k8s-wrkr-01-gpu', 'lines': inv.current_lines(VM_GPU)},
            {'vmid': '4096', 'name': 'k8s-wrkr-02', 'lines': inv.current_lines(VM_PLAIN)},
        ]
        mappings = inv.parse_pci_mappings(MAPPING)
        gt710, p2000 = inv.parse_lspci(LSPCI)
        self.assertEqual(inv.gpu_vms(p2000, vms, mappings), [{'vmid': '4095', 'vm': 'k8s-wrkr-01-gpu'}])
        # the GT 710 reference lives only in a snapshot of VM 4095; VM 4096 owns it by address
        self.assertEqual(inv.gpu_vms(gt710, vms, mappings), [{'vmid': '4096', 'vm': 'k8s-wrkr-02'}])

    def test_pending_and_snapshot_sections_are_ignored(self):
        vms = [{'vmid': '4095', 'name': 'x', 'lines': inv.current_lines(VM_GPU)}]
        usage = inv.build_usage(vms, '', '', '', '', resolve)
        self.assertEqual(list(usage), ['sda'])
        self.assertEqual(usage['sda']['vms'], [{'vmid': '4095', 'vm': 'x', 'iface': 'scsi2'}])

    def test_zfs_membership_and_storage_ids(self):
        usage = inv.build_usage([], ZPOOL, STORAGE, '', '', resolve)
        self.assertEqual(usage['nvme0n1']['zfs'], {'pool': 'rpool', 'storages': ['local-nvme']})
        self.assertEqual(usage['sdb']['zfs'], {'pool': 'slow', 'storages': ['local-hdd']})

    def test_mounts_and_swap_map_partitions_to_disks(self):
        usage = inv.build_usage(
            [], '', '', '/dev/nvme0n1p2 /boot/efi vfat rw 0 0\ntmpfs /run tmpfs rw 0 0\n',
            'Filename Type Size Used Priority\n/dev/sdb2 partition 1 0 -2\n', resolve,
        )
        self.assertEqual(usage['nvme0n1']['mounts'], ['/boot/efi'])
        self.assertTrue(usage['sdb']['swap'])

    def test_disk_name_extraction(self):
        names = {'sda3': 'sda', 'sdaa1': 'sdaa', 'nvme0n1p3': 'nvme0n1', 'nvme0n1': 'nvme0n1', 'zd32': None, 'dm-0': None}
        for raw, disk in names.items():
            self.assertEqual(inv.disk_of(raw), disk, raw)


def render(devices, hw):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROLE / 'templates'), trim_blocks=True)
    env.tests['match'] = lambda value, pattern: re.match(pattern, value) is not None
    return env.get_template('summary.j2').render(ansible_facts={'hostname': 'pve-00', 'devices': devices}, hardware_notes_hw=hw).strip()


def device(model, sectors, rotational='0'):
    return {'model': model, 'sectors': str(sectors), 'sectorsize': '512', 'rotational': rotational}


class SummaryTests(unittest.TestCase):
    def setUp(self):
        vms = [{'vmid': '4096', 'name': 'k8s-wrkr-02', 'lines': ['scsi2: /dev/disk/by-id/ata-CT500MX500SSD1_AAA,ssd=1']}]
        self.hw = {
            'gpus': [
                {'address': '0000:5b:00.0', 'name': 'NVIDIA Quadro P2000', 'driver': 'vfio-pci', 'vms': [{'vmid': '4095', 'vm': 'k8s-wrkr-01-gpu'}]},
                {'address': '0000:02:00.0', 'name': 'NVIDIA GeForce GT 710', 'driver': 'nouveau', 'vms': []},
            ],
            'usage': inv.build_usage(vms, ZPOOL, STORAGE, '', '', resolve),
        }
        self.devices = {
            'nvme0n1': device('SAMSUNG MZVKW1T0HMLH-000L7', 2000409264),
            'sdb': device('HGST HDS724040ALE640', 7814037168, '1'),
            'sda': device('CT500MX500SSD1', 976773168),
            'sdc': device('CT500MX500SSD1', 976773168),
            'sde': device('SD/MMC CRW', 0),
            'zd0': device('', 8192),
            'sr0': device('DVD+/-RW', 2097151),
        }

    def test_summary_lists_gpus_and_physical_disks_with_roles(self):
        text = render(self.devices, self.hw)
        self.assertIn('pve-00 hardware at a glance', text)
        self.assertRegex(text, r'NVIDIA Quadro P2000\s+-> passed through \(vfio-pci\) to VM 4095 k8s-wrkr-01-gpu')
        self.assertRegex(text, r'NVIDIA GeForce GT 710\s+-> used by the host \(nouveau\)')
        self.assertRegex(text, r'SAMSUNG MZVKW1T0HMLH-000L7\s+1\.0 TB NVMe\s+-> host ZFS pool rpool \(storage local-nvme\)')
        self.assertRegex(text, r'HGST HDS724040ALE640\s+4\.0 TB HDD\s+-> host ZFS pool slow \(storage local-hdd\)')
        self.assertRegex(text, r'CT500MX500SSD1\s+500 GB SSD\s+-> passed through to VM 4096 k8s-wrkr-02 \(scsi2\)')
        self.assertRegex(text, r'CT500MX500SSD1\s+500 GB SSD\s+-> unused')

    def test_virtual_empty_and_optical_devices_are_not_listed(self):
        text = render(self.devices, self.hw)
        for ignored in ('SD/MMC', 'DVD', 'zd0'):
            self.assertNotIn(ignored, text)

    def test_summary_has_no_serials_and_is_ascii(self):
        text = render(self.devices, self.hw)
        self.assertNotIn('AAA', text)
        text.encode('ascii')

    def test_new_unclaimed_disk_shows_up_without_edits(self):
        self.devices['sdf'] = device('NEW SSD 1TB', 1953525168)
        self.assertRegex(render(self.devices, self.hw), r'NEW SSD 1TB\s+1\.0 TB SSD\s+-> unused')

    def test_disk_without_model_is_labelled_not_none(self):
        self.devices['sdf'] = {'model': None, 'sectors': '1953525168', 'sectorsize': '512', 'rotational': '0'}
        text = render(self.devices, self.hw)
        self.assertIn('unknown disk', text)
        self.assertNotIn('None', text)


if __name__ == '__main__':
    unittest.main()
