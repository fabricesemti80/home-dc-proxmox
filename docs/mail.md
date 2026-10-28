# Local-host alert delivery

The certificate for `pve-00.krapulax.home` is **not** changed. This internal-only name has no publicly trusted CA certificate; browser warnings remain until a CA trusted by the accessing devices or a public-domain DNS-01 name is chosen. No ACME account or DNS-provider credentials are required for this mail setup.

## 1Password credential source

The Gmail app password is stored as the concealed `credential` field of the `pve-00-gmail-alerts` item in the `iac` vault (tag: `proxmox`). The mail role reads it via `op item get` on the controller, using an **explicit service-account token** from macOS Keychain (or `OP_SERVICE_ACCOUNT_TOKEN` supplied by the controller) with desktop CLI integration disabled. Sender and recipient addresses remain non-secret role defaults. The controller needs `op` CLI v2; the role neither uses `.env` nor asks the desktop app to authorize CLI access.

Each **new** secret created for this Proxmox environment should carry the `proxmox` tag and a host-specific title. Keep other environments' existing items unchanged. Ansible hides the in-memory credential and the resulting Postfix file/diff with `no_log`. A pre-existing local `.env` is not used after this cutover; remove your own ignored copy only after verifying both the check-mode plan and mail delivery. Never print the app password or commit a local credential file.

### Service-account authentication on macOS

One `iac` service account can handle mail reads and the first Terraform credential write. The old Keychain entry `home-dc-proxmox-op` currently holds a **read-only** token; replace its value with the new read/write service-account token you created by running `task op-token-save` locally. Enter the complete new token at its hidden prompt. The task changes only your Mac's Keychain; after verifying the new account, revoke the obsolete read-only account in 1Password.

**Scope tradeoff:** the new token can read and change **every item in `iac`**; the `proxmox` tag does not restrict permissions. A dedicated vault would reduce the blast radius, but you selected the existing `iac` vault. Never send the token to chat, put it in `.env`, or pass it as a shell argument. The `security add-generic-password ... -w` terminal prompt previously truncated a token on this Mac; use `task op-token-save`, which fails if hidden input is unavailable.

Check the stored token without displaying it:

```sh
( token=$(security find-generic-password -a "$USER" -s home-dc-proxmox-op -w) && test -n "$token" && OP_SERVICE_ACCOUNT_TOKEN="$token" OP_BIOMETRIC_UNLOCK_ENABLED=false op user get --me )
```

The result must say `Type: SERVICE_ACCOUNT` and identify your new writer account; plain `op user get --me` uses your personal desktop identity. `task plan` and `task apply` now use this **one** Keychain entry for both roles; all Ansible `op` calls disable desktop CLI integration. A successful plan checks read access, **not write permission**—review the account's `iac` grants before applying. Keychain may still ask to release its item. If an unrelated shell integration calls `op`, inspect **1Password → Developer → View CLI**. Do not enable `OP_CONNECT_HOST` or `OP_CONNECT_TOKEN`, which take precedence over service-account tokens. To remove the local item: `security delete-generic-password -a "$USER" -s home-dc-proxmox-op`. Revoke exposed tokens in 1Password.


This role manages the existing host's loopback-only Postfix service as a Gmail smart host on port 587 with mandatory STARTTLS and SASL. It places the relay password in `/etc/postfix/sasl_passwd` and its indexed map, both mode `0600`; Ansible hides the credential task and map generation with `no_log`. Postfix queues mail during temporary relay outages. It maps the local `root` sender to `automations.fs@gmail.com` for Gmail's sender policy, routes local root mail to `fabrice.semti@gmail.com`, and sets `root@pam`'s Proxmox email to that recipient. It preserves Proxmox's built-in `mail-to-root` sendmail target and `default-matcher` rather than creating a competing notification path. The already-active ZFS event daemon uses `ZED_EMAIL_ADDR="root"`, so its messages follow `/etc/aliases` through Postfix. No network interface, SSH, firewall, storage, GPU, or boot setting is changed.

TLS policy is `smtp_tls_security_level=secure` with `smtp_tls_secure_cert_match=nexthop` and the system CA bundle. This requires both a trusted CA chain and a certificate for the configured relay hostname `smtp.gmail.com` before sending SMTP authentication. `encrypt` alone would only encrypt the connection and would not validate the relay identity; do not downgrade the policy to work around certificate errors. A read-only probe on the host verified Gmail's real chain and hostname; separate negative probes with an incorrect hostname and an unrelated CA bundle both failed certificate verification. These probes do not use the Gmail app password.

## Operator rollout

1. Store the `iac` service-account token in Keychain with `task op-token-save`; no desktop CLI authorization is needed by the Ansible roles.
2. Preview with `ansible-playbook -i inventory site.yml --check --diff --tags mail`, then `task plan`. The protected credential file shows no diff. If the token lacks `iac` read access, the role stops before touching host mail settings.
3. Review the full plan (including the default Terraform identity role), then run `task apply` yourself. The mail configuration itself needs no reboot.
4. Confirm `ssh pve-00 'postfix check; postconf -h relayhost smtp_tls_security_level smtp_sasl_auth_enable; pveum user list --output-format json'`. **Never print** `/etc/postfix/sasl_passwd`, its `.db`, or the app password.
5. Send a Proxmox notification test using Datacenter → Notifications → `mail-to-root` → Test, and verify delivery to `fabrice.semti@gmail.com`.
6. Independently send a local root mail with `printf 'Subject: pve-00 local mail test\n\nLocal mail path OK\n' | ssh pve-00 'sendmail root'` and verify receipt. This tests root alias and Postfix, the path ZED uses; it does not manufacture a ZFS fault.
7. If delivery fails, inspect `ssh pve-00 'mailq; journalctl -u postfix -n 60 --no-pager'` and check outbound DNS/port 587, Gmail app-password status, and sender identity. Do not dump configuration files containing credentials. `mailq` can include recipient addresses. After resolution, rerun `--check --diff --tags mail` for idempotence.

The PVE SMTP target alternative is deliberately not used: Proxmox documents that it bypasses the MTA and does not queue or retry failed deliveries. A successful PVE test alone does not prove that ZFS/system mail works; test both routes.

On the initial rollout, the Proxmox `mail-to-root` test and an independent local-root message were both accepted by Gmail (`250 2.0.0 OK`) and confirmed in the recipient inbox. One older, pre-configuration message remained queued with `alias database unavailable`; it was not resent or discarded. Review `mailq` before deleting or retrying any old queued mail.
