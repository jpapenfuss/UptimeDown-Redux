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

_IAM_INFO_DOC = json.dumps({
    "Code":               "Success",
    "LastUpdated":        "2024-01-01T00:00:00Z",
    "InstanceProfileArn": "arn:aws:iam::123456789012:instance-profile/MyProfile",
    "InstanceProfileId":  "AIPA000000000000EXAMPLE",
})

_MAC = "0a:1b:2c:3d:4e:5f"
_MAC_TRAILING = _MAC + "/"

# Per-MAC IMDS sub-path responses used by network interface tests.
_MAC_DATA = {
    "interface-id":      "eni-0abc1234",
    "device-number":     "0",
    "subnet-id":         "subnet-abc123",
    "vpc-id":            "vpc-deadbeef",
    "local-ipv4s":       "10.0.1.42",
    "public-ipv4s":      "54.1.2.3",
    "security-group-ids": "sg-aaa\nsg-bbb",
}


def _make_imds_get(identity_json, lifecycle, public_ip=None, iam_info=None,
                   tags_raw=None, macs_raw="", mac_data=None,
                   maintenance_scheduled_raw="[]", maintenance_history_raw="[]",
                   spot_action_raw=None, rebalance_raw=None):
    """Return a callable suitable for patching util.imds_get.

    Routes by IMDS path so new calls added to get_metadata() don't break
    existing tests (unlike a positional side_effect list).
    """
    mac_data = mac_data or {}

    def _get(ip, path, headers=None, timeout=2.0):
        if path == aws._IDENTITY_PATH:              return identity_json
        if path == aws._LIFECYCLE_PATH:             return lifecycle
        if path == aws._PUBLIC_IP_PATH:             return public_ip
        if path == aws._IAM_INFO_PATH:              return iam_info
        if path == aws._TAGS_PATH:                  return tags_raw
        if path == aws._MACS_PATH:                  return macs_raw
        if path == aws._MAINTENANCE_SCHEDULED_PATH: return maintenance_scheduled_raw
        if path == aws._MAINTENANCE_HISTORY_PATH:   return maintenance_history_raw
        if path == aws._SPOT_ACTION_PATH:           return spot_action_raw
        if path == aws._REBALANCE_PATH:             return rebalance_raw
        # Per-tag paths: /latest/meta-data/tags/instance/<key>
        if path.startswith(aws._TAGS_PATH + "/"):
            return tags_raw  # not used for per-key; handled in per-tag tests
        # Per-MAC sub-paths: /latest/meta-data/network/interfaces/macs/<mac>/<field>
        if path.startswith(aws._MACS_PATH):
            rest = path[len(aws._MACS_PATH):]   # "<mac>/<field>"
            parts = rest.split("/", 1)
            if len(parts) == 2:
                _, field = parts
                return mac_data.get(field)
        return None

    return _get


def _make_cloud(imds_reachable=True, token="fake-token",
                identity=_IDENTITY_DOC, lifecycle=_LIFECYCLE_ONDEMAND,
                public_ip=None, iam_info=None,
                tags_raw=None, macs_raw="", mac_data=None,
                maintenance_scheduled_raw="[]", maintenance_history_raw="[]",
                spot_action_raw=None, rebalance_raw=None,
                boto3_credits=None, boto3_available=True,
                boto3_tags=None, boto3_volumes=None, boto3_asg=None,
                boto3_instance_status=None):
    """Return the result of AwsCloud().metadata with all external calls mocked."""
    identity_json = json.dumps(identity) if identity is not None else None

    imds_get_fn = _make_imds_get(
        identity_json, lifecycle,
        public_ip=public_ip, iam_info=iam_info,
        tags_raw=tags_raw, macs_raw=macs_raw, mac_data=mac_data,
        maintenance_scheduled_raw=maintenance_scheduled_raw,
        maintenance_history_raw=maintenance_history_raw,
        spot_action_raw=spot_action_raw,
        rebalance_raw=rebalance_raw,
    )

    with patch("monitoring.gather.util.imds_reachable", return_value=imds_reachable), \
         patch("monitoring.gather.util.imds_put", return_value=token), \
         patch("monitoring.gather.util.imds_get", side_effect=imds_get_fn), \
         patch("time.time", return_value=9000.0), \
         _mock_boto3(boto3_credits, available=boto3_available,
                     tags=boto3_tags, volumes=boto3_volumes, asg=boto3_asg,
                     instance_status=boto3_instance_status):
        n = AwsCloud.__new__(AwsCloud)
        return n.get_metadata()


