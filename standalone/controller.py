#!/usr/bin/env python3
"""Fail-closed controller entry point; no operations in validate."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'module_utils'))
from standalone_model import validate_config, validate_inventory

ACTIONS = ('validate', 'discover', 'plan', 'apply', 'verify', 'gpu-discover', 'gpu-plan', 'gpu-prepare', 'gpu-verify', 'reboot')


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        raise ValueError('Python PyYAML is required; install in the isolated controller environment')
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node):
        result = {}
        for k, v in node.value:
            key = loader.construct_object(k)
            if key in result:
                raise ValueError('duplicate YAML key')
            result[key] = loader.construct_object(v)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(path.read_text(), Loader=UniqueLoader)


def main():
    if not (3, 12) <= sys.version_info[:2] <= (3, 14):
        raise ValueError('controller Python 3.12–3.14 is required by pinned ansible-core 2.21')
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=ACTIONS)
    for flag in ('inventory', 'config'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--host')
    for flag in ('inventory', 'config', 'host'):
        if sum(x == '--' + flag or x.startswith('--' + flag + '=') for x in sys.argv[1:]) > 1:
            raise ValueError('duplicate --' + flag)
    args = parser.parse_args()
    paths = []
    for name in ('inventory', 'config'):
        p = Path(getattr(args, name))
        if not p.is_absolute() or not p.is_file():
            raise ValueError('--' + name + ' requires an absolute existing file')
        paths.append(p.resolve())
    config = load_yaml(paths[1])
    c = validate_config(config)
    inventory = validate_inventory(load_yaml(paths[0]), args.host)
    args.host = next(iter(inventory['all']['children']['standalone_proxmox']['hosts']))
    if args.action != 'validate' and not c['deployment_enabled']:
        raise ValueError('deployment_enabled must be true for any SSH action')
    executable = shutil.which('ansible-playbook')
    if not executable:
        raise ValueError('ansible-playbook is required; activate isolated ansible-core 2.21 controller environment')
    root = Path(__file__).resolve().parent
    # Allow connection identity only, no arbitrary ANSIBLE_* plugin/config overrides.
    identity = {'ANSIBLE_REMOTE_USER', 'ANSIBLE_PRIVATE_KEY_FILE'}
    env = {k: v for k, v in os.environ.items() if not k.startswith('ANSIBLE_') or k in identity}
    env.setdefault('ANSIBLE_REMOTE_USER', 'root')
    env.update(ANSIBLE_CONFIG=str(root / 'ansible.cfg'), ANSIBLE_ROLES_PATH=str(root / 'roles'), ANSIBLE_LIBRARY=str(root / 'library'), ANSIBLE_MODULE_UTILS=str(root / 'module_utils'), ANSIBLE_VARS_ENABLED='', ANSIBLE_HOST_KEY_CHECKING='True', ANSIBLE_INVENTORY_ENABLED='yaml', ANSIBLE_FACT_CACHING='memory')
    playbook = 'reboot.yml' if args.action == 'reboot' else 'host.yml'
    with tempfile.TemporaryDirectory(prefix='standalone-pve-') as tmp:
        inv = Path(tmp) / 'inventory.yml'
        cfg = Path(tmp) / 'config.yml'
        inv.write_text(json.dumps(inventory))
        cfg.write_text(json.dumps(config))
        inv.chmod(0o600)
        cfg.chmod(0o600)
        argv = [executable, '-i', str(inv), str(root / 'playbooks' / playbook), '--limit', args.host, '-e', '@' + str(cfg), '-e', json.dumps({'standalone_action': args.action})]
        if args.action == 'validate':
            for name in ('host.yml', 'reboot.yml'):
                command = argv.copy()
                command[3] = str(root / 'playbooks' / name)
                subprocess.run(command + ['--syntax-check'], cwd=root, env=env, check=True)
            print('Offline schema, single-host inventory and playbook syntax validated; no target contacted.')
            return 0
        if args.action in ('plan', 'gpu-plan'):
            argv += ['--check', '--diff']
        return subprocess.run(argv, cwd=root, env=env).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print('standalone-host: ' + str(exc), file=sys.stderr)
        sys.exit(2)
