"""Pure validation/comparison helpers shared by controller and target module."""
import re


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(value, allowed, required=None):
    require(type(value) is dict, 'expected mapping')
    require(not set(value) - set(allowed), 'unknown fields: ' + str(sorted(set(value) - set(allowed))))
    require(set(required or allowed) <= set(value), 'missing fields: ' + str(sorted(set(required or allowed) - set(value))))


def text(value, pattern=r'[^\x00-\x1f]+'):
    require(type(value) is str and re.fullmatch(pattern, value) is not None, 'invalid text value')


def boolean(value):
    require(type(value) is bool, 'boolean required')


def integer(value, low=1, high=2147483647):
    require(type(value) is int and low <= value <= high, 'integer outside allowed range')


def unique(values):
    require(type(values) is list, 'list required')
    require(len(values) == len(set(values)), 'duplicate values')


def identifier(value):
    text(value, r'[A-Za-z][A-Za-z0-9_-]{0,63}')


def validate_config(data):
    keys(data, ['proxmox_host'])
    c = data['proxmox_host']
    keys(c, ['deployment_enabled', 'mode', 'expected_pve_major', 'expected_debian_major', 'timezone', 'repository', 'packages', 'storage', 'backups', 'gpu'])
    boolean(c['deployment_enabled'])
    require(c['mode'] == 'standalone', 'mode must be standalone')
    require(type(c['expected_pve_major']) is int and c['expected_pve_major'] == 9, 'only PVE 9 is supported')
    require(type(c['expected_debian_major']) is int and c['expected_debian_major'] == 13, 'only Debian 13 is supported')
    text(c['timezone'], r'[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+')
    require('..' not in c['timezone'], 'invalid timezone')
    require(c['repository'] in ('preserve', 'no-subscription', 'enterprise'), 'invalid repository')
    unique(c['packages'])
    for p in c['packages']:
        text(p, r'[a-z0-9][a-z0-9+.-]*')
        require(p not in ('proxmox-ve', 'pve-kernel', 'ifupdown', 'ifupdown2', 'ceph', 'corosync', 'keepalived'), 'infrastructure package outside baseline scope')
    keys(c['storage'], ['local_expected_ids', 'nfs'])
    unique(c['storage']['local_expected_ids'])
    for i in c['storage']['local_expected_ids']:
        identifier(i)
    require(type(c['storage']['nfs']) is list and type(c['backups']) is list, 'storage/backups must be lists')
    ids = list(c['storage']['local_expected_ids'])
    enabled_backup_storage = set(ids)
    for n in c['storage']['nfs']:
        keys(n, ['id', 'server', 'export', 'content', 'options', 'enabled'], ['id', 'server', 'export', 'content', 'enabled'])
        identifier(n['id'])
        require(n['id'] not in ids, 'storage IDs must be unique')
        ids.append(n['id'])
        text(n['server'], r'[A-Za-z0-9][A-Za-z0-9.:-]*')
        text(n['export'], r'/[A-Za-z0-9_./-]*')
        require('..' not in n['export'].split('/'), 'invalid NFS export')
        boolean(n['enabled'])
        unique(n['content'])
        require(bool(n['content']) and set(n['content']) <= {'backup', 'iso', 'vztmpl', 'snippets', 'images', 'rootdir'}, 'invalid NFS content')
        if 'options' in n:
            text(n['options'], r'[A-Za-z0-9_=.,:-]+')
            require(not re.search(r'pass|secret|token|cred|user', n['options'], re.I), 'credentials forbidden in NFS options')
        if n['enabled'] and 'backup' in n['content']:
            enabled_backup_storage.add(n['id'])
    jobs = []
    for b in c['backups']:
        keys(b, ['id', 'storage', 'schedule', 'vmids', 'mode', 'compress', 'enabled', 'prune_backups'], ['id', 'storage', 'schedule', 'vmids', 'enabled', 'prune_backups'])
        identifier(b['id'])
        require(b['id'] not in jobs, 'duplicate job ID')
        jobs.append(b['id'])
        identifier(b['storage'])
        boolean(b['enabled'])
        require(not b['enabled'] or b['storage'] in enabled_backup_storage, 'backup storage must be explicitly enabled/expected')
        text(b['schedule'], r'[A-Za-z0-9*,: /.-]+')
        require(bool(b['vmids']), 'explicit nonempty vmids required')
        unique(b['vmids'])
        for i in b['vmids']:
            integer(i, 100, 999999999)
        require(b.get('mode', 'snapshot') in ('snapshot', 'suspend', 'stop'), 'invalid backup mode')
        require(b.get('compress', 'zstd') in ('zstd', 'lzo', 'gzip'), 'invalid compression')
        require(type(b['prune_backups']) is dict and bool(b['prune_backups']), 'positive retention map required')
        require(set(b['prune_backups']) <= {'keep-last', 'keep-hourly', 'keep-daily', 'keep-weekly', 'keep-monthly', 'keep-yearly'}, 'invalid retention key')
        for n in b['prune_backups'].values():
            integer(n)
    g = c['gpu']
    keys(g, ['enabled', 'bootloader', 'pci_addresses', 'pci_ids', 'allow_host_console_loss'])
    boolean(g['enabled'])
    boolean(g['allow_host_console_loss'])
    require(g['bootloader'] in (None, 'grub', 'systemd-boot'), 'explicit grub or systemd-boot required')
    unique(g['pci_addresses'])
    unique(g['pci_ids'])
    for a in g['pci_addresses']:
        text(a, r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]')
    for i in g['pci_ids']:
        text(i, r'[0-9a-f]{4}:[0-9a-f]{4}')
    if g['enabled']:
        require(bool(g['pci_addresses']) and bool(g['pci_ids']), 'enabled GPU requires explicit BDFs and IDs')
    return c