def _mock_boto3(credits_result, available=True, tags=None, volumes=None, asg=None,
                instance_status=None):
    """Context manager that injects (or removes) a mock boto3 into sys.modules."""
    if not available:
        return patch.dict(sys.modules, {'boto3': None})

    mock_boto3 = MagicMock()
    ec2_client = mock_boto3.client.return_value

    # describe_instance_credit_specifications
    if credits_result is not None:
        specs = [{"InstanceId": "i-x", "CpuCredits": credits_result}]
    else:
        specs = []
    ec2_client.describe_instance_credit_specifications.return_value = {
        "InstanceCreditSpecifications": specs,
    }

    # describe_tags (boto3 tag fallback)
    tag_list = [{"Key": k, "Value": v} for k, v in (tags or {}).items()]
    ec2_client.describe_tags.return_value = {"Tags": tag_list}

    # describe_volumes
    ec2_client.describe_volumes.return_value = {"Volumes": volumes or []}

    # describe_auto_scaling_instances
    asg_instances = [{"AutoScalingGroupName": asg}] if asg else []
    ec2_client.describe_auto_scaling_instances.return_value = {
        "AutoScalingInstances": asg_instances,
    }

    # describe_instance_status
    if instance_status is not None:
        ec2_client.describe_instance_status.return_value = {
            "InstanceStatuses": [instance_status],
        }
    else:
        ec2_client.describe_instance_status.return_value = {
            "InstanceStatuses": [],
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
        imds_fn = _make_imds_get(None, None)
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=imds_fn):
            n = AwsCloud.__new__(AwsCloud)
            self.assertIs(n.get_metadata(), False)

    def test_returns_false_when_identity_doc_malformed(self):
        imds_fn = _make_imds_get("not-json", _LIFECYCLE_ONDEMAND)
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=imds_fn):
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

    def test_time_key_absent(self):
        self.assertNotIn("_time", self.result)

    def test_instance_life_cycle_ondemand(self):
        self.assertEqual(self.result["instance_life_cycle"], "on-demand")

    def test_network_interfaces_key_present(self):
        self.assertIn("network_interfaces", self.result)

    def test_tags_key_present(self):
        self.assertIn("tags", self.result)


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
        imds_fn = _make_imds_get(json.dumps(_IDENTITY_DOC), None)
        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=imds_fn), \
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
# Public IP
# ---------------------------------------------------------------------------

class TestPublicIp(unittest.TestCase):
    """public_ip is populated from IMDS /latest/meta-data/public-ipv4."""

    def test_public_ip_set_when_available(self):
        result = _make_cloud(public_ip="54.1.2.3")
        self.assertEqual(result["public_ip"], "54.1.2.3")

    def test_public_ip_stripped(self):
        result = _make_cloud(public_ip="54.1.2.3\n")
        self.assertEqual(result["public_ip"], "54.1.2.3")

    def test_public_ip_none_when_imds_returns_nothing(self):
        result = _make_cloud(public_ip=None)
        self.assertIsNone(result["public_ip"])


# ---------------------------------------------------------------------------
# IAM profile
# ---------------------------------------------------------------------------

