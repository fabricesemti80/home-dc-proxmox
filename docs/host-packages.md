# Host packages and wireless regulatory domain

`proxmox_packages` installs `proxmox_packages` (a configurable list):
`wireless-regdb` supplies signed regulatory data, `iw` inspects wireless devices,
`usbutils` identifies USB hardware, and `ethtool` diagnoses Ethernet links.
It installs missing packages, not a distribution upgrade.

`proxmox_wireless_regulatory` is independently optional:
`proxmox_wireless_regulatory_enabled` defaults to false and
`proxmox_wireless_regulatory_country` defaults to `GB`.
`host_vars/pve-00.yml` explicitly enables it for this host in GB.
Use the country where the hardware physically operates, not a preferred channel set.
The role installs its own required tools, so its tag can run independently.

The role writes `/etc/modprobe.d/wireless-regulatory.conf` for module loading and
`/etc/systemd/system/wireless-regulatory.service` to apply the domain at boot.
It also applies the setting immediately, correcting runtime drift. Hardware or
firmware may impose additional restrictions. It does not enable Wi-Fi, configure
credentials, change routing, or restart networking. No new secrets or environment
variables are introduced; host/guest diagrams are unchanged.

## Validation

```sh
task packages-plan
task wireless-regulatory-plan
task packages-apply
task wireless-regulatory-apply
ssh pve-00 'iw reg get; systemctl status wireless-regulatory.service --no-pager'
```

Check mode previews package/file changes without changing the regulatory domain
or starting/reloading services. Reapply should report no changes when converged.

## Rollback

Disabling the opt-in prevents future management; it does not undo existing state.
To remove the configuration, disable and stop `wireless-regulatory.service`, delete
the two managed files, run `systemctl daemon-reload`, and set the appropriate domain
with `iw reg set <country>` (or `00` for the restrictive world domain).
Remove utility packages only if no other role or operator needs them.