def validate_inventory(data, alias=None):
    keys(data, ['all'])
    keys(data['all'], ['children'])
    keys(data['all']['children'], ['standalone_proxmox'])
    group = data['all']['children']['standalone_proxmox']
    keys(group, ['hosts'])
    require(type(group['hosts']) is dict and len(group['hosts']) == 1, 'exactly one concrete standalone_proxmox host required')
    if alias is None or alias == '':
        alias = next(iter(group['hosts']))
    identifier(alias)
    require(alias not in ('all', 'ungrouped', 'standalone_proxmox'), 'reserved inventory alias')
    require(list(group['hosts']) == [alias], 'inventory alias must equal --host')
    host = group['hosts'][alias]
    keys(host, ['ansible_host', 'ansible_port'], ['ansible_host'])
    text(host['ansible_host'], r'[A-Za-z0-9][A-Za-z0-9.:-]*')
    if 'ansible_port' in host:
        integer(host['ansible_port'], 1, 65535)
    return data


def iommu_tokens(existing, vendor):
    require(vendor in ('GenuineIntel', 'AuthenticAMD'), 'unsupported CPU vendor')
    wanted = 'intel_iommu=on' if vendor == 'GenuineIntel' else 'amd_iommu=on'
    tokens = existing.split()
    for t in tokens:
        require(not t.startswith(('pcie_acs_override', 'allow_unsafe_interrupts', 'vfio_iommu_type1.allow_unsafe_interrupts')), 'unsafe kernel argument present')
        if t.startswith(('intel_iommu=', 'amd_iommu=')):
            require(t == wanted, 'conflicting IOMMU argument')
        if t.startswith('iommu='):
            require(t == 'iommu=pt', 'conflicting iommu argument')
    return ' '.join(dict.fromkeys(tokens + [wanted, 'iommu=pt']))


def bootloader_choice(requested, efi, current_loader, pbt_status):
    require(requested in ('grub', 'systemd-boot'), 'gpu.bootloader must be explicitly selected')
    require(not efi or current_loader in ('grub', 'systemd-boot'), 'EFI bootloader ambiguous; inspect bootctl status')
    require((efi and requested == current_loader) or (not efi and requested == 'grub'), 'configured bootloader mismatches current boot')
    configured = set(re.findall(r'configured with:\s*(uefi|grub)\b', pbt_status, re.I))
    configured = {x.lower() for x in configured}
    if requested == 'systemd-boot':
        require(configured == {'uefi'}, 'systemd-boot requires exclusively uefi-configured Proxmox ESPs')
    elif configured:
        require(configured == {'grub'}, 'GRUB selection conflicts with Proxmox ESP loader configuration')
    return requested


def gpu_selection(devices, gpu, require_groups=True):
    selected = set(gpu['pci_addresses'])
    require(selected <= set(devices), 'selected PCI function missing')
    slots = {a.rsplit('.', 1)[0] for a in selected}
    full_slots = {a for a in devices if a.rsplit('.', 1)[0] in slots}
    require(full_slots == selected, 'all PCI functions in each selected GPU slot must be explicitly reviewed')
    for slot in slots:
        members = [devices[a] for a in selected if a.rsplit('.', 1)[0] == slot]
        require(any(d.get('class', '').startswith('0x03') for d in members), 'each selected slot must include a display controller')
        require(all(d.get('class', '').startswith(('0x03', '0x0403', '0x0c03', '0x0c80')) for d in members), 'unsupported GPU ancillary function class')
    actual_ids = {devices[a]['id'] for a in selected}
    require(actual_ids == set(gpu['pci_ids']), 'selected BDF IDs differ from reviewed pci_ids')
    require(not any(a not in selected and d['id'] in actual_ids for a, d in devices.items()), 'duplicate PCI IDs would bind unselected devices')
    for a in selected:
        d = devices[a]
        require(not d['console'] or gpu['allow_host_console_loss'], 'selected GPU drives host console; recovery access and explicit allow_host_console_loss required')
        if require_groups:
            require(d['group'] is not None, 'IOMMU group unavailable')
            require(set(d['peers']) <= selected, 'IOMMU group includes unselected functions')
    return sorted(selected)


def equivalent(current, desired):
    """PVE encodes lists as comma strings, booleans as integers, omits defaults."""
    def norm(k, v):
        if k in ('content', 'vmid'):
            return sorted(str(v).split(','))
        if k == 'prune-backups':
            return sorted(str(v).split(','))
        return str(v)
    return all(norm(k, current.get(k, '')) == norm(k, v) for k, v in desired.items())
