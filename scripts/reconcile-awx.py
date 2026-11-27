#!/usr/bin/env python3
"""Reconcile this repository's AWX objects; never launch jobs or print secrets."""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "awx" / "config.json"


class AWX:
    def __init__(self, url, username, password, apply):
        if not url.startswith(("http://", "https://")):
            raise ValueError("AWX_URL must be an HTTP(S) URL")
        self.url = url.rstrip("/") + "/api/v2/"
        self.auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        self.apply = apply

    def request(self, path, data=None, method=None):
        body = None if data is None else json.dumps(data).encode()
        request = Request(self.url + path.lstrip("/"), body, method=method or ("POST" if body else "GET"),
                          headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            # Never print API responses: validation failures can echo credential inputs.
            raise RuntimeError(f"AWX {request.method} {path}: HTTP {error.code}") from None

    def list(self, path):
        results = []
        while path:
            page = self.request(path)
            results.extend(page["results"])
            path = page["next"]
            if path and path.startswith(self.url):
                path = path[len(self.url):]
        return results

    def find(self, collection, name):
        matches = [item for item in self.list(collection + "?page_size=200") if item["name"] == name]
        if len(matches) > 1:
            raise RuntimeError(f"ambiguous {collection}: {name}")
        return matches[0] if matches else None

    def ensure(self, collection, name, fields, *, secret=False):
        current = self.find(collection, name)
        if current is None:
            print(f"create {collection}: {name}")
            if not self.apply:
                return None
            return self.request(collection, {"name": name, **fields})
        if secret:
            # AWX masks stored inputs. Retain them unless explicitly rotated.
            fields = {k: v for k, v in fields.items() if k != "inputs"}
        def same(key, value):
            if key in ("variables", "extra_vars"):
                return yaml.safe_load(current.get(key) or "{}") == json.loads(value)
            return current.get(key) == value
        changed = {k: v for k, v in fields.items() if not same(k, v)}
        if changed:
            print(f"update {collection}: {name} ({', '.join(changed)})")
            if self.apply:
                return self.request(f"{collection}{current['id']}/", changed, "PATCH")
        return current

    def association(self, path, target):
        if target not in [item["id"] for item in self.list(path + "?page_size=200")]:
            print(f"associate {path} -> {target}")
            if self.apply:
                self.request(path, {"id": target})


def required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def doppler_secret(name, project, config):
    result = subprocess.run(["doppler", "secrets", "get", name,
                             "--plain", "--project", project, "--config", config],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"Cannot read {name} from Doppler")
    return result.stdout.strip()


def private_key():
    return os.environ.get("AWX_PVE_SSH_PRIVATE_KEY") or (
        doppler_secret("AWX_PVE_SSH_PRIVATE_KEY", "home-dc-awx", "prd") + "\n")


def reconcile(api, cfg, rotate=False):
    org = api.find("organizations/", cfg["organization"])
    if not org:
        raise RuntimeError("Create the AWX Default organization first")
    oid = org["id"]
    inv = api.ensure("inventories/", cfg["inventory"], {"organization": oid})
    ee = api.ensure("execution_environments/", cfg["execution_environment"]["name"],
                    {**{k: v for k, v in cfg["execution_environment"].items() if k != "name"}, "organization": oid})
    project = api.ensure("projects/", cfg["project"]["name"],
                         {**{k: v for k, v in cfg["project"].items() if k != "name"}, "organization": oid})
    kind = api.ensure("credential_types/", cfg["doppler_credential_type"], {
        "kind": "cloud", "inputs": {"fields": [{"id": "token", "type": "string", "label": "Service token", "secret": True}], "required": ["token"]},
        "injectors": {"env": {"DOPPLER_TOKEN": "{{ token }}"}}})
    machine_type = api.find("credential_types/", "Machine")
    if not machine_type:
        raise RuntimeError("AWX Machine credential type not found")
    # Credential values are only needed on creation or explicit rotation.
    machine_current = api.find("credentials/", cfg["machine_credential"])
    token_current = api.find("credentials/", cfg["doppler_credential"])
    machine = api.ensure("credentials/", cfg["machine_credential"], {
        "organization": oid, "credential_type": machine_type["id"],
        **({"inputs": {"username": "root", "ssh_key_data": private_key()}}
           if api.apply and (not machine_current or rotate) else {})}, secret=True)
    doppler = api.ensure("credentials/", cfg["doppler_credential"], {
        "organization": oid, "credential_type": kind["id"] if kind else 0,
        **({"inputs": {"token": required("AWX_DOPPLER_TOKEN")}}
           if api.apply and (not token_current or rotate) else {})}, secret=True)
    if rotate and api.apply:
        for obj, inputs in ((machine, {"username": "root", "ssh_key_data": private_key()}),
                            (doppler, {"token": required("AWX_DOPPLER_TOKEN")})):
            api.request(f"credentials/{obj['id']}/", {"inputs": inputs}, "PATCH")
            print(f"rotate credentials/{obj['id']}/")
    if not api.apply and any(item is None for item in (inv, ee, project, kind, machine, doppler)):
        print("Missing dependencies; apply before planning dependent objects")
        return
    group = api.ensure("groups/", cfg["group"], {"inventory": inv["id"]})
    host = api.ensure("hosts/", cfg["host"], {"inventory": inv["id"],
                       "variables": json.dumps(cfg["host_variables"], sort_keys=True)})
    api.association(f"groups/{group['id']}/hosts/", host["id"])
    templates = {}
    for entry in cfg["templates"]:
        fields = {"organization": oid, "inventory": inv["id"], "project": project["id"],
                  "execution_environment": ee["id"], "playbook": "site.yml", "limit": cfg["host"],
                  "forks": 1, "diff_mode": True, "become_enabled": False,
                  "extra_vars": json.dumps(cfg["extra_vars"], sort_keys=True),
                  "job_tags": "", "skip_tags": "", **{k: v for k, v in entry.items() if k != "name"}}
        job = api.ensure("job_templates/", entry["name"], fields)
        for cred in (machine, doppler):
            api.association(f"job_templates/{job['id']}/credentials/", cred["id"])
        templates[entry["name"]] = job
    workflow = api.ensure("workflow_job_templates/", cfg["workflow"], {"organization": oid,
                           "inventory": inv["id"], "limit": cfg["host"]})
    nodes_path = f"workflow_job_templates/{workflow['id']}/workflow_nodes/"
    def node(identifier, template=None):
        matches = [n for n in api.list(nodes_path + "?page_size=200") if
                   n["identifier"] == identifier or
                   n.get("summary_fields", {}).get("unified_job_template", {}).get("name") ==
                   (template["name"] if template else cfg["approval"])]
        if len(matches) > 1:
            raise RuntimeError(f"ambiguous workflow node: {identifier}")
        if matches:
            existing = matches[0]
            if template and existing.get("unified_job_template") != template["id"]:
                raise RuntimeError(f"workflow node {identifier} points to a different template")
            return existing
        print(f"create workflow node: {identifier}")
        if api.apply:
            return api.request(nodes_path, {"identifier": identifier,
                               **({"unified_job_template": template["id"]} if template else {})})
        return None
    check = node("updates-check", templates["pve-00 updates (check)"])
    approval = node("approval")
    if approval and not approval.get("unified_job_template"):
        print("create workflow approval")
        if api.apply:
            api.request(f"workflow_job_template_nodes/{approval['id']}/create_approval_template/",
                        {"name": cfg["approval"], "timeout": 3600,
                         "description": "Review the updates check; real dist-upgrade on pve-00; reboot locally."})
    apply = node("updates-apply", templates["pve-00 updates (APPLY)"])
    if check and approval:
        api.association(f"workflow_job_template_nodes/{check['id']}/success_nodes/", approval["id"])
    if approval and apply:
        api.association(f"workflow_job_template_nodes/{approval['id']}/success_nodes/", apply["id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write drift to AWX (default: read-only plan)")
    parser.add_argument("--rotate", action="store_true", help="replace credential inputs; requires --apply")
    args = parser.parse_args()
    if args.rotate and not args.apply:
        parser.error("--rotate requires --apply")
    cfg = json.loads(CONFIG.read_text())
    reconcile(AWX(os.getenv("AWX_URL", "http://awx.krapulax.home"),
                  os.getenv("AWX_USERNAME", "admin"),
                  os.environ.get("AWX_ADMIN_PASSWORD") or
                  doppler_secret("AWX_ADMIN_PASSWORD", "home-dc-kubernetes", "apps"),
                  args.apply), cfg, args.rotate)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
