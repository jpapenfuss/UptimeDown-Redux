# AWS EC2 instance metadata gatherer.
#
# Detects EC2 via IMDSv2 and collects instance identity (id, type, region, AZ,
# account, AMI, architecture, private IP), instance life-cycle (on-demand/spot),
# public IP, IAM instance profile, instance tags, network interfaces (per-ENI),
# attached EBS volumes, and Auto Scaling group membership.
#
# IMDS-sourced fields (no AWS SDK required):
#   public_ip, iam_profile, tags (if "Allow tags in metadata" is enabled),
#   network_interfaces
#
# boto3-sourced fields (omitted when boto3 is not installed):
#   burst (T-series CPU credit mode), tags (fallback if IMDS tags not enabled),
#   volumes, autoscaling_group
#
# Falls back to direct HTTP (urllib) if boto3 is absent; all IMDS HTTP helpers
# live in util.py so future cloud provider gatherers can reuse them.
#
# Exposes AwsCloud class. After instantiation:
#   metadata — dict with cloud/instance fields and a '_time' key,
#              or False if the instance is not running on EC2.
#
# Design notes:
#   IMDSv2 requires a session token obtained via PUT before any GET.  The token
#   fetch doubles as cloud-provider identification: if the PUT fails, this is not
#   AWS IMDS even if 169.254.169.254 was reachable (e.g. GCP, Azure, or APIPA).
#   A short TCP probe (util.imds_reachable) gates all HTTP work so non-cloud
#   machines fail fast without waiting for HTTP timeouts.
import sys
sys.dont_write_bytecode = True
import json
import logging
import time

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

IMDS_IP = "169.254.169.254"
_TOKEN_PATH         = "/latest/api/token"
_IDENTITY_PATH      = "/latest/dynamic/instance-identity/document"
_LIFECYCLE_PATH     = "/latest/meta-data/instance-life-cycle"
_PUBLIC_IP_PATH     = "/latest/meta-data/public-ipv4"
_IAM_INFO_PATH      = "/latest/meta-data/iam/info"
_TAGS_PATH          = "/latest/meta-data/tags/instance"
_MACS_PATH          = "/latest/meta-data/network/interfaces/macs/"
_MAINTENANCE_SCHEDULED_PATH = "/latest/meta-data/events/maintenance/scheduled"
_MAINTENANCE_HISTORY_PATH   = "/latest/meta-data/events/maintenance/history"
_SPOT_ACTION_PATH           = "/latest/meta-data/spot/instance-action"
_REBALANCE_PATH             = "/latest/meta-data/events/recommendations/rebalance"

# Instance type prefixes eligible for CPU burst credits.
_BURST_PREFIXES = ("t1.", "t2.", "t3.", "t3a.", "t4g.")


def _get_token():
    """Fetch an IMDSv2 session token. Returns the token string or None."""
    return util.imds_put(
        IMDS_IP,
        _TOKEN_PATH,
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
    )


def _imds(path, token):
    """GET a metadata path using an IMDSv2 token."""
    headers = {"X-aws-ec2-metadata-token": token} if token else {}
    return util.imds_get(IMDS_IP, path, headers=headers)


def _burst_credits(instance_id):
    """Return CPU credit specification for a T-series instance via boto3.

    Returns a dict {'cpu_credits': 'standard'|'unlimited'} if boto3 is
    available and the API call succeeds, None otherwise.
    """
    try:
        import boto3
    except ImportError:
        logger.debug("_burst_credits: boto3 not available")
        return None
    try:
        ec2 = boto3.client('ec2')
        resp = ec2.describe_instance_credit_specifications(InstanceIds=[instance_id])
        specs = resp.get('InstanceCreditSpecifications', [])
        if specs:
            return {"cpu_credits": specs[0].get("CpuCredits", "unknown")}
        return None
    except Exception as e:
        logger.warning("_burst_credits: boto3 call failed: %s", e)
        return None


def _imds_public_ip(token):
    """Return the instance's public IPv4 address, or None."""
    raw = _imds(_PUBLIC_IP_PATH, token)
    return raw.strip() if raw else None


def _imds_iam_profile(token):
    """Return the IAM instance profile ARN from IMDS, or None.

    The /iam/info endpoint returns a JSON doc containing InstanceProfileArn.
    Returns None if IAM is not attached or the call fails.
    """
    raw = _imds(_IAM_INFO_PATH, token)
    if not raw:
        return None
    try:
        info = json.loads(raw)
        return info.get("InstanceProfileArn")
    except (ValueError, KeyError):
        return None


