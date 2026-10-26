#!/usr/bin/python
"""Conservative standalone PVE operations. No shell and no runtime PCI unbind."""
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.standalone_model import (validate_config, require, equivalent,
    iommu_tokens, bootloader_choice, gpu_selection)
import glob
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile


class Host:
    def __init__(self, module):
        self.m = module
        self.c = validate_config({'proxmox_host': module.params['config']})
        require(self.c['deployment_enabled'], 'deployment is disabled')
        self.action = module.params['action']
        self.preview = module.check_mode
        self.verify = self.action in ('verify', 'gpu-verify')
        self.changed = False
        self.diffs = []
        self.report = {}
        self.state_path = Path('/var/lib/standalone-proxmox/ownership.json')
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'storage': [], 'backup': []}

    def command(self, argv, acceptable=(0,)):
        rc, out, err = self.m.run_command(argv, environ_update={'DEBIAN_FRONTEND': 'noninteractive'})
        require(rc in acceptable, 'command failed: %s: %s' % (' '.join(argv), err.strip()))
        return out.strip()

    def api(self, path):
        return json.loads(self.command(['pvesh', 'get', path, '--output-format', 'json']))

    def mutate(self, argv):
        self.changed = True
        if not self.preview:
            self.command(argv)

    def file(self, path, content, mode=0o644):
        p = Path(path)
        old = p.read_text() if p.exists() else ''
        if old == content:
            return False
        if self.verify:
            raise ValueError('configured file differs: ' + path)
        self.diffs.append({'before_header': path, 'after_header': path, 'before': old, 'after': content})
        self.changed = True
        if not self.preview:
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            # Keep one recoverable original, never replace it on repeat apply.
            backup = Path(path + '.standalone-original')
            if p.exists() and not backup.exists():
                shutil.copy2(p, backup)
            fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix='.standalone-')
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(content)
                os.chmod(tmp, mode)
                os.replace(tmp, p)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return True

    def preflight(self):
        release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        require(release.get('ID', '').strip('"') == 'debian' and release.get('VERSION_ID', '').strip('"').split('.')[0] == '13', 'official PVE9 Debian13 installation required')
        version = self.command(['pveversion'])
        require(re.match(r'pve-manager/9\.', version) is not None, 'PVE major version must be 9')
        require(not Path('/etc/pve/corosync.conf').exists(), 'cluster configuration detected; refusing standalone operations')
        status = self.api('/cluster/status')
        require(not any(x.get('type') == 'cluster' for x in status), 'unexpected cluster membership')
        nodes = [x for x in status if x.get('type') == 'node']
        require(len(nodes) == 1 and nodes[0].get('local') == 1, 'exactly one local standalone node required')
        require(not Path('/etc/pve/ceph.conf').exists() and not Path('/etc/ceph/ceph.conf').exists(), 'existing Ceph configuration detected; inspect separately, never remove automatically')
        self.storage = [dict(self.api('/storage/' + x['storage']), storage=x['storage']) for x in self.api('/storage')]
        require(not any(x.get('type') in ('rbd', 'cephfs') for x in self.storage), 'existing Ceph storage detected; standalone configuration refused')
        self.report['platform'] = {'pveversion': version, 'node': nodes[0].get('name')}

    def discover(self):
        commands = {
            'cpu': ['lscpu', '--json'],
            'memory': ['free', '--bytes'],
            'disks': ['lsblk', '--json', '--bytes', '--output', 'NAME,PATH,SIZE,MODEL,SERIAL,TYPE,FSTYPE,MOUNTPOINTS'],
            'mounts': ['findmnt', '--json'],
            'network': ['ip', '-json', 'address', 'show'],
            'storage_status': ['pvesm', 'status'],
            'zfs': ['zpool', 'status'],
            'lvm': ['lvs', '--reportformat', 'json', '-o', 'lv_name,vg_name,lv_size,devices'],
            'boot_tool': ['proxmox-boot-tool', 'status'],
            'bootctl': ['bootctl', '--no-pager', 'status'],
        }
        self.report['storage_config'] = self.storage
        self.report['efi'] = Path('/sys/firmware/efi').exists()
        self.report['active_cmdline'] = Path('/proc/cmdline').read_text().strip()
        for name, cmd in commands.items():
            if not shutil.which(cmd[0]):
                self.report[name] = {'available': False}
                continue
            rc, out, err = self.m.run_command(cmd)
            self.report[name] = {'rc': rc, 'stdout': out.strip(), 'stderr': err.strip()}
        self.report['pci'] = self.pci()

    def timezone(self):
        zone = Path('/usr/share/zoneinfo') / self.c['timezone']
        require(zone.is_file(), 'configured timezone does not exist')
        local = Path('/etc/localtime')
        same = local.exists() and local.read_bytes() == zone.read_bytes()
        if not same:
            require(not self.verify, 'timezone differs')
            self.changed = True
            self.diffs.append({'before': str(local.resolve()), 'after': str(zone)})
            if not self.preview:
                if local.exists() and not Path('/etc/localtime.standalone-original').exists():
                    shutil.copy2(local, '/etc/localtime.standalone-original')
                tmp = Path('/etc/localtime.standalone-new')
                tmp.symlink_to(zone)
                tmp.replace(local)
        self.file('/etc/timezone', self.c['timezone'] + '\n')
        active = []
        for service in ('chrony.service', 'systemd-timesyncd.service'):
            rc, out, _ = self.m.run_command(['systemctl', 'is-active', service])
            if rc == 0 and out.strip() == 'active':
                active.append(service)
        require(len(active) == 1, 'exactly one supported existing time-sync service must be active; configure deliberately before apply')
        synced = self.command(['timedatectl', 'show', '--property=NTPSynchronized', '--value'])
        require(synced == 'yes', 'host time is not synchronised; inspect existing time-sync service')
        for service in ('pveproxy.service', 'pvedaemon.service', 'pvestatd.service'):
            require(self.command(['systemctl', 'is-active', service]) == 'active', service + ' must be active')
        self.report['time_sync'] = {'service': active[0], 'synchronised': True}

    def repositories(self):
        mode = self.c['repository']
        if mode == 'preserve':
            return
        # Do not edit arbitrary mixed source files. Recognise only dedicated PVE files.
        dedicated = {'pve-enterprise.sources', 'pve-no-subscription.sources', 'pve-install-repo.list', 'pve-enterprise.list'}
        for p in [Path('/etc/apt/sources.list')] + list(Path('/etc/apt/sources.list.d').glob('*')):
            if not p.is_file():
                continue
            content = p.read_text()
            if mode == 'no-subscription' and re.search(r'enterprise\.proxmox\.com/debian/ceph-', content):
                # Fresh ISO installs can include an unused enterprise Ceph source.
                # Preflight already rejected every configured Ceph installation.
                require(p.name in ('ceph.sources', 'ceph.list'), 'Ceph enterprise source in unexpected file; review manually')
                if p.suffix == '.sources':
                    fields = {}
                    for line in content.splitlines():
                        if not line.strip() or line.lstrip().startswith('#'):
                            continue
                        require(':' in line and not line[0].isspace(), 'unsupported Ceph repository stanza')
                        k, v = line.split(':', 1)
                        require(k not in fields, 'mixed Ceph repository stanzas require manual review')
                        fields[k] = v.strip()
                    require(set(fields) <= {'Types', 'URIs', 'Suites', 'Components', 'Signed-By', 'Enabled'}, 'unsupported Ceph source fields')
                    require(fields.get('Types') == 'deb' and fields.get('Suites') == 'trixie' and fields.get('Components') == 'enterprise', 'unsupported Ceph enterprise source')
                    require(re.fullmatch(r'https://enterprise\.proxmox\.com/debian/ceph-(?:squid|tentacle)', fields.get('URIs', '')) is not None, 'unrecognised Ceph enterprise source URI')
                    require(fields.get('Enabled', 'yes') in ('yes', 'no'), 'unsupported Ceph source enabled value')
                    require(fields.get('Signed-By', '/usr/share/keyrings/proxmox-archive-keyring.gpg') == '/usr/share/keyrings/proxmox-archive-keyring.gpg', 'unexpected Ceph source signing key')
                    disabled = re.sub(r'^Enabled:.*$', 'Enabled: no', content, flags=re.M) if 'Enabled' in fields else content.rstrip() + '\nEnabled: no\n'
                    self.file(str(p), disabled)
                else:
                    lines = content.splitlines()
                    require(all(not line.strip() or line.lstrip().startswith('#') or re.fullmatch(r'deb https://enterprise\.proxmox\.com/debian/ceph-(?:squid|tentacle) trixie enterprise', line.strip()) for line in lines), 'mixed Ceph legacy source requires manual review')
                    self.file(str(p), '\n'.join('# standalone disabled: ' + line if line.strip() and not line.lstrip().startswith('#') else line for line in lines) + '\n')
                continue
            if re.search(r'(?:enterprise\.proxmox\.com|download\.proxmox\.com)/debian/pve', content):
                require(p.name in dedicated, 'PVE repository in non-dedicated source file; review manually: ' + str(p))
                if p.suffix == '.sources':
                    # Refuse extra stanzas, signed-by overrides, unrelated repository data.
                    fields = {}
                    for line in content.splitlines():
                        if not line.strip() or line.lstrip().startswith('#'):
                            continue
                        require(':' in line and not line[0].isspace(), 'unsupported repository stanza')
                        k, v = line.split(':', 1)
                        require(k not in fields, 'multiple repository stanzas require manual review')
                        fields[k] = v.strip()
                    require(fields.get('Types') == 'deb' and fields.get('Suites') == 'trixie' and fields.get('Components') in ('pve-enterprise', 'pve-no-subscription'), 'unsupported PVE source; review manually')
                    require(set(fields) <= {'Types', 'URIs', 'Suites', 'Components', 'Signed-By', 'Enabled'}, 'unsupported PVE source fields')
                    expected_uri = 'https://enterprise.proxmox.com/debian/pve' if fields['Components'] == 'pve-enterprise' else 'http://download.proxmox.com/debian/pve'
                    require(fields.get('URIs') in (expected_uri, expected_uri.replace('http:', 'https:')), 'unexpected PVE source URI')
                    require(fields.get('Signed-By', '/usr/share/keyrings/proxmox-archive-keyring.gpg') == '/usr/share/keyrings/proxmox-archive-keyring.gpg', 'unexpected source signing key')
                    enabled = fields['Components'] == ('pve-enterprise' if mode == 'enterprise' else 'pve-no-subscription')
                    fields['Enabled'] = 'yes' if enabled else 'no'
                    self.file(str(p), ''.join(k + ': ' + v + '\n' for k, v in fields.items()))
                else:
                    lines = content.splitlines()
                    require(all(not line.strip() or line.lstrip().startswith('#') or re.fullmatch(r'deb https?://(?:enterprise|download)\.proxmox\.com/debian/pve trixie pve-(?:enterprise|no-subscription)', line.strip()) for line in lines), 'mixed or unsupported legacy source file; review manually')
                    self.file(str(p), '\n'.join('# standalone disabled: ' + l if l.strip() and not l.lstrip().startswith('#') else l for l in lines) + '\n')
        component = 'pve-enterprise' if mode == 'enterprise' else 'pve-no-subscription'
        uri = 'https://enterprise.proxmox.com/debian/pve' if mode == 'enterprise' else 'http://download.proxmox.com/debian/pve'
        target = '/etc/apt/sources.list.d/' + component + '.sources'
        # Don't overwrite a pre-existing file without validating above.
        p = Path(target)
        require(not p.exists() or '/debian/pve' in p.read_text(), 'repository target exists with unrelated content')
        self.file(target, 'Types: deb\nURIs: ' + uri + '\nSuites: trixie\nComponents: ' + component + '\nSigned-By: /usr/share/keyrings/proxmox-archive-keyring.gpg\nEnabled: yes\n')

    def packages(self):
        missing = []
        for name in self.c['packages']:
            rc, out, _ = self.m.run_command(['dpkg-query', '-W', '-f=${Status}', name])
            if rc != 0 or out.strip() != 'install ok installed':
                missing.append(name)
        if missing:
            require(not self.verify, 'explicit packages missing: ' + ','.join(missing))
            self.diffs.append({'before': 'packages missing', 'after': ','.join(missing)})
            self.changed = True
            if not self.preview:
                self.command(['apt-get', 'update'])
                self.command(['apt-get', '-y', '--no-remove', '--no-install-recommends', 'install'] + missing)

    def object(self, kind, path, desired, existing, create_extra=None):
        identity = desired.pop('id')
        current = next((x for x in existing if str(x.get('storage' if kind == 'storage' else 'id')) == identity), None)
        compare = dict(current or {})
        for key in ('disable', 'enabled'):
            if key in desired:
                compare.setdefault(key, 0 if key == 'disable' else 1)
        if current is not None and equivalent(compare, desired):
            return
        require(current is None or identity in self.state[kind], 'existing conflicting non-managed %s ID: %s' % (kind, identity))
        require(not self.verify, 'missing/different %s: %s' % (kind, identity))
        self.diffs.append({'before': compare, 'after': dict(desired, id=identity)})
        command = ['pvesh', 'set' if current else 'create', path + '/' + identity if current else path]
        if not current:
            command += ['--storage' if kind == 'storage' else '--id', identity]
        payload = dict(desired)
        if current:
            payload.pop('type', None)
        for key, value in payload.items():
            command += ['--' + key, str(value)]
        self.mutate(command)
        if identity not in self.state[kind]:
            self.state[kind].append(identity)

    def storage_backups(self):
        existing_ids = {s['storage'] for s in self.storage}
        require(set(self.c['storage']['local_expected_ids']) <= existing_ids, 'expected installer storage ID missing; no local storage is ever created')
        desired_nfs = []
        for n in self.c['storage']['nfs']:
            if not n['enabled']:
                continue
            d = dict(id=n['id'], type='nfs', server=n['server'], export=n['export'], content=','.join(sorted(n['content'])), disable=0)
            if n.get('options'):
                d['options'] = n['options']
            # A registration could mount over a pre-existing directory. Never do so.
            existing = next((s for s in self.storage if s['storage'] == n['id']), None)
            mount = Path('/mnt/pve') / n['id']
            if existing is None:
                require(not mount.exists() or (mount.is_dir() and not any(mount.iterdir()) and not os.path.ismount(mount)), 'NFS mount path already contains data or is mounted')
            else:
                require(existing.get('path', str(mount)) == str(mount), 'existing NFS has non-default mount path')
                require(not existing.get('nodes') and not existing.get('username') and not existing.get('password'), 'existing NFS has unsupported restrictions/credentials')
                # An omitted options field means the Proxmox default, never preserve custom settings silently.
                if 'options' not in d:
                    require(not existing.get('options'), 'existing NFS has unreviewed mount options')
            self.object('storage', '/storage', d, self.storage)
            desired_nfs.append(n)
        configured = {s['storage']: s for s in self.storage}
        for n in desired_nfs:
            configured[n['id']] = {'content': ','.join(n['content']), 'disable': 0}
        jobs = self.api('/cluster/backup')
        resources = self.api('/cluster/resources') if any(b['enabled'] for b in self.c['backups']) else []
        vmids = {int(r['vmid']) for r in resources if r.get('type') in ('qemu', 'lxc') and 'vmid' in r}
        for b in self.c['backups']:
            if not b['enabled']:
                continue
            store = configured.get(b['storage'])
            require(store is not None and not store.get('disable') and 'backup' in store.get('content', '').split(','), 'backup target must be enabled and accept backup content')
            require(set(b['vmids']) <= vmids, 'backup references nonexistent VM/container IDs')
            self.command(['systemd-analyze', 'calendar', b['schedule']])
            d = dict(id=b['id'], storage=b['storage'], schedule=b['schedule'], vmid=','.join(str(x) for x in sorted(b['vmids'])), mode=b.get('mode', 'snapshot'), compress=b.get('compress', 'zstd'), enabled=1, **{'prune-backups': ','.join(k + '=' + str(v) for k, v in sorted(b['prune_backups'].items()))})
            current = next((j for j in jobs if j.get('id') == b['id']), None)
            if current:
                require(not current.get('all') and not current.get('pool') and not current.get('exclude'), 'existing backup job has broad selection fields; review manually')
            self.object('backup', '/cluster/backup', d, jobs)
        if not self.verify and (self.state_path.exists() or self.state != {'storage': [], 'backup': []}):
            self.file(str(self.state_path), json.dumps(self.state, sort_keys=True, indent=2) + '\n', 0o600)

    def pci(self):
        devices = {}
        def read(p, default=''):
            try:
                return p.read_text().strip()
            except FileNotFoundError:
                return default
        framebuffer_devices = []
        for fb in Path('/sys/class/graphics').glob('fb*'):
            framebuffer_devices.append(str((fb / 'device').resolve()))
        for p in Path('/sys/bus/pci/devices').iterdir():
            group = (p / 'iommu_group').resolve() if (p / 'iommu_group').exists() else None
            devices[p.name] = {'id': read(p / 'vendor').removeprefix('0x') + ':' + read(p / 'device').removeprefix('0x'), 'class': read(p / 'class'), 'driver': (p / 'driver').resolve().name if (p / 'driver').exists() else None, 'group': group.name if group else None, 'peers': sorted(x.name for x in (group / 'devices').iterdir()) if group else [], 'console': read(p / 'boot_vga') == '1' or any(str(p.resolve()) in x for x in framebuffer_devices)}
        return devices

    def gpu(self):
        g = self.c['gpu']
        devices = self.pci()
        self.report['pci'] = devices
        if self.action == 'gpu-discover':
            self.discover()
            return
        require(g['enabled'], 'GPU preparation/verification requires gpu.enabled true')
        cpu = Path('/proc/cpuinfo').read_text()
        vendor = next((line.split(':', 1)[1].strip() for line in cpu.splitlines() if line.startswith('vendor_id')), '')
        active = Path('/proc/cmdline').read_text().strip()
        if self.action in ('gpu-verify', 'gpu-post-reboot'):
            selected = gpu_selection(devices, g)
            iommu_tokens(active, vendor)
            require(set(iommu_tokens('', vendor).split()) <= set(active.split()), 'required IOMMU parameters are not active; explicit reboot may be pending')
            if self.action == 'gpu-post-reboot' and not Path('/etc/modprobe.d/standalone-vfio.conf').exists():
                self.report['gpu'] = {'stage': 'IOMMU active and isolation observed; run gpu-discover then gpu-prepare to prepare VFIO binding'}
                return
            require(all(devices[a]['driver'] == 'vfio-pci' for a in selected), 'selected PCI functions are not bound to vfio-pci')
            self.report['gpu_verified'] = selected
            return
        gpu_selection(devices, g, require_groups=False)
        efi = Path('/sys/firmware/efi').exists()
        rc, out, err = self.m.run_command(['bootctl', '--no-pager', 'status'])
        # Inspect current boot loader section, not the list of installed loaders.
        current = out.split('Current Boot Loader:', 1)[1].split('\n\n', 1)[0] if 'Current Boot Loader:' in out else ''
        loader = 'systemd-boot' if re.search(r'Product:\s+systemd-boot', current) else 'grub' if re.search(r'Product:\s+GRUB', current, re.I) else None
        pbt = self.command(['proxmox-boot-tool', 'status'], acceptable=(0, 1, 2))
        boot = bootloader_choice(g['bootloader'], efi, loader, pbt)
        # Existing unsafe settings cannot be made safe by silently adding our own.
        iommu_tokens(active, vendor)
        for pattern in ('/etc/modprobe.d/*.conf', '/etc/default/grub.d/*.cfg'):
            for filename in glob.glob(pattern):
                value = Path(filename).read_text()
                require(not re.search(r'pcie_acs_override|allow_unsafe_interrupts\s*=\s*(?:1|Y|yes)', value, re.I), 'unsafe existing host setting: ' + filename)
                if filename != '/etc/modprobe.d/standalone-vfio.conf':
                    require(not re.search(r'^\s*options\s+vfio[-_]pci\s+.*ids=', value, re.M), 'unmanaged VFIO ID binding exists; review manually')
        ready = all(devices[a]['group'] is not None for a in g['pci_addresses'])
        if ready:
            gpu_selection(devices, g)
        else:
            require(not Path('/etc/modprobe.d/standalone-vfio.conf').exists(), 'IOMMU groups disappeared after binding preparation; inspect firmware')
        tokens = iommu_tokens('', vendor)
        boot_changed = False
        if boot == 'systemd-boot':
            path = Path('/etc/kernel/cmdline')
            require(path.is_file(), 'systemd-boot kernel cmdline file missing')
            boot_changed = self.file(str(path), iommu_tokens(path.read_text(), vendor) + '\n')
        else:
            original = Path('/etc/default/grub').read_text()
            base_args = []
            for name in ('GRUB_CMDLINE_LINUX_DEFAULT', 'GRUB_CMDLINE_LINUX'):
                assignments = list(re.finditer(r'^\s*' + name + r'=(.*)$', original, re.M))
                require(len(assignments) <= 1, 'duplicate GRUB cmdline assignments require manual review: ' + name)
                for match in assignments:
                    parsed = shlex.split(match.group(1), comments=True)
                    require(len(parsed) == 1 and '$' not in parsed[0] and '`' not in parsed[0], 'GRUB cmdline must use a literal assignment for safe validation')
                    iommu_tokens(parsed[0], vendor)
                    base_args.extend(parsed[0].split())
            missing = [token for token in tokens.split() if token not in base_args]
            # Fail rather than override unreviewed drop-ins that can replace our arguments.
            for filename in glob.glob('/etc/default/grub.d/*'):
                if Path(filename).name != '90-standalone-iommu.cfg':
                    value = Path(filename).read_text()
                    require(not re.search(r'^\s*GRUB_CMDLINE_LINUX', value, re.M), 'additional GRUB cmdline drop-in requires manual review')
            grub_dropin = '# Managed by standalone-proxmox\n'
            if missing:
                grub_dropin += 'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT ' + ' '.join(missing) + '"\n'
            boot_changed = self.file('/etc/default/grub.d/90-standalone-iommu.cfg', grub_dropin)
        vfio_changed = False
        if ready:
            gpu_selection(devices, g)
            require(Path('/usr/share/initramfs-tools/hook-functions').is_file(), 'initramfs-tools hook support missing')
            vfio_changed |= self.file('/etc/modules-load.d/standalone-vfio.conf', 'vfio\nvfio_pci\nvfio_iommu_type1\n')
            vfio_changed |= self.file('/etc/initramfs-tools/hooks/standalone-vfio', '#!/bin/sh\nset -e\ncase "${1:-}" in prereqs) exit 0 ;; esac\n. /usr/share/initramfs-tools/hook-functions\nforce_load vfio\nforce_load vfio_pci\nforce_load vfio_iommu_type1\n', 0o755)
            drivers = {devices[a]['driver'] for a in g['pci_addresses']} - {None, 'vfio-pci'}
            managed = Path('/etc/modprobe.d/standalone-vfio.conf')
            if managed.exists():
                drivers.update(re.findall(r'^softdep ([a-zA-Z0-9_-]+) pre: vfio-pci$', managed.read_text(), re.M))
            require(drivers <= {'nouveau', 'nvidia', 'amdgpu', 'radeon', 'snd_hda_intel', 'i915', 'xe', 'xhci_hcd', 'nvidia-gpu'}, 'unsupported selected GPU driver; review binding preparation manually')
            vfio_changed |= self.file('/etc/modprobe.d/standalone-vfio.conf', '# Managed by standalone-proxmox\noptions vfio-pci ids=' + ','.join(sorted(g['pci_ids'])) + '\n' + ''.join('softdep ' + driver + ' pre: vfio-pci\n' for driver in sorted(drivers)))
        else:
            require(not Path('/etc/modprobe.d/standalone-vfio.conf').exists(), 'IOMMU groups disappeared after binding preparation; inspect firmware')
        if (boot_changed or vfio_changed) and not self.preview:
            self.command(['update-initramfs', '-u', '-k', 'all'])
            self.command(['update-grub'] if boot == 'grub' else ['proxmox-boot-tool', 'refresh'])
            if boot == 'grub' and 'configured with' in pbt:
                self.command(['proxmox-boot-tool', 'refresh'])
        self.report['gpu'] = {'stage': 'binding prepared' if ready else 'IOMMU boot arguments only; explicit reboot then gpu-discover and repeat gpu-prepare before binding', 'reboot_required': boot_changed or vfio_changed or any(devices[a]['driver'] != 'vfio-pci' for a in g['pci_addresses']), 'bootloader': boot, 'recovery_backups_suffix': '.standalone-original'}

    def run(self):
        self.preflight()
        def dispatch():
            if self.action == 'discover':
                self.discover()
            elif self.action.startswith('gpu-'):
                self.gpu()
            else:
                self.timezone()
                self.repositories()
                self.packages()
                self.storage_backups()
        # Validate every desired object before the first write. This is not a
        # transaction: external changes or command failures still need review.
        if not self.preview and self.action in ('apply', 'gpu-prepare'):
            original_state = copy.deepcopy(self.state)
            self.preview = True
            dispatch()
            self.preview = False
            self.state = original_state
            self.changed = False
            self.diffs = []
        dispatch()
        if self.preview:
            self.report['preview_limits'] = 'Read-only probes ran. No files, packages, API objects, initramfs or bootloader changed. NAS access, package resolution, boot refresh and restore cannot be proven by preview.'
        return dict(changed=self.changed, report=self.report, diff=self.diffs)


def main():
    m = AnsibleModule(argument_spec=dict(action=dict(type='str', required=True, choices=['discover', 'plan', 'apply', 'verify', 'gpu-discover', 'gpu-plan', 'gpu-prepare', 'gpu-verify', 'gpu-post-reboot']), config=dict(type='dict', required=True)), supports_check_mode=True)
    try:
        host = Host(m)
        if m.params['action'] in ('plan', 'gpu-plan'):
            require(m.check_mode, 'plan actions require Ansible check mode')
        m.exit_json(**host.run())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        m.fail_json(msg=str(exc))


if __name__ == '__main__':
    main()
