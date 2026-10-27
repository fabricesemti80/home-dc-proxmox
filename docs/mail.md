# Local-host alert delivery

The certificate for `pve-00.krapulax.home` is **not** changed. This internal-only name has no publicly trusted CA certificate; browser warnings remain until a CA trusted by the accessing devices or a public-domain DNS-01 name is chosen. No ACME account or DNS-provider credentials are required for this mail setup.

## One private configuration file

From the repository root, copy `.env_example` to `.env`, set permissions with `chmod 600 .env`, and fill `GMAIL_APP_PASSWORD` with the **app password for `automations.fs@gmail.com`**. The account must have Gmail two-step verification and an active app password. Use the documented simple `KEY=value` format; do not include shell quoting or inline comments. `.env` is ignored by Git and is read by Ansible's controller-side `ini` lookup in properties mode; it is **never executed or copied to the host**. The committed example contains no credential. Do not paste real values into tickets, shell commands, or Ansible output.

This role manages the existing host's loopback-only Postfix service as a Gmail smart host on port 587 with mandatory STARTTLS and SASL. It places the relay password in `/etc/postfix/sasl_passwd` and its indexed map, both mode `0600`; Ansible hides the credential task and map generation with `no_log`. Postfix queues mail during temporary relay outages. It maps the local `root` sender to `automations.fs@gmail.com` for Gmail's sender policy, routes local root mail to `fabrice.semti@gmail.com`, and sets `root@pam`'s Proxmox email to that recipient. It preserves Proxmox's built-in `mail-to-root` sendmail target and `default-matcher` rather than creating a competing notification path. The already-active ZFS event daemon uses `ZED_EMAIL_ADDR="root"`, so its messages follow `/etc/aliases` through Postfix. No network interface, SSH, firewall, storage, GPU, or boot setting is changed.

TLS policy is `smtp_tls_security_level=secure` with `smtp_tls_secure_cert_match=nexthop` and the system CA bundle. This requires both a trusted CA chain and a certificate for the configured relay hostname `smtp.gmail.com` before sending SMTP authentication. `encrypt` alone would only encrypt the connection and would not validate the relay identity; do not downgrade the policy to work around certificate errors. A read-only probe on the host verified Gmail's real chain and hostname; separate negative probes with an incorrect hostname and an unrelated CA bundle both failed certificate verification. These probes do not use the Gmail app password.

## Operator rollout

1. Prepare `.env` locally; verify it is ignored with `git check-ignore .env`. Never commit it.
2. Preview with `ansible-playbook -i inventory site.yml --check --diff --tags mail`, then `task plan`. The protected credential file will show no diff; the package, Postfix configuration, aliases, and Proxmox user update are previewed. In check mode, command handlers and the PVE user mutation do not execute.
3. Review the plan, then run `task apply` yourself. No reboot is needed. The role refuses to run if `.env` is missing, not mode `0600`/`0400`, or lacks required values. Since the mail role is included in `site.yml`, future full plans/applies also require `.env`.
4. Confirm `ssh pve-00 'postfix check; postconf -h relayhost smtp_tls_security_level smtp_sasl_auth_enable; pveum user list --output-format json'`. **Never print** `/etc/postfix/sasl_passwd`, its `.db`, or the app password.
5. Send a Proxmox notification test using Datacenter → Notifications → `mail-to-root` → Test, and verify delivery to `fabrice.semti@gmail.com`.
6. Independently send a local root mail with `printf 'Subject: pve-00 local mail test\n\nLocal mail path OK\n' | ssh pve-00 'sendmail root'` and verify receipt. This tests root alias and Postfix, the path ZED uses; it does not manufacture a ZFS fault.
7. If delivery fails, inspect `ssh pve-00 'mailq; journalctl -u postfix -n 60 --no-pager'` and check outbound DNS/port 587, Gmail app-password status, and sender identity. Do not dump configuration files containing credentials. `mailq` can include recipient addresses. After resolution, rerun `--check --diff --tags mail` for idempotence.

The PVE SMTP target alternative is deliberately not used: Proxmox documents that it bypasses the MTA and does not queue or retry failed deliveries. A successful PVE test alone does not prove that ZFS/system mail works; test both routes.

On the initial rollout, the Proxmox `mail-to-root` test and an independent local-root message were both accepted by Gmail (`250 2.0.0 OK`) and confirmed in the recipient inbox. One older, pre-configuration message remained queued with `alias database unavailable`; it was not resent or discarded. Review `mailq` before deleting or retrying any old queued mail.