def _imds_tags(token):
    """Fetch instance tags from IMDS. Returns a dict or None.

    Requires "Allow tags in instance metadata" to be enabled on the instance.
    Returns None (not an empty dict) if the endpoint is unavailable, so the
    caller can fall back to boto3.
    """
    raw = _imds(_TAGS_PATH, token)
    if raw is None:
        return None
    tags = {}
    for key in raw.strip().splitlines():
        key = key.strip()
        if key:
            val = _imds(f"{_TAGS_PATH}/{key}", token)
            tags[key] = val.strip() if val else ""
    return tags


def _boto3_tags(instance_id):
    """Fetch instance tags via boto3 describe_tags. Returns a dict or None."""
    try:
        import boto3
    except ImportError:
        return None
    try:
        ec2 = boto3.client('ec2')
        resp = ec2.describe_tags(Filters=[
            {'Name': 'resource-id',   'Values': [instance_id]},
            {'Name': 'resource-type', 'Values': ['instance']},
        ])
        return {t['Key']: t['Value'] for t in resp.get('Tags', [])}
    except Exception as e:
        logger.warning("_boto3_tags: boto3 call failed: %s", e)
        return None


def _imds_network_interfaces(token):
    """Fetch per-ENI info from IMDS. Returns a list of dicts (one per interface).

    Each dict contains: mac, interface_id, device_number (int), subnet_id,
    vpc_id, private_ips (list), public_ips (list), security_group_ids (list).
    """
    raw = _imds(_MACS_PATH, token)
    if not raw:
        return []

    interfaces = []
    for entry in raw.strip().splitlines():
        mac = entry.strip().rstrip('/')
        if not mac:
            continue

        base = f"{_MACS_PATH}{mac}"

        def _get(subpath, _base=base):
            val = _imds(f"{_base}/{subpath}", token)
            return val.strip() if val else None

        def _get_lines(subpath, _base=base):
            val = _imds(f"{_base}/{subpath}", token)
            return [s.strip() for s in val.strip().splitlines() if s.strip()] if val else []

        iface = {"mac": mac}

        iface_id = _get("interface-id")
        if iface_id:
            iface["interface_id"] = iface_id

        dev_num = _get("device-number")
        if dev_num is not None:
            try:
                iface["device_number"] = int(dev_num)
            except ValueError:
                iface["device_number"] = dev_num

        subnet_id = _get("subnet-id")
        if subnet_id:
            iface["subnet_id"] = subnet_id

        vpc_id = _get("vpc-id")
        if vpc_id:
            iface["vpc_id"] = vpc_id

        iface["private_ips"]        = _get_lines("local-ipv4s")
        iface["public_ips"]         = _get_lines("public-ipv4s")
        iface["security_group_ids"] = _get_lines("security-group-ids")

        interfaces.append(iface)

    return interfaces


def _boto3_volumes(instance_id):
    """Fetch attached EBS volume details via boto3. Returns a list of dicts or None.

    Each dict contains: volume_id, device, size_gb, volume_type, encrypted,
    and optionally iops and throughput_mbps.
    Returns None if boto3 is not installed or the call fails.
    """
    try:
        import boto3
    except ImportError:
        return None
    try:
        ec2 = boto3.client('ec2')
        resp = ec2.describe_volumes(
            Filters=[{'Name': 'attachment.instance-id', 'Values': [instance_id]}]
        )
        volumes = []
        for vol in resp.get('Volumes', []):
            attachment = next(
                (a for a in vol.get('Attachments', []) if a.get('InstanceId') == instance_id),
                {}
            )
            entry = {
                "volume_id":   vol.get('VolumeId', ''),
                "device":      attachment.get('Device', ''),
                "size_gb":     vol.get('Size'),
                "volume_type": vol.get('VolumeType', ''),
                "encrypted":   vol.get('Encrypted', False),
            }
            if vol.get('Iops'):
                entry["iops"] = vol['Iops']
            if vol.get('Throughput'):
                entry["throughput_mbps"] = vol['Throughput']
            volumes.append(entry)
        return volumes
    except Exception as e:
        logger.warning("_boto3_volumes: boto3 call failed: %s", e)
        return None


def _boto3_autoscaling_group(instance_id):
    """Return the Auto Scaling group name for this instance, or None.

    Returns None if boto3 is not installed, the instance is not in an ASG,
    or the call fails.
    """
    try:
        import boto3
    except ImportError:
        return None
    try:
        asg = boto3.client('autoscaling')
        resp = asg.describe_auto_scaling_instances(InstanceIds=[instance_id])
        instances = resp.get('AutoScalingInstances', [])
        if instances:
            return instances[0].get('AutoScalingGroupName')
        return None
    except Exception as e:
        logger.warning("_boto3_autoscaling_group: boto3 call failed: %s", e)
        return None


