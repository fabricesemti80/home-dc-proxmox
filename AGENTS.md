# AGENTS.md

## Secrets and environment variables

[`docs/secrets-and-env-vars.md`](docs/secrets-and-env-vars.md) is the authoritative inventory of every secret, credential and environment variable this repository reads or writes.

- Update it **in the same change** whenever you add, rename, remove or move a secret or env var. That includes changing a Doppler project/config, a Keychain item, a role default that names a secret, or a script's `os.environ` / `lookup('env', ...)` use.
- Record names, locations, writers, readers and purpose only. Never write secret values into the file, a commit, a log or chat.
- If a change affects a value shared with another repository (for example `PROXMOX_TOKEN_*` referenced from `home-dc-terraform/prd`, or `PVE_MONITORING_TOKEN_SECRET` and `MONITORING_HW_*` used by `home-dc-kubernetes`), update that repository's `docs/secrets-and-env-vars.md` too.
- Before finishing, check for drift: `grep -rnE "doppler|DOPPLER_|lookup\('env'|os\.environ" roles scripts standalone`. Every name it shows must appear in the inventory.
