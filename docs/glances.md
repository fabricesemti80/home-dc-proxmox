# Glances system monitor

`proxmox_glances` installs [Glances](https://nicolargo.github.io/glances/) (Debian 13 package `glances`, 4.3.1) on the Proxmox host so an operator can run `glances` over SSH for a live CPU, memory, disk, network and process view. Tags: `glances`. Tasks: `task glances-plan` / `task glances-apply`.

## Design and assumptions

- **No recommended packages.** The role installs with `install_recommends: false`: 19 packages (Glances, FastAPI/uvicorn and their Python dependencies) instead of 147. The extra 128 are pulled by Recommends (a C preprocessor, Tk, fonts, numpy headers) and have no use on a hypervisor. Optional extras are not installed: `lm-sensors` (temperatures), `python3-docker`, `python3-netifaces`, `python3-jinja2`. Add them to the role if a view needs them.
- **No background service by default.** Debian's `postinst` enables and starts `glances.service` (`glances -s -B 127.0.0.1`, a loopback-only server) on first install. The command-line tool does not need it, so the role stops and disables it (`proxmox_glances_service_enabled: false`). Because the unit is recorded as disabled, later package upgrades do not re-enable it. The server never listened beyond loopback, so there was no network exposure either way. The unit does run for the few seconds of the first install before the role stops it.
- **Not a web UI.** The role does not run `glances -w` and opens no port. Exposing a monitor with no authentication on a hypervisor is out of scope; use SSH. Metrics and dashboards stay with `proxmox_hardware_monitoring`.
- No secrets or environment variables are introduced, so `docs/secrets-and-env-vars.md` is unchanged. Host, storage and guest layout are unchanged, so the diagrams are too.
- The role refreshes APT metadata (`update_cache`, valid for one hour) like `proxmox_packages`; it does not upgrade any installed package.

## Validation

```sh
task glances-plan            # check mode: lists the 19 packages, skips the service step
task glances-apply
ssh pve-00 'glances -V; systemctl is-enabled glances.service; systemctl is-active glances.service'
ssh pve-00 'glances --stdout cpu.user,mem.percent,load.min1 --stop-after 1'
ssh pve-00 'ss -ltn'         # same listeners as before: no new port
task glances-apply           # second run: ok, no change from the package task
```

Observed on `pve-00` (Debian 13.7) on the first apply: `glances 4.3.1`, `disabled`/`inactive`, the listener set unchanged, one-shot metrics returned, `/var/log/dpkg.log` showed 19 installs, 0 upgrades, 0 removals. Run `glances` interactively over SSH to use it.

## Rollback

```sh
ssh pve-00 'apt-get remove --purge glances && apt-get autoremove --purge'
```

`autoremove` also removes the Python dependencies that were installed only for Glances; review its list first, because other tools may share them. Then delete the role, its `site.yml` entry and the Taskfile entries, or the next `task apply` reinstalls it. No host reboot, network or storage change is involved.
