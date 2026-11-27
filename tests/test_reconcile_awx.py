"""Exercise new-instance provisioning and repeated reconciliation without a live AWX."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "reconcile-awx.py"
spec = importlib.util.spec_from_file_location("reconcile_awx", MODULE)
reconciler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconciler)
CONFIG = json.loads(reconciler.CONFIG.read_text())


class MemoryAWX(reconciler.AWX):
    def __init__(self, apply=True):
        self.apply = apply
        self.objects = {"organizations/": [{"id": 1, "name": "Default"}],
                        "credential_types/": [{"id": 2, "name": "Machine"}]}
        self.calls = []
        self.next_id = 3

    def request(self, path, data=None, method=None):
        self.calls.append((path, method or ("POST" if data else "GET")))
        if path.endswith("create_approval_template/"):
            node_id = int(path.split("/")[1])
            for nodes in self.objects.values():
                for node in nodes:
                    if node["id"] == node_id:
                        node["unified_job_template"] = self.next_id
                        node["summary_fields"] = {"unified_job_template": {"name": data["name"]}}
                        self.next_id += 1
                        return {}
        if path.endswith(("hosts/", "credentials/", "success_nodes/")) and data and "id" in data:
            self.objects.setdefault(path, []).append({"id": data["id"]})
            return {}
        if method == "PATCH":
            collection, identifier = path.rsplit("/", 2)[:2]
            collection += "/"
            obj = next(obj for obj in self.objects[collection] if obj["id"] == int(identifier))
            obj.update(data)
            return obj
        item = {"id": self.next_id, **data}
        self.next_id += 1
        self.objects.setdefault(path, []).append(item)
        return item

    def list(self, path):
        return self.objects.get(path.split("?")[0], [])


def run_reconcile(api):
    output = io.StringIO()
    with contextlib.redirect_stdout(output), patch.dict(os.environ, {"AWX_DOPPLER_TOKEN": "test-token"}), \
            patch.object(reconciler, "private_key", return_value="test-private-key"):
        reconciler.reconcile(api, CONFIG)
    return output.getvalue()


class ReconcileTests(unittest.TestCase):
    def test_fresh_then_repeat_without_launching_or_duplicating(self):
        api = MemoryAWX()
        first = run_reconcile(api)
        self.assertIn("create workflow approval", first)
        self.assertEqual(len(api.objects["job_templates/"]), 4)
        self.assertEqual(len(api.objects["workflow_job_templates/" + str(api.objects["workflow_job_templates/"][0]["id"]) + "/workflow_nodes/"]), 3)
        self.assertFalse(any("launch" in path for path, _ in api.calls))
        second = run_reconcile(api)
        self.assertEqual(second, "")
        self.assertFalse(any("test-token" in str(call) for call in api.calls))

    def test_adopts_existing_workflow_nodes_with_generated_identifiers(self):
        api = MemoryAWX()
        run_reconcile(api)
        path = "workflow_job_templates/" + str(api.objects["workflow_job_templates/"][0]["id"]) + "/workflow_nodes/"
        for node in api.objects[path]:
            node["identifier"] = f"generated-{node['id']}"
            if node.get("unified_job_template") and "summary_fields" not in node:
                template = next(t for t in api.objects["job_templates/"]
                                if t["id"] == node["unified_job_template"])
                node["summary_fields"] = {"unified_job_template": {"name": template["name"]}}
        self.assertEqual(run_reconcile(api), "")
        self.assertEqual(len(api.objects[path]), 3)

    def test_plan_does_not_write_or_require_secret_inputs(self):
        api = MemoryAWX()
        run_reconcile(api)
        api.apply = False
        api.calls.clear()
        with patch.dict(os.environ, {}, clear=True), patch.object(reconciler, "private_key", side_effect=AssertionError):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                reconciler.reconcile(api, CONFIG)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