def _imds_maintenance_events(token):
    """Fetch scheduled and historical maintenance events from IMDS.

    Returns {"scheduled": [...], "history": [...]}.  Both paths return [] (HTTP
    200, not 404) when no events are active; callers can rely on the keys always
    being present.

    Each event dict has: event_id, code, description, state, not_before,
    not_after.  Timestamp strings use the IMDS format "21 Jan 2019 09:00:43 GMT"
    (RFC 2822-like, not ISO 8601).  History entries have Description prefixed
    with "[Canceled]" or "[Completed]".
    """
    def _parse(path):
        raw = _imds(path, token)
        if not raw:
            return []
        try:
            events = json.loads(raw)
        except ValueError:
            return []
        result = []
        for ev in events:
            result.append({
                "event_id":    ev.get("EventId", ""),
                "code":        ev.get("Code", ""),
                "description": ev.get("Description", ""),
                "state":       ev.get("State", ""),
                "not_before":  ev.get("NotBefore", ""),
                "not_after":   ev.get("NotAfter", ""),
            })
        return result

    return {
        "scheduled": _parse(_MAINTENANCE_SCHEDULED_PATH),
        "history":   _parse(_MAINTENANCE_HISTORY_PATH),
    }


def _imds_spot_action(token):
    """Return the pending spot instance action, or None.

    Returns None in normal operation (IMDS path 404s).
    Returns {"action": "terminate"/"stop"/"hibernate", "time": "<ISO>"}
    approximately 2 minutes before AWS acts on a spot interruption or
    scheduled stop/hibernate.
    """
    raw = _imds(_SPOT_ACTION_PATH, token)
    if not raw:
        return None
    try:
        action = json.loads(raw)
        return {
            "action": action.get("action", ""),
            "time":   action.get("time", ""),
        }
    except ValueError:
        return None


def _imds_rebalance_recommendation(token):
    """Return the spot rebalance recommendation notice, or None.

    Returns None in normal operation (IMDS path 404s).
    Returns {"notice_time": "<ISO>"} when AWS recommends proactive migration
    to a new spot instance (earlier signal than an interruption notice).
    """
    raw = _imds(_REBALANCE_PATH, token)
    if not raw:
        return None
    try:
        rec = json.loads(raw)
        return {"notice_time": rec.get("noticeTime", "")}
    except ValueError:
        return None


def _boto3_instance_status(instance_id):
    """Fetch EC2 instance status checks via boto3. Returns a dict or None.

    Status check values: 'ok', 'impaired', 'insufficient-data',
    'not-applicable', 'initializing'.

    Returns a dict with:
        system_status     — host hardware/network reachability (AWS-side)
        instance_status   — OS/kernel reachability (guest-side)
        attached_ebs_status — EBS health (newer field; omitted if absent)
    Returns None if boto3 is not installed or the call fails.
    """
    try:
        import boto3
    except ImportError:
        return None
    try:
        ec2 = boto3.client('ec2')
        resp = ec2.describe_instance_status(
            InstanceIds=[instance_id],
            IncludeAllInstances=True,
        )
        statuses = resp.get('InstanceStatuses', [])
        if not statuses:
            return None
        s = statuses[0]
        result = {
            "system_status":   s.get('SystemStatus',   {}).get('Status', 'unknown'),
            "instance_status": s.get('InstanceStatus', {}).get('Status', 'unknown'),
        }
        ebs = s.get('AttachedEbsStatus', {})
        if ebs:
            result["attached_ebs_status"] = ebs.get('Status', 'unknown')
        return result
    except Exception as e:
        logger.warning("_boto3_instance_status: boto3 call failed: %s", e)
        return None