class TestIamProfile(unittest.TestCase):
    """iam_profile is parsed from IMDS /latest/meta-data/iam/info."""

    def test_iam_profile_parsed(self):
        result = _make_cloud(iam_info=_IAM_INFO_DOC)
        self.assertEqual(
            result["iam_profile"],
            "arn:aws:iam::123456789012:instance-profile/MyProfile",
        )

    def test_iam_profile_none_when_not_attached(self):
        result = _make_cloud(iam_info=None)
        self.assertIsNone(result["iam_profile"])

    def test_iam_profile_none_when_json_malformed(self):
        result = _make_cloud(iam_info="not-json")
        self.assertIsNone(result["iam_profile"])

    def test_iam_profile_none_when_field_absent(self):
        result = _make_cloud(iam_info=json.dumps({"Code": "Success"}))
        self.assertIsNone(result["iam_profile"])


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags(unittest.TestCase):
    """tags dict is populated from IMDS or boto3 fallback."""

    def test_tags_from_imds(self):
        # Patch imds_get so per-tag calls return values.
        identity_json = json.dumps(_IDENTITY_DOC)

        def _get(ip, path, headers=None, timeout=2.0):
            if path == aws._IDENTITY_PATH:      return identity_json
            if path == aws._LIFECYCLE_PATH:     return _LIFECYCLE_ONDEMAND
            if path == aws._PUBLIC_IP_PATH:     return None
            if path == aws._IAM_INFO_PATH:      return None
            if path == aws._TAGS_PATH:          return "Name\nEnv"
            if path == aws._TAGS_PATH + "/Name": return "my-server"
            if path == aws._TAGS_PATH + "/Env":  return "prod"
            if path == aws._MACS_PATH:          return ""
            return None

        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=_get), \
             patch("time.time", return_value=9000.0), \
             _mock_boto3(None):
            n = AwsCloud.__new__(AwsCloud)
            result = n.get_metadata()

        self.assertEqual(result["tags"], {"Name": "my-server", "Env": "prod"})

    def test_tags_empty_dict_when_imds_returns_empty_string(self):
        # IMDS tags enabled but instance has no tags → empty string.
        identity_json = json.dumps(_IDENTITY_DOC)

        def _get(ip, path, headers=None, timeout=2.0):
            if path == aws._IDENTITY_PATH:  return identity_json
            if path == aws._LIFECYCLE_PATH: return _LIFECYCLE_ONDEMAND
            if path == aws._TAGS_PATH:      return ""   # enabled but no tags
            if path == aws._MACS_PATH:      return ""
            return None

        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=_get), \
             patch("time.time", return_value=9000.0), \
             _mock_boto3(None):
            n = AwsCloud.__new__(AwsCloud)
            result = n.get_metadata()

        self.assertEqual(result["tags"], {})

    def test_tags_boto3_fallback_when_imds_returns_none(self):
        # IMDS tags endpoint returns None → fall back to boto3.
        result = _make_cloud(
            tags_raw=None,
            boto3_tags={"Name": "from-boto3", "Env": "staging"},
        )
        self.assertEqual(result["tags"], {"Name": "from-boto3", "Env": "staging"})

    def test_tags_none_when_both_fail(self):
        # IMDS returns None and boto3 describe_tags raises an exception.
        identity_json = json.dumps(_IDENTITY_DOC)

        def _get(ip, path, headers=None, timeout=2.0):
            if path == aws._IDENTITY_PATH:  return identity_json
            if path == aws._LIFECYCLE_PATH: return _LIFECYCLE_ONDEMAND
            if path == aws._TAGS_PATH:      return None   # IMDS tags unavailable
            if path == aws._MACS_PATH:      return ""
            return None

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value.describe_tags.side_effect = Exception("API error")
        mock_boto3.client.return_value.describe_instance_credit_specifications.return_value = {
            "InstanceCreditSpecifications": []
        }
        mock_boto3.client.return_value.describe_volumes.return_value = {"Volumes": []}
        mock_boto3.client.return_value.describe_auto_scaling_instances.return_value = {
            "AutoScalingInstances": []
        }

        with patch("monitoring.gather.util.imds_reachable", return_value=True), \
             patch("monitoring.gather.util.imds_put", return_value="token"), \
             patch("monitoring.gather.util.imds_get", side_effect=_get), \
             patch("time.time", return_value=9000.0), \
             patch.dict(sys.modules, {'boto3': mock_boto3}):
            n = AwsCloud.__new__(AwsCloud)
            result = n.get_metadata()

        self.assertIsNone(result["tags"])

    def test_tags_none_when_boto3_unavailable_and_imds_fails(self):
        result = _make_cloud(tags_raw=None, boto3_available=False)
        self.assertIsNone(result["tags"])


