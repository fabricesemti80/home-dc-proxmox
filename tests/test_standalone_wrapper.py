import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='standalone wrapper ')
        self.directory = Path(self.tmp.name)
        self.bin = self.directory / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'ansible-playbook'
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
with open(os.environ['CAPTURE'], 'a') as f:
 f.write(json.dumps({'argv':sys.argv[1:], 'env':{k:v for k,v in os.environ.items() if k.startswith('ANSIBLE_') or k=='SSH_AUTH_SOCK'}, 'inventory':pathlib.Path(sys.argv[2]).read_text(), 'cwd':os.getcwd()})+'\\n')
sys.exit(int(os.environ.get('FAKE_EXIT', '0')))
''')
        fake.chmod(0o755)
        self.inventory = self.directory / 'inventory file.yml'
        self.inventory.write_text((ROOT / 'standalone/examples/inventory.yml').read_text())
        self.config = self.directory / 'config file.yml'
        self.config.write_text((ROOT / 'standalone/examples/host.yml').read_text().replace('deployment_enabled: false', 'deployment_enabled: true'))
        self.capture = self.directory / 'capture.jsonl'
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], CAPTURE=str(self.capture), ANSIBLE_CONFIG='/bad/ansible.cfg', ANSIBLE_HOST_KEY_CHECKING='False', ANSIBLE_VARS_PLUGINS='/bad/plugin', ANSIBLE_REMOTE_USER='root', ANSIBLE_PRIVATE_KEY_FILE='/a key file', SSH_AUTH_SOCK='/agent socket')

    def tearDown(self):
        self.tmp.cleanup()

    def run_action(self, action, extra=()):
        return subprocess.run(['bash', str(ROOT / 'scripts/standalone-host.sh'), action, '--inventory', str(self.inventory), '--config', str(self.config), '--host', 'pve-app'] + list(extra), cwd='/tmp', env=self.env, text=True, capture_output=True)

    def records(self):
        return [json.loads(s) for s in self.capture.read_text().splitlines()] if self.capture.exists() else []

    def test_every_action_argv_isolated_and_reboot_separate(self):
        for action in ('validate', 'discover', 'plan', 'apply', 'verify', 'gpu-discover', 'gpu-plan', 'gpu-prepare', 'gpu-verify', 'reboot'):
            with self.subTest(action=action):
                self.capture.unlink(missing_ok=True)
                result = self.run_action(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                records = self.records()
                self.assertEqual(len(records), 2 if action == 'validate' else 1)
                record = records[0]
                args = record['argv']
                self.assertIn('--limit', args)
                self.assertEqual(args[args.index('--limit') + 1], 'pve-app')
                self.assertEqual('--check' in args, action in ('plan', 'gpu-plan'))
                self.assertEqual('--diff' in args, action in ('plan', 'gpu-plan'))
                if action != 'validate':
                    self.assertEqual(args[2].endswith('/reboot.yml'), action == 'reboot')
                env = record['env']
                self.assertEqual(env['ANSIBLE_CONFIG'], str(ROOT / 'standalone/ansible.cfg'))
                self.assertEqual(env['ANSIBLE_HOST_KEY_CHECKING'], 'True')
                self.assertEqual(env['ANSIBLE_REMOTE_USER'], 'root')
                self.assertEqual(env['ANSIBLE_PRIVATE_KEY_FILE'], '/a key file')
                self.assertEqual(env['SSH_AUTH_SOCK'], '/agent socket')
                self.assertNotIn('ANSIBLE_VARS_PLUGINS', env)
                self.assertEqual(env['ANSIBLE_VARS_ENABLED'], '')
                self.assertEqual(json.loads(record['inventory'])['all']['children']['standalone_proxmox']['hosts']['pve-app']['ansible_host'], '192.0.2.10')

    def test_rejects_before_ansible(self):
        for action, extra in [('apply', ['-e', 'unsafe=true']), ('other', []), ('apply', ['--host', 'all']), ('apply', ['--inventory', 'relative.yml'])]:
            self.assertNotEqual(self.run_action(action, extra).returncode, 0)
            self.assertEqual(self.records(), [])
        self.config.write_text(self.config.read_text().replace('deployment_enabled: true', 'deployment_enabled: false'))
        self.assertNotEqual(self.run_action('discover').returncode, 0)
        self.assertEqual(self.run_action('validate').returncode, 0)

    def test_duplicate_yaml_rejected_and_exit_preserved(self):
        self.env['FAKE_EXIT'] = '37'
        self.assertEqual(self.run_action('apply').returncode, 37)
        self.capture.unlink()
        self.config.write_text('proxmox_host: {}\nproxmox_host: {}\n')
        self.assertNotEqual(self.run_action('apply').returncode, 0)
        self.assertEqual(self.records(), [])

    def test_missing_flag_and_host_pattern(self):
        cmd = ['bash', str(ROOT / 'scripts/standalone-host.sh'), 'validate']
        self.assertNotEqual(subprocess.run(cmd, env=self.env, capture_output=True).returncode, 0)
        self.inventory.write_text(self.inventory.read_text().replace('pve-app:', 'other:'))
        self.assertNotEqual(self.run_action('apply').returncode, 0)
        self.assertEqual(self.records(), [])

    def test_infers_only_one_literal_host_before_planning(self):
        self.inventory.write_text(self.inventory.read_text().replace('pve-app:', 'pve-00:'))
        cmd = ['bash', str(ROOT / 'scripts/standalone-host.sh'), 'plan',
               '--inventory', str(self.inventory), '--config', str(self.config)]
        result = subprocess.run(cmd, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.records()[0]['argv']
        self.assertEqual(args[args.index('--limit') + 1], 'pve-00')
        self.assertIn('--check', args)
        self.assertIn('--diff', args)
        self.capture.unlink()
        import yaml
        data = yaml.safe_load(self.inventory.read_text())
        data['all']['children']['standalone_proxmox']['hosts']['other'] = {'ansible_host': '192.0.2.11'}
        self.inventory.write_text(yaml.safe_dump(data))
        self.assertNotEqual(subprocess.run(cmd, env=self.env, capture_output=True).returncode, 0)
        self.assertEqual(self.records(), [])

    def test_missing_selected_controller_does_not_fall_back(self):
        self.env['PROXMOX_PYTHON'] = str(self.directory / 'missing-python')
        self.assertNotEqual(self.run_action('apply').returncode, 0)
        self.assertEqual(self.records(), [])



if __name__ == '__main__':
    unittest.main()
