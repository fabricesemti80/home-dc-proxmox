"""Inspect real Ansible SSH commands without making a network connection."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConnectionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='proxmox SSH identity ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        binary = self.directory / 'bin'
        binary.mkdir()
        self.capture = self.directory / 'ssh.jsonl'
        ssh = binary / 'ssh'
        ssh.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ''' - "$@" <<'PY'
import json, os, sys
with open(os.environ['SSH_CAPTURE'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit(255)
PY
''')
        ssh.chmod(0o755)
        self.inventory = self.directory / 'inventory.yml'
        self.inventory.write_text(json.dumps({'all': {'children': {'standalone_proxmox': {
            'hosts': {'pve-fixture': {'ansible_host': '192.0.2.10'}}}}}}))
        self.config = self.directory / 'host.yml'
        self.config.write_text((ROOT / 'standalone/examples/host.yml').read_text().replace(
            'deployment_enabled: false', 'deployment_enabled: true'))
        home = self.directory / 'home'
        home.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('ANSIBLE_') and key != 'SSH_AUTH_SOCK'}
        self.env.update(HOME=str(home), PATH=str(binary) + os.pathsep + os.environ['PATH'],
                        PROXMOX_PYTHON=sys.executable, SSH_CAPTURE=str(self.capture))

    def connection_commands(self, user=None):
        if user is not None:
            self.env['ANSIBLE_REMOTE_USER'] = user
        result = subprocess.run(['bash', str(ROOT / 'scripts/standalone-host.sh'), 'plan',
                                 '--inventory', str(self.inventory), '--config', str(self.config)],
                                env=self.env, text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        records = [json.loads(line) for line in self.capture.read_text().splitlines()]
        commands = [record[-1] for record in records if '192.0.2.10' in record]
        self.assertTrue(commands, result.stdout + result.stderr)
        tokens = [shlex.split(command) for command in commands]
        return [shlex.split(parts[2]) if parts[:2] == ['/bin/sh', '-c'] else parts
                for parts in tokens]

    def test_default_root_connection_does_not_request_sudo(self):
        commands = self.connection_commands()
        self.assertTrue(all('sudo' not in command for command in commands), commands)

    def test_explicit_non_root_connection_still_requests_escalation(self):
        commands = self.connection_commands('operator')
        self.assertTrue(any('sudo' in command for command in commands), commands)


if __name__ == '__main__':
    unittest.main()
