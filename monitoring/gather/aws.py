# AWS EC2 instance metadata gatherer.
#
# Detects EC2 via IMDSv2 and collects instance identity (id, type, region, AZ,
# account, AMI, architecture, private IP), instance life-cycle (on-demand/spot),
# and — for T-series burst-capable instance types — CPU credit specification
# (standard vs unlimited) via boto3 if it is installed.
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
_TOKEN_PATH = "/latest/api/token"
_IDENTITY_PATH = "/latest/dynamic/instance-identity/document"
_LIFECYCLE_PATH = "/latest/meta-data/instance-life-cycle"

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


class AwsCloud:
    """AWS EC2 instance metadata gatherer.

    After instantiation:
        metadata — dict containing:
            provider          'aws'
            instance_id       EC2 instance ID (e.g. 'i-0abc123...')
            instance_type     Instance type (e.g. 't3.medium', 'm5.xlarge')
            region            AWS region (e.g. 'us-east-1')
            availability_zone AZ (e.g. 'us-east-1a')
            account_id        AWS account ID
            ami_id            AMI used to launch this instance
            architecture      CPU architecture (e.g. 'x86_64', 'arm64')
            private_ip        Primary private IPv4 address
            instance_life_cycle  'on-demand', 'spot', 'scheduled', or 'capacity-block'
            burst_capable     True for T-series instance types, False otherwise
            burst             (T-series only) {'cpu_credits': 'standard'|'unlimited'}
                              if boto3 is available, omitted otherwise
            _time             Unix timestamp of data capture
        or False if not running on EC2 (IMDS unreachable or not AWS).
    """

    def get_metadata(self):
        """Probe IMDS and return an AWS metadata dict, or False if not on EC2."""
        if not util.imds_reachable(IMDS_IP):
            logger.debug("get_metadata: IMDS not reachable, not on EC2")
            return False

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

        logger.debug(
            "get_metadata: %s %s region=%s az=%s life_cycle=%s burst_capable=%s",
            instance_id, instance_type,
            result["region"], result["availability_zone"],
            result["instance_life_cycle"], result["burst_capable"],
        )
        return result

    def __init__(self):
        """Probe EC2 IMDS and populate self.metadata."""
        self.metadata = self.get_metadata()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    pprint.PrettyPrinter(indent=4).pprint(AwsCloud().metadata)
else:
    from . import util
