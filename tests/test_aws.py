"""Tests for monitoring/gather/aws.py — AwsCloud.get_metadata()."""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitoring.gather import aws
from monitoring.gather.aws import AwsCloud

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_IDENTITY_DOC = {
    "instanceId":       "i-0abc1234567890def",
    "instanceType":     "t3.medium",
    "region":           "us-east-1",
    "availabilityZone": "us-east-1b",
    "accountId":        "123456789012",
    "imageId":          "ami-0deadbeef",
    "architecture":     "x86_64",
    "privateIp":        "10.0.1.42",
}

_IDENTITY_DOC_M5 = dict(_IDENTITY_DOC, instanceType="m5.xlarge",
                         instanceId="i-0m5instance0000000")

_LIFECYCLE_ONDEMAND = "on-demand"
_LIFECYCLE_SPOT     = "spot"


def _make_cloud(imds_reachable=True, token="fake-token",
                identity=_IDENTITY_DOC, lifecycle=_LIFECYCLE_ONDEMAND,
                boto3_credits=None, boto3_available=True):
    """Return the result of AwsCloud().metadata with all IMDS calls mocked."""
    identity_json = json.dumps(identity) if identity is not None else None

    with patch("monitoring.gather.util.imds_reachable", return_value=imds_reachable), \
         patch("monitoring.gather.util.imds_put", return_value=token), \
         patch("monitoring.gather.util.imds_get", side_effect=[identity_json, lifecycle]), \
         patch("time.time", return_value=9000.0), \
         _mock_boto3(boto3_credits, available=boto3_available):
        n = AwsCloud.__new__(AwsCloud)
        return n.get_metadata()


def _mock_boto3(credits_result, available=True):
    """Context manager that injects (or removes) a mock boto3 into sys.modules."""
    if not available:
        # Simulate boto3 not installed: ensure it raises ImportError
        return patch.dict(sys.modules, {'boto3': None})

    mock_boto3 = MagicMock()
    if credits_result is not None:
        specs = [{"InstanceId": "i-x", "CpuCredits": credits_result}]
    else:
        specs = []
    mock_boto3.client.return_value.describe_instance_credit_specifications.return_value = {
        "InstanceCreditSpecifications": specs,
    }
    return patch.dict(sys.modules, {'boto3': mock_boto3})


# ---------------------------------------------------------------------------
# Not on EC2 — IMDS not reachable
# ---------------------------------------------------------------------------

class TestNotOnEc2(unittest.TestCase):
    """get_metadata() returns False when IMDS is not reachable."""

    def test_returns_false_when_imds_unreachable(self):
        result = _make_cloud(imds_reachable=False)
        self.assertIs(result, False)

    def test_returns_false_when_token_fetch_fails(self):
        # IMDS reachable but token PUT fails (e.g. GCP or Azure at same IP).
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value=None):
            n = AwsCloud.__new__(AwsCloud)
            self.assertIs(n.get_metadata(), False)

    def test_returns_false_when_identity_doc_missing(self):
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", return_value=None):
            n = AwsCloud.__new__(AwsCloud)
            self.assertIs(n.get_metadata(), False)

    def test_returns_false_when_identity_doc_malformed(self):
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=["not-json", "on-demand"]):
            n = AwsCloud.__new__(AwsCloud)
            self.assertIs(n.get_metadata(), False)


# ---------------------------------------------------------------------------
# On EC2 — basic structure
# ---------------------------------------------------------------------------

class TestOnEc2Structure(unittest.TestCase):
    """get_metadata() returns a dict with expected keys when on EC2."""

    def setUp(self):
        self.result = _make_cloud()

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_provider_is_aws(self):
        self.assertEqual(self.result["provider"], "aws")

    def test_instance_id(self):
        self.assertEqual(self.result["instance_id"], "i-0abc1234567890def")

    def test_instance_type(self):
        self.assertEqual(self.result["instance_type"], "t3.medium")

    def test_region(self):
        self.assertEqual(self.result["region"], "us-east-1")

    def test_availability_zone(self):
        self.assertEqual(self.result["availability_zone"], "us-east-1b")

    def test_account_id(self):
        self.assertEqual(self.result["account_id"], "123456789012")

    def test_ami_id(self):
        self.assertEqual(self.result["ami_id"], "ami-0deadbeef")

    def test_architecture(self):
        self.assertEqual(self.result["architecture"], "x86_64")

    def test_private_ip(self):
        self.assertEqual(self.result["private_ip"], "10.0.1.42")

    def test_time_key(self):
        self.assertEqual(self.result["_time"], 9000.0)

    def test_instance_life_cycle_ondemand(self):
        self.assertEqual(self.result["instance_life_cycle"], "on-demand")