# ---------------------------------------------------------------------------
# Network interfaces
# ---------------------------------------------------------------------------

class TestNetworkInterfaces(unittest.TestCase):
    """network_interfaces list is populated from IMDS per-MAC paths."""

    def test_empty_list_when_no_macs(self):
        result = _make_cloud(macs_raw="")
        self.assertEqual(result["network_interfaces"], [])

    def test_single_interface_parsed(self):
        result = _make_cloud(
            macs_raw=_MAC_TRAILING,
            mac_data=_MAC_DATA,
        )
        nics = result["network_interfaces"]
        self.assertEqual(len(nics), 1)
        nic = nics[0]
        self.assertEqual(nic["mac"],                _MAC)
        self.assertEqual(nic["interface_id"],       "eni-0abc1234")
        self.assertEqual(nic["device_number"],      0)
        self.assertEqual(nic["subnet_id"],          "subnet-abc123")
        self.assertEqual(nic["vpc_id"],             "vpc-deadbeef")
        self.assertEqual(nic["private_ips"],        ["10.0.1.42"])
        self.assertEqual(nic["public_ips"],         ["54.1.2.3"])
        self.assertEqual(nic["security_group_ids"], ["sg-aaa", "sg-bbb"])

    def test_multiple_private_ips(self):
        mac_data = dict(_MAC_DATA, **{"local-ipv4s": "10.0.1.42\n10.0.1.43"})
        result = _make_cloud(macs_raw=_MAC_TRAILING, mac_data=mac_data)
        nic = result["network_interfaces"][0]
        self.assertEqual(nic["private_ips"], ["10.0.1.42", "10.0.1.43"])

    def test_no_public_ip_on_private_instance(self):
        mac_data = dict(_MAC_DATA, **{"public-ipv4s": None})
        result = _make_cloud(macs_raw=_MAC_TRAILING, mac_data=mac_data)
        nic = result["network_interfaces"][0]
        self.assertEqual(nic["public_ips"], [])

    def test_device_number_is_int(self):
        result = _make_cloud(macs_raw=_MAC_TRAILING, mac_data=_MAC_DATA)
        self.assertIsInstance(result["network_interfaces"][0]["device_number"], int)


# ---------------------------------------------------------------------------
# Attached volumes (boto3)
# ---------------------------------------------------------------------------

class TestVolumes(unittest.TestCase):
    """volumes list is populated from boto3 describe_volumes."""

    _VOL = {
        "VolumeId":    "vol-0abc1234",
        "VolumeType":  "gp3",
        "Size":        100,
        "Encrypted":   True,
        "Iops":        3000,
        "Attachments": [{"InstanceId": "i-0abc1234567890def", "Device": "/dev/xvda"}],
    }

    def test_volumes_present_when_boto3_available(self):
        result = _make_cloud(boto3_volumes=[self._VOL])
        self.assertIn("volumes", result)

    def test_volume_fields(self):
        result = _make_cloud(boto3_volumes=[self._VOL])
        vol = result["volumes"][0]
        self.assertEqual(vol["volume_id"],   "vol-0abc1234")
        self.assertEqual(vol["device"],      "/dev/xvda")
        self.assertEqual(vol["size_gb"],     100)
        self.assertEqual(vol["volume_type"], "gp3")
        self.assertTrue(vol["encrypted"])
        self.assertEqual(vol["iops"],        3000)

    def test_throughput_included_when_present(self):
        vol_with_tp = dict(self._VOL, Throughput=125)
        result = _make_cloud(boto3_volumes=[vol_with_tp])
        self.assertEqual(result["volumes"][0]["throughput_mbps"], 125)

    def test_volumes_absent_when_boto3_unavailable(self):
        result = _make_cloud(boto3_available=False)
        self.assertNotIn("volumes", result)

    def test_empty_volumes_list(self):
        result = _make_cloud(boto3_volumes=[])
        self.assertEqual(result["volumes"], [])


# ---------------------------------------------------------------------------
# Auto Scaling group (boto3)
# ---------------------------------------------------------------------------

