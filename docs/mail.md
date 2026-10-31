# Local-host alert delivery

The certificate for `pve-00.krapulax.home` is **not** changed. This internal-only name has no publicly trusted CA certificate; browser warnings remain until a CA trusted by the accessing devices or a public-domain DNS-01 name is chosen. No ACME account or DNS-provider credentials are required for this mail setup.

## Doppler credential source

The Gmail app password is the `GMAIL_APP_PASSWORD` secret in Doppler project `home-dc-proxmox`, config `prd`. The mail role reads it on the controller with `doppler secrets get GMAIL_APP_PASSWORD --json`, authenticating with an **explicit config-scoped service token** from macOS Keychain (item `home-dc-doppler-proxmox`) or a `DOPPLER_TOKEN` supplied by the controller. It never uses a personal Doppler login. Sender and recipient addresses remain non-secret role defaults. The controller needs the Doppler CLI; the role does not use `.env`.

Ansible hides the in-memory credential and the resulting Postfix file/diff with `no_log`. A pre-existing local `.env` is not used; remove your own ignored copy only after verifying both the check-mode plan and mail delivery. Never print the app password or commit a local credential file. To rotate it, generate a new Google app password and replace the secret through Doppler's interactive prompt (`doppler secrets set GMAIL_APP_PASSWORD -p home-dc-proxmox -c prd`) rather than as a command-line argument, then rerun the mail role.

### Service-token authentication on macOS

Create a **read/write service token** on `home-dc-proxmox` → `prd` (dashboard → Access → Generate; this repo's token is named `ansible-pve-00`), then run `task doppler-token-save` locally and enter the complete token at its hidden prompt. The task refuses personal, CLI and non-`prd` tokens, proves the token can read `home-dc-proxmox/prd`, and only then stores it in your Mac's Keychain. **One token** serves mail reads, config checks and the Terraform credential write.

**Scope:** a Doppler service token is limited to one config. This token can read and change every secret in `home-dc-proxmox/prd` (the Gmail app password and the root-equivalent Terraform token) and nothing else in the workplace. Never send it to chat, put it in `.env`, or pass it as a shell argument. The `security add-generic-password ... -w` terminal prompt previously truncated a token on this Mac; use `task doppler-token-save`, which fails if hidden input is unavailable.

Check the stored token without displaying it:

```sh
( token=$(security find-generic-password -a "$USER" -s home-dc-doppler-proxmox -w) && test -n "$token" && DOPPLER_TOKEN="$token" doppler me --json )
```

The result must contain `"type": "service_token"`; `"type": "cli"` means a personal login answered instead. `task plan` and `task apply` use this **one** Keychain entry for both roles. A successful plan checks read access, **not write permission**; a read-only token fails at the Terraform write and the role then rolls back. Do not export a `DOPPLER_TOKEN` for another project before running the roles, because it takes precedence over Keychain. To remove the local item: `security delete-generic-password -a "$USER" -s home-dc-doppler-proxmox`. Revoke exposed tokens in the Doppler dashboard (Access tab).


This role manages the existing host's loopback-only Postfix service as a Gmail smart host on port 587 with mandatory STARTTLS and SASL. It places the relay password in `/etc/postfix/sasl_passwd` and its indexed map, both mode `0600`; Ansible hides the credential task and map generation with `no_log`. Postfix queues mail during temporary relay outages. It maps the local `root` sender to `automations.fs@gmail.com` for Gmail's sender policy, routes local root mail to `fabrice.semti@gmail.com`, and sets `root@pam`'s Proxmox email to that recipient. It preserves Proxmox's built-in `mail-to-root` sendmail target and `default-matcher` rather than creating a competing notification path. The already-active ZFS event daemon uses `ZED_EMAIL_ADDR="root"`, so its messages follow `/etc/aliases` through Postfix. No network interface, SSH, firewall, storage, GPU, or boot setting is changed.

TLS policy is `smtp_tls_security_level=secure` with `smtp_tls_secure_cert_match=nexthop` and the system CA bundle. This requires both a trusted CA chain and a certificate for the configured relay hostname `smtp.gmail.com` before sending SMTP authentication. `encrypt` alone would only encrypt the connection and would not validate the relay identity; do not downgrade the policy to work around certificate errors. A read-only probe on the host verified Gmail's real chain and hostname; separate negative probes with an incorrect hostname and an unrelated CA bundle both failed certificate verification. These probes do not use the Gmail app password.

## Operator rollout

1. Save the `home-dc-proxmox/prd` service token in Keychain with `task doppler-token-save`; the Ansible roles never use a personal Doppler login.
2. Preview with `ansible-playbook -i inventory site.yml --check --diff --tags mail`, then `task plan`. The protected credential file shows no diff. If the token cannot read `home-dc-proxmox/prd`, the role stops before touching host mail settings.
3. Review the full plan (including the default Terraform identity role), then run `task apply` yourself. The mail configuration itself needs no reboot.
4. Confirm `ssh pve-00 'postfix check; postconf -h relayhost smtp_tls_security_level smtp_sasl_auth_enable; pveum user list --output-format json'`. **Never print** `/etc/postfix/sasl_passwd`, its `.db`, or the app password.
5. Send a Proxmox notification test using Datacenter → Notifications → `mail-to-root` → Test, and verify delivery to `fabrice.semti@gmail.com`.
6. Independently send a local root mail with `printf 'Subject: pve-00 local mail test\n\nLocal mail path OK\n' | ssh pve-00 'sendmail root'` and verify receipt. This tests root alias and Postfix, the path ZED uses; it does not manufacture a ZFS fault.
7. If delivery fails, inspect `ssh pve-00 'mailq; journalctl -u postfix -n 60 --no-pager'` and check outbound DNS/port 587, Gmail app-password status, and sender identity. Do not dump configuration files containing credentials. `mailq` can include recipient addresses. After resolution, rerun `--check --diff --tags mail` for idempotence.

The PVE SMTP target alternative is deliberately not used: Proxmox documents that it bypasses the MTA and does not queue or retry failed deliveries. A successful PVE test alone does not prove that ZFS/system mail works; test both routes.

On the initial rollout, the Proxmox `mail-to-root` test and an independent local-root message were both accepted by Gmail (`250 2.0.0 OK`) and confirmed in the recipient inbox. One older, pre-configuration message remained queued with `alias database unavailable`; it was not resent or discarded. Review `mailq` before deleting or retrying any old queued mail.