# ---------------------------------------------------------------------------
# Life-cycle variants
# ---------------------------------------------------------------------------

class TestLifecycle(unittest.TestCase):
    """instance_life_cycle reflects the IMDS value."""

    def test_spot(self):
        result = _make_cloud(lifecycle=_LIFECYCLE_SPOT)
        self.assertEqual(result["instance_life_cycle"], "spot")

    def test_lifecycle_stripped(self):
        # IMDS may include trailing whitespace/newline.
        result = _make_cloud(lifecycle="on-demand\n")
        self.assertEqual(result["instance_life_cycle"], "on-demand")

    def test_lifecycle_unknown_when_imds_returns_none(self):
        # identity doc OK but lifecycle call returns None.
        identity_json = json.dumps(_IDENTITY_DOC)
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=[identity_json, None]), \
             patch("time.time", return_value=9000.0), \
             _mock_boto3(None):
            n = AwsCloud.__new__(AwsCloud)
            result = n.get_metadata()
        self.assertEqual(result["instance_life_cycle"], "unknown")


# ---------------------------------------------------------------------------
# T-series burst credits
# ---------------------------------------------------------------------------

class TestBurstCapable(unittest.TestCase):
    """burst_capable and burst fields for T-series vs non-T-series."""

    def test_t3_is_burst_capable(self):
        result = _make_cloud()  # t3.medium
        self.assertTrue(result["burst_capable"])

    def test_non_t_series_not_burst_capable(self):
        result = _make_cloud(identity=_IDENTITY_DOC_M5)
        self.assertFalse(result["burst_capable"])

    def test_non_t_series_has_no_burst_key(self):
        result = _make_cloud(identity=_IDENTITY_DOC_M5)
        self.assertNotIn("burst", result)

    def test_t3_burst_key_present_when_boto3_returns_credits(self):
        result = _make_cloud(boto3_credits="standard")
        self.assertIn("burst", result)
        self.assertEqual(result["burst"]["cpu_credits"], "standard")

    def test_t3_unlimited_credits(self):
        result = _make_cloud(boto3_credits="unlimited")
        self.assertEqual(result["burst"]["cpu_credits"], "unlimited")

    def test_t3_no_burst_key_when_boto3_unavailable(self):
        result = _make_cloud(boto3_available=False)
        self.assertTrue(result["burst_capable"])
        self.assertNotIn("burst", result)

    def test_t3_no_burst_key_when_api_returns_empty(self):
        # boto3 available but describe_instance_credit_specifications returns nothing.
        result = _make_cloud(boto3_credits=None, boto3_available=True)
        self.assertNotIn("burst", result)

    def test_all_t_series_prefixes_are_burst_capable(self):
        prefixes = ["t1.", "t2.", "t3.", "t3a.", "t4g."]
        for prefix in prefixes:
            identity = dict(_IDENTITY_DOC, instanceType=f"{prefix}micro")
            result = _make_cloud(identity=identity)
            self.assertTrue(result["burst_capable"], f"{prefix}micro should be burst_capable")


# ---------------------------------------------------------------------------
# AwsCloud.__init__
# ---------------------------------------------------------------------------

class TestAwsCloudInit(unittest.TestCase):
    """__init__() calls get_metadata() and stores result in self.metadata."""

    def test_init_populates_metadata(self):
        fake = {"provider": "aws", "_time": 1.0}
        n = AwsCloud.__new__(AwsCloud)
        with patch.object(n, "get_metadata", return_value=fake):
            n.__init__()
        self.assertEqual(n.metadata, fake)

    def test_init_stores_false_when_not_on_ec2(self):
        n = AwsCloud.__new__(AwsCloud)
        with patch.object(n, "get_metadata", return_value=False):
            n.__init__()
        self.assertIs(n.metadata, False)


if __name__ == "__main__":
    unittest.main()
