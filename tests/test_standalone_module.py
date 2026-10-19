"""Offline target-module fixtures: no connection, subprocess or actual /etc writes."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone/module_utils'))
import standalone_model
sys.modules['ansible.module_utils.standalone_model'] = standalone_model
spec = importlib.util.spec_from_file_location('standalone_host', ROOT / 'standalone/library/standalone_host.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeModule:
    def __init__(self):
        self.commands = []

    def run_command(self, argv, **kwargs):
        self.commands.append(argv)
        if argv[0] == 'bootctl':
            return 1, '', 'not EFI'
        if argv[:2] == ['proxmox-boot-tool', 'status']:
            return 0, 'no configured ESPs', ''
        raise AssertionError('unexpected command: ' + str(argv))


class ModuleFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.h = module.Host.__new__(module.Host)
        self.h.c = yaml.safe_load((ROOT / 'standalone/examples/host.yml').read_text())['proxmox_host']
        self.h.m = FakeModule()
        self.h.preview = True
        self.h.verify = False
        self.h.changed = False
        self.h.report = {}
        self.h.diffs = []
        self.h.state = {'storage': [], 'backup': []}

    def tearDown(self):
        self.tmp.cleanup()

    def target(self, path):
        p = Path(path)
        return self.root / str(p).lstrip('/') if p.is_absolute() else p

    def put(self, path, content):
        p = self.target(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def test_absent_managed_file_check_mode_no_write(self):
        path = str(self.root / 'absent' / 'test.conf')
        self.assertTrue(self.h.file(path, 'desired\n'))
        self.assertFalse(Path(path).exists())
        self.assertFalse(Path(path).parent.exists())
        self.assertEqual(self.h.diffs[0]['before'], '')
        self.h.verify = True
        with self.assertRaises(ValueError):
            self.h.file(path, 'desired\n')

    def test_new_nfs_and_job_preview_never_mutates(self):
        self.h.object('storage', '/storage', dict(id='nas', type='nfs', server='nas.test', export='/backup', content='backup', disable=0), [])
        self.h.object('backup', '/cluster/backup', dict(id='job', storage='nas', vmid='100', enabled=1), [])
        self.assertTrue(self.h.changed)
        self.assertEqual(self.h.m.commands, [])
        self.assertEqual(self.h.state, {'storage': ['nas'], 'backup': ['job']})

    def test_nonmanaged_conflicts_fail_but_exact_objects_stay_unmanaged(self):
        desired = dict(id='nas', type='nfs', server='nas.test', export='/backup', content='backup', disable=0)
        existing = [dict(storage='nas', type='nfs', server='other', export='/backup', content='backup')]
        with self.assertRaises(ValueError):
            self.h.object('storage', '/storage', desired.copy(), existing)
        existing[0]['server'] = 'nas.test'
        self.h.object('storage', '/storage', desired.copy(), existing)
        self.assertEqual(self.h.state['storage'], [])
        self.assertFalse(self.h.changed)
        self.h.state['storage'].append('nas')
        existing[0]['server'] = 'other'
        self.h.object('storage', '/storage', desired.copy(), existing)
        self.assertTrue(self.h.changed)
        self.assertEqual(self.h.m.commands, [])

    def setup_gpu(self, groups=False):
        self.h.action = 'gpu-plan'
        self.h.c['gpu'].update(enabled=True, bootloader='grub', pci_addresses=['0000:01:00.0', '0000:01:00.1'], pci_ids=['10de:1234', '10de:5678'])
        self.put('/proc/cpuinfo', 'vendor_id\t: GenuineIntel\n')
        self.put('/proc/cmdline', 'root=UUID=abc quiet\n')
        self.put('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\nGRUB_CMDLINE_LINUX=""\n')
        self.put('/usr/share/initramfs-tools/hook-functions', '# fixture\n')
        self.devices = {
            '0000:01:00.0': {'id': '10de:1234', 'class': '0x030000', 'driver': 'nouveau', 'group': '1' if groups else None, 'peers': ['0000:01:00.0', '0000:01:00.1'] if groups else [], 'console': False},
            '0000:01:00.1': {'id': '10de:5678', 'class': '0x040300', 'driver': 'snd_hda_intel', 'group': '1' if groups else None, 'peers': ['0000:01:00.0', '0000:01:00.1'] if groups else [], 'console': False},
        }
        self.h.pci = lambda: self.devices

    def test_first_run_gpu_check_missing_files_and_groups_only_plans_boot(self):
        self.setup_gpu()
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            self.h.gpu()
        self.assertIn('IOMMU boot arguments only', self.h.report['gpu']['stage'])
        self.assertEqual(len(self.h.diffs), 1)
        self.assertIn('quiet', self.h.diffs[0]['after']) if 'quiet' in self.h.diffs[0]['after'] else self.assertIn('$GRUB_CMDLINE_LINUX_DEFAULT', self.h.diffs[0]['after'])
        self.assertFalse(self.target('/etc/default/grub.d/90-standalone-iommu.cfg').exists())
        self.assertEqual(len(self.h.m.commands), 2)

    def test_binding_preview_includes_early_initramfs_modules_no_refresh(self):
        self.setup_gpu(groups=True)
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            self.h.gpu()
        self.assertEqual(self.h.report['gpu']['stage'], 'binding prepared')
        after = '\n'.join(d.get('after', '') for d in self.h.diffs)
        self.assertIn('force_load vfio_pci', after)
        self.assertNotIn('softdep amdgpu', after)
        self.assertIn('softdep nouveau', after)
        self.assertEqual(len(self.h.m.commands), 2)
        self.assertFalse(self.target('/etc/modprobe.d/standalone-vfio.conf').exists())




    def test_grub_does_not_add_duplicate_existing_kernel_arguments(self):
        self.setup_gpu()
        self.put('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on"\nGRUB_CMDLINE_LINUX="iommu=pt"\n')
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            self.h.gpu()
        self.assertEqual(self.h.diffs[0]['after'], '# Managed by standalone-proxmox\n')

    def test_grub_overridden_duplicate_assignment_fails_before_file_changes(self):
        self.setup_gpu()
        self.put('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT="intel_iommu=on iommu=pt"\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_CMDLINE_LINUX=""\n')
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'duplicate GRUB cmdline assignments'):
                self.h.gpu()
        self.assertFalse(self.h.changed)
        self.assertEqual(self.h.diffs, [])
        self.assertFalse(self.target('/etc/default/grub.d/90-standalone-iommu.cfg').exists())

    def test_fresh_iso_no_subscription_disables_unused_ceph_enterprise(self):
        self.h.c['repository'] = 'no-subscription'
        source = '# ISO source\nTypes: deb\nURIs: https://enterprise.proxmox.com/debian/ceph-squid\nSuites: trixie\nComponents: enterprise\nSigned-By: /usr/share/keyrings/proxmox-archive-keyring.gpg\n'
        self.put('/etc/apt/sources.list.d/ceph.sources', source)
        self.put('/etc/apt/sources.list.d/pve-enterprise.sources', 'Types: deb\nURIs: https://enterprise.proxmox.com/debian/pve\nSuites: trixie\nComponents: pve-enterprise\nSigned-By: /usr/share/keyrings/proxmox-archive-keyring.gpg\n')
        with patch.object(module, 'Path', self.target):
            self.h.repositories()
        ceph = next(d for d in self.h.diffs if d['after_header'].endswith('ceph.sources'))
        self.assertEqual(ceph['after'], source + 'Enabled: no\n')
        self.assertEqual(self.target('/etc/apt/sources.list.d/ceph.sources').read_text(), source)
        self.assertEqual(self.h.m.commands, [])
        self.put('/etc/apt/sources.list.d/ceph.sources', source + '\nTypes: deb\nURIs: https://other.invalid/repo\n')
        with patch.object(module, 'Path', self.target):
            with self.assertRaises(ValueError):
                self.h.repositories()

    def test_first_run_storage_and_backup_plan_has_no_api_mutations(self):
        self.h.storage = [{'storage': 'local', 'content': 'backup'}]
        self.h.c['storage']['local_expected_ids'] = ['local']
        self.h.c['storage']['nfs'] = [dict(id='nas', server='nas.test', export='/backup', content=['backup'], enabled=True)]
        self.h.c['backups'] = [dict(id='job', storage='nas', schedule='daily', vmids=[100], enabled=True, prune_backups={'keep-last': 1})]
        self.h.api = lambda path: [] if path == '/cluster/backup' else [{'type': 'qemu', 'vmid': 100}]
        self.h.state_path = self.target('/var/lib/standalone-proxmox/ownership.json')
        self.h.m.run_command = lambda argv, **kwargs: (0, '', '') if argv[0] == 'systemd-analyze' else (_ for _ in ()).throw(AssertionError(str(argv)))
        with patch.object(module, 'Path', self.target):
            self.h.storage_backups()
        self.assertEqual(self.h.state, {'storage': ['nas'], 'backup': ['job']})
        self.assertFalse(self.h.state_path.exists())
        self.assertFalse(self.target('/mnt/pve/nas').exists())

    def test_unchanged_gpu_files_do_not_run_refresh_handlers(self):
        self.setup_gpu(groups=True)
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            self.h.gpu()
        for difference in self.h.diffs:
            self.put(difference['after_header'], difference['after'])
        self.h.changed = False
        self.h.diffs = []
        self.h.preview = False
        self.h.action = 'gpu-prepare'
        self.h.m.commands = []
        with patch.object(module, 'Path', self.target), patch.object(module.glob, 'glob', return_value=[]):
            self.h.gpu()
        self.assertFalse(self.h.changed)
        self.assertEqual(self.h.diffs, [])
        self.assertEqual(len(self.h.m.commands), 2)  # bootctl and boot-tool status only

    def test_invalid_later_backup_prevents_earlier_nfs_write(self):
        self.h.action = 'apply'
        self.h.preview = False
        self.h.preflight = lambda: None
        self.h.timezone = lambda: None
        self.h.repositories = lambda: None
        self.h.packages = lambda: None
        self.h.storage = [{'storage': 'local', 'content': 'backup'}]
        self.h.c['storage']['local_expected_ids'] = ['local']
        self.h.c['storage']['nfs'] = [dict(id='nas', server='nas.test', export='/backup', content=['backup'], enabled=True)]
        self.h.c['backups'] = [dict(id='later', storage='nas', schedule='daily', vmids=[999], enabled=True, prune_backups={'keep-last': 1})]
        self.h.api = lambda path: []  # No VM 999 exists.
        with patch.object(module, 'Path', self.target):
            with self.assertRaises(ValueError):
                self.h.run()
        self.assertEqual(self.h.m.commands, [])
        self.assertFalse(self.target('/var/lib/standalone-proxmox/ownership.json').exists())

    def test_post_reboot_stage_one_and_unsafe_active_arguments(self):
        self.setup_gpu(groups=True)
        self.h.action = 'gpu-post-reboot'
        self.put('/proc/cmdline', 'root=UUID=abc intel_iommu=on iommu=pt\n')
        with patch.object(module, 'Path', self.target):
            self.h.gpu()
        self.assertIn('IOMMU active', self.h.report['gpu']['stage'])
        self.put('/proc/cmdline', 'intel_iommu=on iommu=pt pcie_acs_override=downstream\n')
        with patch.object(module, 'Path', self.target):
            with self.assertRaises(ValueError):
                self.h.gpu()
        self.h.action = 'gpu-verify'
        self.put('/proc/cmdline', 'intel_iommu=on iommu=pt\n')
        with patch.object(module, 'Path', self.target):
            with self.assertRaises(ValueError):
                self.h.gpu()
        self.assertEqual(self.h.m.commands, [])


if __name__ == '__main__':
    unittest.main()