class TestAutoscalingGroup(unittest.TestCase):
    """autoscaling_group is populated from boto3 describe_auto_scaling_instances."""

    def test_asg_name_set_when_in_asg(self):
        result = _make_cloud(boto3_asg="my-asg")
        self.assertEqual(result["autoscaling_group"], "my-asg")

    def test_asg_absent_when_not_in_asg(self):
        result = _make_cloud(boto3_asg=None)
        self.assertNotIn("autoscaling_group", result)

    def test_asg_absent_when_boto3_unavailable(self):
        result = _make_cloud(boto3_available=False)
        self.assertNotIn("autoscaling_group", result)


# ---------------------------------------------------------------------------
# Maintenance events
# ---------------------------------------------------------------------------

_EVENT_ACTIVE = {
    "EventId":     "instance-event-0d59937288b749b32",
    "Code":        "system-reboot",
    "Description": "scheduled reboot",
    "State":       "active",
    "NotBefore":   "21 Jan 2019 09:00:43 GMT",
    "NotAfter":    "21 Jan 2019 09:17:23 GMT",
}
_EVENT_COMPLETED = dict(_EVENT_ACTIVE,
    Description="[Completed] scheduled reboot",
    State="completed",
)


class TestMaintenanceEvents(unittest.TestCase):
    """maintenance_events is always present with scheduled and history sub-lists."""

    def test_key_always_present(self):
        result = _make_cloud()
        self.assertIn("maintenance_events", result)

    def test_empty_when_no_events(self):
        result = _make_cloud()
        self.assertEqual(result["maintenance_events"]["scheduled"], [])
        self.assertEqual(result["maintenance_events"]["history"], [])

    def test_scheduled_event_parsed(self):
        raw = json.dumps([_EVENT_ACTIVE])
        result = _make_cloud(maintenance_scheduled_raw=raw)
        events = result["maintenance_events"]["scheduled"]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["event_id"],    "instance-event-0d59937288b749b32")
        self.assertEqual(ev["code"],        "system-reboot")
        self.assertEqual(ev["description"], "scheduled reboot")
        self.assertEqual(ev["state"],       "active")
        self.assertEqual(ev["not_before"],  "21 Jan 2019 09:00:43 GMT")
        self.assertEqual(ev["not_after"],   "21 Jan 2019 09:17:23 GMT")

    def test_history_event_parsed(self):
        raw = json.dumps([_EVENT_COMPLETED])
        result = _make_cloud(maintenance_history_raw=raw)
        ev = result["maintenance_events"]["history"][0]
        self.assertEqual(ev["state"],       "completed")
        self.assertEqual(ev["description"], "[Completed] scheduled reboot")

    def test_multiple_scheduled_events(self):
        ev2 = dict(_EVENT_ACTIVE, EventId="instance-event-aabbccdd", Code="instance-retirement")
        raw = json.dumps([_EVENT_ACTIVE, ev2])
        result = _make_cloud(maintenance_scheduled_raw=raw)
        self.assertEqual(len(result["maintenance_events"]["scheduled"]), 2)
        self.assertEqual(result["maintenance_events"]["scheduled"][1]["code"], "instance-retirement")

    def test_malformed_json_returns_empty(self):
        result = _make_cloud(maintenance_scheduled_raw="not-json")
        self.assertEqual(result["maintenance_events"]["scheduled"], [])

    def test_imds_returns_none_gives_empty(self):
        # If IMDS call itself fails (returns None), treat as empty list.
        result = _make_cloud(maintenance_scheduled_raw=None,
                             maintenance_history_raw=None)
        self.assertEqual(result["maintenance_events"]["scheduled"], [])
        self.assertEqual(result["maintenance_events"]["history"], [])


# ---------------------------------------------------------------------------
# Spot action
# ---------------------------------------------------------------------------

