# AGENTS.md

## Secrets and environment variables

[`docs/secrets-and-env-vars.md`](docs/secrets-and-env-vars.md) is the authoritative inventory of every secret, credential and environment variable this repository reads or writes.

- Update it **in the same change** whenever you add, rename, remove or move a secret or env var. That includes changing a Doppler project/config, a Keychain item, a role default that names a secret, or a script's `os.environ` / `lookup('env', ...)` use.
- Record names, locations, writers, readers and purpose only. Never write secret values into the file, a commit, a log or chat.
- If a change affects a value shared with another repository (for example `PROXMOX_TOKEN_*` referenced from `home-dc-terraform/prd`, or `PVE_MONITORING_TOKEN_SECRET` and `MONITORING_HW_*` used by `home-dc-kubernetes`), update that repository's `docs/secrets-and-env-vars.md` too.
- Before finishing, check for drift: `grep -rnE "doppler|DOPPLER_|lookup\('env'|os\.environ" roles scripts standalone`. Every name it shows must appear in the inventory.

## Role separation

Each concern is its own role under `roles/`, wired into `site.yml` with its own tags and, where useful, `task <name>-plan` / `task <name>-apply` entries in `Taskfile.yml`.

- Add a new capability as a **new role**; do not grow an unrelated role. A role owns its tasks, defaults, handlers, files and templates, and `site.yml` carries no task logic.
- Do not reach into another role's tasks or handlers. A role may read another role's `defaults/main.yml` only to avoid duplicating a single source of truth (for example the SSD-to-VM table), and must say so in a comment.
- Every role starts with a banner task named `"========== ROLE: <NAME> =========="` (an `ansible.builtin.debug` with a one-line message), so each role is visibly separated in the playbook output. Use `"---------- <ROLE>: <SECTION> ----------"` for distinct sections inside a role.
- Role order in `site.yml` is deliberate: a role that reports on or depends on another role's result runs after it. Roles that only describe state (for example `proxmox_hardware_notes`) go last. State changed outside this repository (OpenTofu attaching disks, VM changes) is not visible until the next apply, so document when to re-run.
- A role must be safe in check mode: read-only inspection runs with `check_mode: false`, and nothing is written, restarted or reloaded in check mode.

## Documentation and diagrams

Keep the documentation in step with the code **in the same change**.

- Update [`README.md`](README.md): the role list under "Playbook and roles", "What Ansible changes", and any statement about hardware, storage or passthrough that your change alters.
- Update the matching file in `docs/` (or add one) with design, assumptions, validation and rollback.
- Update the diagrams whenever the host, storage, GPU, passthrough or guest layout changes: [`docs/architecture.svg`](docs/architecture.svg) (logical overview shown in the README), [`docs/layout.html`](docs/layout.html) (detailed host diagram) and, for physical or slot changes, [`docs/motherboard.html`](docs/motherboard.html). Also keep [`docs/hardware.md`](docs/hardware.md) and [`docs/storage.md`](docs/storage.md) accurate for disks and storage IDs.
- If a change makes a diagram or README statement untrue and you cannot update it, say so explicitly in the PR instead of leaving it silently stale.
- Run the tests (`python3 -m unittest discover tests`) and `ansible-playbook -i inventory site.yml --syntax-check` before finishing.
