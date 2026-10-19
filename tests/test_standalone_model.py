import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'standalone/module_utils'))
from standalone_model import validate_config, validate_inventory, iommu_tokens, bootloader_choice, gpu_selection, equivalent
import yaml


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / 'standalone/examples/host.yml').read_text())
        self.inventory = yaml.safe_load((ROOT / 'standalone/examples/inventory.yml').read_text())

    def test_inert_examples(self):
        validate_config(self.config)
        validate_inventory(self.inventory, 'pve-app')

    def test_schema_rejects_unsafe_and_secret_inputs(self):
        mutations = [
            lambda c: c.update(password='secret'),
            lambda c: c.update(deployment_enabled='true'),
            lambda c: c.update(mode='cluster'),
            lambda c: c.update(expected_pve_major=True),
            lambda c: c.update(timezone='../../etc/passwd'),
            lambda c: c.update(repository='testing'),
            lambda c: c['gpu'].update(pci_addresses=['0000:01:00.0;bad']),
            lambda c: c['gpu'].update(enabled=True),
            lambda c: c['storage'].update(nfs=[dict(id='nas', server='nas.test', export='/backup', content=['backup'], enabled=True, options='password=secret')]),
            lambda c: c.update(backups=[dict(id='job', storage='local', schedule='daily', vmids=[], enabled=True, prune_backups={'keep-last': 1})]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                c = copy.deepcopy(self.config)
                mutate(c['proxmox_host'])
                with self.assertRaises((ValueError, TypeError)):
                    validate_config(c)

    def test_nfs_and_explicit_backup_schema(self):
        c = self.config['proxmox_host']
        c['storage']['nfs'] = [dict(id='nas', server='nas.test', export='/backup', content=['backup'], enabled=True)]
        c['backups'] = [dict(id='job', storage='nas', schedule='sun 01:00', vmids=[100], enabled=True, prune_backups={'keep-last': 2})]
        validate_config(self.config)
        c['storage']['nfs'][0]['enabled'] = False
        with self.assertRaises(ValueError):
            validate_config(self.config)

    def test_inventory_rejects_patterns_multi_host_and_vars(self):
        for alias in ('all', '*', 'pve-*', 'pve-app:other', 'pve-app,other'):
            with self.assertRaises(ValueError):
                validate_inventory(self.inventory, alias)
        self.inventory['all']['children']['standalone_proxmox']['hosts']['other'] = {'ansible_host': '192.0.2.11'}
        with self.assertRaises(ValueError):
            validate_inventory(self.inventory, 'pve-app')
        del self.inventory['all']['children']['standalone_proxmox']['hosts']['other']
        self.inventory['all']['children']['standalone_proxmox']['hosts']['pve-app']['ansible_connection'] = 'local'
        with self.assertRaises(ValueError):
            validate_inventory(self.inventory, 'pve-app')

    def test_iommu_arguments_preserved_and_deduplicated(self):
        got = iommu_tokens('root=UUID=abc quiet intel_iommu=on iommu=pt quiet', 'GenuineIntel')
        self.assertEqual(got, 'root=UUID=abc quiet intel_iommu=on iommu=pt')
        self.assertEqual(iommu_tokens(got, 'GenuineIntel'), got)
        self.assertEqual(iommu_tokens('', 'AuthenticAMD'), 'amd_iommu=on iommu=pt')
        for value in ('intel_iommu=off', 'amd_iommu=on', 'iommu=soft', 'pcie_acs_override=downstream', 'vfio_iommu_type1.allow_unsafe_interrupts=1'):
            with self.assertRaises(ValueError):
                iommu_tokens(value, 'GenuineIntel')

    def test_explicit_observed_bootloader(self):
        self.assertEqual(bootloader_choice('grub', False, None, ''), 'grub')
        self.assertEqual(bootloader_choice('systemd-boot', True, 'systemd-boot', 'ABCD configured with: uefi'), 'systemd-boot')
        for args in [(None, False, None, ''), ('grub', True, None, ''), ('grub', True, 'systemd-boot', ''), ('systemd-boot', False, None, ''), ('systemd-boot', True, 'systemd-boot', ''), ('systemd-boot', True, 'systemd-boot', 'System currently booted with uefi\nABCD is configured with: grub (versions: 6.14)'), ('systemd-boot', True, 'systemd-boot', 'ABCD is configured with: uefi\nEFGH is configured with: grub')]:
            with self.assertRaises(ValueError):
                bootloader_choice(*args)

    def test_gpu_group_peers_duplicate_ids_and_console(self):
        devices = {'0000:01:00.0': dict(id='10de:1234', **{'class': '0x030000'}, group='1', peers=['0000:01:00.0', '0000:01:00.1'], console=False), '0000:01:00.1': dict(id='10de:5678', **{'class': '0x040300'}, group='1', peers=['0000:01:00.0', '0000:01:00.1'], console=False)}
        g = dict(pci_addresses=list(devices), pci_ids=['10de:1234', '10de:5678'], allow_host_console_loss=False)
        self.assertEqual(gpu_selection(devices, g), sorted(devices))
        devices['0000:01:00.0']['console'] = True
        with self.assertRaises(ValueError):
            gpu_selection(devices, g)
        g['allow_host_console_loss'] = True
        devices['0000:02:00.0'] = dict(id='10de:1234', group='2', peers=[], console=False)
        with self.assertRaises(ValueError):
            gpu_selection(devices, g)
        del devices['0000:02:00.0']
        g['pci_addresses'] = ['0000:01:00.0']
        g['pci_ids'] = ['10de:1234']
        with self.assertRaises(ValueError):
            gpu_selection(devices, g)
        devices['0000:01:00.0']['group'] = None
        with self.assertRaises(ValueError):
            gpu_selection(devices, g)
        g['pci_addresses'] = ['0000:01:00.0', '0000:01:00.1']
        g['pci_ids'] = ['10de:1234', '10de:5678']
        gpu_selection(devices, g, require_groups=False)


    def test_full_slot_functions_required_even_separate_groups(self):
        devices = {
            '0000:01:00.0': dict(id='10de:1234', **{'class': '0x030000'}, group='1', peers=['0000:01:00.0'], console=False),
            '0000:01:00.1': dict(id='10de:5678', **{'class': '0x040300'}, group='2', peers=['0000:01:00.1'], console=False),
            '0000:01:00.2': dict(id='10de:9abc', **{'class': '0x0c0330'}, group='3', peers=['0000:01:00.2'], console=False),
            '0000:01:00.3': dict(id='10de:def0', **{'class': '0x0c8000'}, group='4', peers=['0000:01:00.3'], console=False),
        }
        gpu = dict(pci_addresses=['0000:01:00.0'], pci_ids=['10de:1234'], allow_host_console_loss=False)
        with self.assertRaises(ValueError):
            gpu_selection(devices, gpu)
        gpu.update(pci_addresses=list(devices), pci_ids=[d['id'] for d in devices.values()])
        self.assertEqual(gpu_selection(devices, gpu), sorted(devices))
        devices['0000:01:00.3']['class'] = '0x020000'
        with self.assertRaises(ValueError):
            gpu_selection(devices, gpu)

    def test_api_comparison(self):
        self.assertTrue(equivalent({'content': 'iso,backup', 'disable': 0}, {'content': 'backup,iso', 'disable': 0}))
        self.assertFalse(equivalent({'server': 'other'}, {'server': 'nas.test'}))
        self.assertTrue(equivalent({'vmid': '101,100', 'prune-backups': 'keep-last=2,keep-daily=3'}, {'vmid': '100,101', 'prune-backups': 'keep-daily=3,keep-last=2'}))


if __name__ == '__main__':
    unittest.main()