class TestSpotAction(unittest.TestCase):
    """spot_action is None normally; populated when an interruption notice is issued."""

    def test_none_when_no_notice(self):
        result = _make_cloud()
        self.assertIsNone(result["spot_action"])

    def test_terminate_notice_parsed(self):
        raw = json.dumps({"action": "terminate", "time": "2024-06-01T12:00:00Z"})
        result = _make_cloud(spot_action_raw=raw)
        self.assertEqual(result["spot_action"]["action"], "terminate")
        self.assertEqual(result["spot_action"]["time"],   "2024-06-01T12:00:00Z")

    def test_stop_action(self):
        raw = json.dumps({"action": "stop", "time": "2024-06-01T12:00:00Z"})
        result = _make_cloud(spot_action_raw=raw)
        self.assertEqual(result["spot_action"]["action"], "stop")

    def test_hibernate_action(self):
        raw = json.dumps({"action": "hibernate", "time": "2024-06-01T12:00:00Z"})
        result = _make_cloud(spot_action_raw=raw)
        self.assertEqual(result["spot_action"]["action"], "hibernate")

    def test_malformed_json_returns_none(self):
        result = _make_cloud(spot_action_raw="not-json")
        self.assertIsNone(result["spot_action"])


# ---------------------------------------------------------------------------
# Rebalance recommendation
# ---------------------------------------------------------------------------

class TestRebalanceRecommendation(unittest.TestCase):
    """rebalance_recommendation is None normally; populated when AWS recommends migration."""

    def test_none_when_no_recommendation(self):
        result = _make_cloud()
        self.assertIsNone(result["rebalance_recommendation"])

    def test_recommendation_parsed(self):
        raw = json.dumps({"noticeTime": "2024-06-01T10:00:00Z"})
        result = _make_cloud(rebalance_raw=raw)
        self.assertEqual(result["rebalance_recommendation"]["notice_time"],
                         "2024-06-01T10:00:00Z")

    def test_malformed_json_returns_none(self):
        result = _make_cloud(rebalance_raw="not-json")
        self.assertIsNone(result["rebalance_recommendation"])


# ---------------------------------------------------------------------------
# Instance status checks (boto3)
# ---------------------------------------------------------------------------

_STATUS_OK = {
    "SystemStatus":   {"Status": "ok",       "Details": [{"Name": "reachability", "Status": "passed"}]},
    "InstanceStatus": {"Status": "ok",       "Details": [{"Name": "reachability", "Status": "passed"}]},
}
_STATUS_IMPAIRED = {
    "SystemStatus":   {"Status": "impaired", "Details": [{"Name": "reachability", "Status": "failed"}]},
    "InstanceStatus": {"Status": "ok",       "Details": []},
}
_STATUS_WITH_EBS = dict(_STATUS_OK, AttachedEbsStatus={"Status": "ok", "Details": []})


class TestInstanceStatus(unittest.TestCase):
    """instance_status is populated from boto3 describe_instance_status."""

    def test_absent_when_boto3_unavailable(self):
        result = _make_cloud(boto3_available=False)
        self.assertNotIn("instance_status", result)

    def test_absent_when_no_status_data(self):
        # describe_instance_status returns empty InstanceStatuses list.
        result = _make_cloud(boto3_instance_status=None)
        self.assertNotIn("instance_status", result)

    def test_ok_status(self):
        result = _make_cloud(boto3_instance_status=_STATUS_OK)
        s = result["instance_status"]
        self.assertEqual(s["system_status"],   "ok")
        self.assertEqual(s["instance_status"], "ok")

    def test_impaired_system_status(self):
        result = _make_cloud(boto3_instance_status=_STATUS_IMPAIRED)
        self.assertEqual(result["instance_status"]["system_status"], "impaired")

    def test_attached_ebs_status_included_when_present(self):
        result = _make_cloud(boto3_instance_status=_STATUS_WITH_EBS)
        self.assertEqual(result["instance_status"]["attached_ebs_status"], "ok")

    def test_attached_ebs_status_absent_when_not_in_response(self):
        result = _make_cloud(boto3_instance_status=_STATUS_OK)
        self.assertNotIn("attached_ebs_status", result["instance_status"])


# ---------------------------------------------------------------------------
# AwsCloud.__init__
# ---------------------------------------------------------------------------

class TestAwsCloudInit(unittest.TestCase):
    """__init__() calls get_metadata() and stores result in self.metadata."""

    def test_init_populates_metadata(self):
        fake = {"provider": "aws"}
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