class AwsCloud:
    """AWS EC2 instance metadata gatherer.

    After instantiation:
        metadata — dict containing:
            provider            'aws'
            instance_id         EC2 instance ID (e.g. 'i-0abc123...')
            instance_type       Instance type (e.g. 't3.medium', 'm5.xlarge')
            region              AWS region (e.g. 'us-east-1')
            availability_zone   AZ (e.g. 'us-east-1a')
            account_id          AWS account ID
            ami_id              AMI used to launch this instance
            architecture        CPU architecture (e.g. 'x86_64', 'arm64')
            private_ip          Primary private IPv4 address
            public_ip           Public IPv4 address, or None
            iam_profile         IAM instance profile ARN, or None
            instance_life_cycle 'on-demand', 'spot', 'scheduled', or 'capacity-block'
            burst_capable       True for T-series instance types, False otherwise
            burst               (T-series only) {'cpu_credits': 'standard'|'unlimited'}
                                if boto3 is available, omitted otherwise
            tags                dict of tag key→value, or None if unavailable
            network_interfaces  list of per-ENI dicts (mac, interface_id, device_number,
                                subnet_id, vpc_id, private_ips, public_ips,
                                security_group_ids)
            volumes             (boto3 only) list of attached EBS volume dicts
                                (volume_id, device, size_gb, volume_type, encrypted,
                                optionally iops, throughput_mbps); omitted if boto3
                                unavailable
            autoscaling_group   (boto3 only) ASG name string, or None if not in an ASG;
                                omitted if boto3 unavailable
            _time               Unix timestamp of data capture
        or False if not running on EC2 (IMDS unreachable or not AWS).
    """

    def get_metadata(self):
        """Probe IMDS and return an AWS metadata dict, or False if not on EC2."""
        if not util.imds_reachable(IMDS_IP):
            logger.debug("get_metadata: IMDS not reachable, not on EC2")
            return False

        ts = getattr(self, '_ts', None)
        if ts is None:
            ts = time.time()

        token = _get_token()
        if token is None:
            # Reachable address but not AWS IMDSv2 (e.g. GCP, Azure, or APIPA).
            logger.debug("get_metadata: IMDSv2 token request failed, not AWS IMDS")
            return False

        identity_raw = _imds(_IDENTITY_PATH, token)
        if identity_raw is None:
            logger.warning("get_metadata: failed to read instance identity document")
            return False
        try:
            identity = json.loads(identity_raw)
        except (ValueError, KeyError) as e:
            logger.warning("get_metadata: failed to parse identity document: %s", e)
            return False

        instance_id   = identity.get("instanceId", "")
        instance_type = identity.get("instanceType", "")

        result = {
            "provider":           "aws",
            "instance_id":        instance_id,
            "instance_type":      instance_type,
            "region":             identity.get("region", ""),
            "availability_zone":  identity.get("availabilityZone", ""),
            "account_id":         identity.get("accountId", ""),
            "ami_id":             identity.get("imageId", ""),
            "architecture":       identity.get("architecture", ""),
            "private_ip":         identity.get("privateIp", ""),
            "_time":              ts,
        }

        lifecycle = _imds(_LIFECYCLE_PATH, token)
        result["instance_life_cycle"] = lifecycle.strip() if lifecycle else "unknown"

        if any(instance_type.startswith(p) for p in _BURST_PREFIXES):
            result["burst_capable"] = True
            credits = _burst_credits(instance_id)
            if credits is not None:
                result["burst"] = credits
        else:
            result["burst_capable"] = False

        result["public_ip"]   = _imds_public_ip(token)
        result["iam_profile"] = _imds_iam_profile(token)

        # Tags: try IMDS first (requires "Allow tags in metadata" enabled on the
        # instance), then fall back to boto3 describe_tags.
        tags = _imds_tags(token)
        if tags is None:
            tags = _boto3_tags(instance_id)
        result["tags"] = tags

        result["network_interfaces"] = _imds_network_interfaces(token)

        # Volumes and ASG require boto3 — omit the key entirely if unavailable.
        volumes = _boto3_volumes(instance_id)
        if volumes is not None:
            result["volumes"] = volumes

        asg_name = _boto3_autoscaling_group(instance_id)
        if asg_name is not None:
            result["autoscaling_group"] = asg_name

        # Maintenance events — both paths return [] (not 404) when quiet.
        result["maintenance_events"] = _imds_maintenance_events(token)

        # Spot signals — None when not applicable or no notice pending.
        result["spot_action"]              = _imds_spot_action(token)
        result["rebalance_recommendation"] = _imds_rebalance_recommendation(token)

        # Instance status checks — boto3 only; omitted if unavailable.
        instance_status = _boto3_instance_status(instance_id)
        if instance_status is not None:
            result["instance_status"] = instance_status

        n_scheduled = len(result["maintenance_events"]["scheduled"])
        logger.debug(
            "get_metadata: %s %s region=%s az=%s life_cycle=%s burst_capable=%s "
            "tags=%s nics=%d maintenance_scheduled=%d spot_action=%s",
            instance_id, instance_type,
            result["region"], result["availability_zone"],
            result["instance_life_cycle"], result["burst_capable"],
            len(tags) if isinstance(tags, dict) else None,
            len(result["network_interfaces"]),
            n_scheduled,
            result["spot_action"],
        )
        return result

    def __init__(self, _time=None):
        """Probe EC2 IMDS and populate self.metadata."""
        self._ts = _time if _time is not None else time.time()
        self.metadata = self.get_metadata()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    pprint.PrettyPrinter(indent=4).pprint(AwsCloud().metadata)
else:
    from . import util
