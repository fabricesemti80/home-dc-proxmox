import copy
import importlib.util
from pathlib import Path
import unittest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "hack" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load("check", "check-ceph-recovery.py")
label = load("label", "ceph-osd-key.py")


class RecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.data = [
            {"health": {"status": "HEALTH_OK"}, "osdmap": {"num_osds": 3, "num_up_osds": 3, "num_in_osds": 3}},
            {"quorum_names": ["pve-0", "pve-1", "pve-2"]},
            {"active_name": "pve-0", "available": True, "standbys": [{"name": "pve-1"}, {"name": "pve-2"}]},
            {"standbys": [{"name": "pve-0"}, {"name": "pve-1"}], "filesystems": [{"mdsmap": {
                "max_mds": 1, "in": [0], "up": {"mds_0": 42}, "failed": [], "damaged": [],
                "info": {"gid_42": {"name": "pve-2", "state": "up:active"}}}}]},
            {"pg_summary": {"num_pgs": 145, "num_pg_by_state": [{"name": "active+clean", "num": 145}]}},
        ]

    def test_complete_cluster(self):
        self.assertTrue(check.healthy(*self.data))

    def test_health_ok_alone_does_not_hide_missing_standbys(self):
        for index in (2, 3):
            data = copy.deepcopy(self.data)
            data[index]["standbys"].pop()
            self.assertFalse(check.healthy(*data))

    def test_rejects_incomplete_quorum_osds_and_recovery(self):
        for index, field, value in [(0, "health", {"status": "HEALTH_WARN"}),
                                    (0, "osdmap", {"num_osds": 3, "num_up_osds": 2, "num_in_osds": 3}),
                                    (1, "quorum_names", ["pve-0", "pve-2"]),
                                    (4, "pg_summary", {"num_pgs": 145, "num_pg_by_state": [
                                        {"name": "active+clean", "num": 144}, {"name": "peering", "num": 1}]})]:
            data = copy.deepcopy(self.data)
            data[index][field] = value
            self.assertFalse(check.healthy(*data))

    def test_rejects_damaged_filesystem(self):
        self.data[3]["filesystems"][0]["mdsmap"]["damaged"] = [0]
        self.assertFalse(check.healthy(*self.data))

    def test_label_identity_guard(self):
        valid = {"device": {"ceph_fsid": label.CLUSTER_FSID, "osd_uuid": "expected"}}
        self.assertEqual(label.validate(valid, "expected"), valid["device"])
        for labels, uuid in [(valid, "wrong"), ({}, "expected"),
                             ({"device": {"ceph_fsid": "other", "osd_uuid": "expected"}}, "expected")]:
            with self.assertRaises(ValueError):
                label.validate(labels, uuid)


if __name__ == "__main__":
    unittest.main()
