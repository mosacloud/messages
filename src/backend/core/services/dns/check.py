"""
DNS checking functionality for mail domains.
"""

import re
from typing import Dict, List, Optional, Tuple

import dns.resolver

from core.models import MailDomain


def normalize_txt_value(value: str) -> str:
    """
    Normalize a TXT record value.
    """
    return re.sub(r"\;$", "", re.sub(r"\s*\;\s*", ";", value.strip('"')))


def parse_dkim_tags(value: str) -> Optional[Dict[str, str]]:
    """Parse a DKIM record into a dict of tag=value pairs.

    Per RFC 6376, tags are separated by semicolons, with tag=value format.
    The v= tag MUST be first and equal to DKIM1.
    Returns None if the record is not a valid DKIM record.
    """
    parts = [p.strip() for p in value.split(";") if p.strip()]
    if not parts:
        return None
    # v= must be first
    first = parts[0]
    if not first.startswith("v=") or first.split("=", 1)[1].strip() != "DKIM1":
        return None
    tags = {}
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        tags[key.strip()] = val.strip()
    return tags


def parse_spf_terms(value: str) -> Optional[Tuple[str, set]]:
    """Parse an SPF record into its qualifier-all and set of other terms.

    Per RFC 7208, v=spf1 must be first. Returns (all_mechanism, other_terms)
    where all_mechanism is e.g. "-all", "~all", "+all", "?all" or None,
    and other_terms is the set of remaining mechanisms/modifiers.
    Returns None if not a valid SPF record.
    """
    if not value.startswith("v=spf1"):
        return None
    rest = value[len("v=spf1") :].strip()
    terms = rest.split()
    all_mechanism = None
    other_terms = set()
    for term in terms:
        if term in ("-all", "~all", "+all", "?all", "all"):
            all_mechanism = term
        else:
            other_terms.add(term)
    return (all_mechanism, other_terms)


def _check_dkim_semantic(
    expected_value: str, found_values: List[str]
) -> Optional[Dict[str, any]]:
    """Semantic comparison for DKIM records (tag order doesn't matter per RFC 6376)."""
    expected_tags = parse_dkim_tags(expected_value)
    if not expected_tags:
        return None
    for found_value in found_values:
        found_tags = parse_dkim_tags(found_value)
        if not found_tags:
            continue
        if not all(found_tags.get(k) == v for k, v in expected_tags.items()):
            continue
        # Check for t=y (testing mode) → insecure
        if found_tags.get("t") and "y" in found_tags["t"].split(":"):
            return {"status": "insecure", "found": found_values}
        return {"status": "correct", "found": found_values}
    return None


def _check_spf_semantic(
    expected_value: str, found_values: List[str]
) -> Optional[Dict[str, any]]:
    """Semantic comparison for SPF records (term order doesn't matter)."""
    expected_spf = parse_spf_terms(expected_value)
    if not expected_spf:
        return None
    expected_all, expected_terms = expected_spf
    for found_value in found_values:
        found_spf = parse_spf_terms(found_value)
        if not found_spf:
            continue
        found_all, found_terms = found_spf
        if not expected_terms <= found_terms:
            continue
        if expected_all == found_all:
            return {"status": "correct", "found": found_values}
        if expected_all == "-all" and found_all == "~all":
            return {"status": "correct", "found": found_values}
    return None


def _resolve_dns_values(record_type, target, query_name):
    """Resolve DNS and return found values and normalized expected value flag."""
    if record_type.upper() == "MX":
        answers = dns.resolver.resolve(query_name, "MX")
        return [f"{answer.preference} {answer.exchange}" for answer in answers]

    if record_type.upper() == "TXT":
        answers = dns.resolver.resolve(query_name, "TXT")
        if target.endswith("._domainkey"):
            return [
                normalize_txt_value(answer.to_text().strip('"').replace('" "', ""))
                for answer in answers
            ]
        return [normalize_txt_value(answer.to_text()) for answer in answers]

    answers = dns.resolver.resolve(query_name, record_type)
    return [answer.to_text() for answer in answers]


def _check_txt_security(expected_value, found_values):
    """Check for duplicate/insecure SPF and DMARC records. Returns result or None."""
    # SPF duplicate and insecure checks
    if expected_value.startswith("v=spf1"):
        spf_records = [v for v in found_values if v.startswith("v=spf1")]
        if len(spf_records) > 1:
            return {"status": "duplicate", "found": found_values}
        if expected_value.endswith("-all"):
            for spf in spf_records:
                if spf.endswith("+all") or spf.endswith("?all"):
                    return {"status": "insecure", "found": found_values}

    # DMARC duplicate and insecure checks
    if expected_value.startswith("v=DMARC1"):
        dmarc_records = [v for v in found_values if v.startswith("v=DMARC1")]
        if len(dmarc_records) > 1:
            return {"status": "duplicate", "found": found_values}
        if "p=none" not in expected_value:
            for dmarc in dmarc_records:
                if "p=none" in dmarc:
                    return {"status": "insecure", "found": found_values}

    return None


def check_single_record(
    maildomain: MailDomain, expected_record: Dict[str, any]
) -> Dict[str, any]:
    """
    Check a single DNS record for a mail domain.

    Args:
        maildomain: The MailDomain instance
        expected_record: The expected record to check

    Returns:
        Check result dictionary with status and details
    """
    record_type = expected_record["type"]
    target = expected_record["target"]
    expected_value = expected_record["value"]

    # Build the query name
    query_name = f"{target}.{maildomain.name}" if target else maildomain.name

    try:
        found_values = _resolve_dns_values(record_type, target, query_name)
        if record_type.upper() == "TXT":
            expected_value = normalize_txt_value(expected_value)

        # Check for duplicate/insecure SPF and DMARC
        if record_type.upper() == "TXT":
            security_result = _check_txt_security(expected_value, found_values)
            if security_result:
                return security_result

        # Exact match
        if expected_value in found_values:
            return {"status": "correct", "found": found_values}

        # Accept ~all as correct when -all is expected for SPF records
        if record_type.upper() == "TXT" and expected_value.endswith("-all"):
            softfail_variant = expected_value[:-4] + "~all"
            if softfail_variant in found_values:
                return {"status": "correct", "found": found_values}

        # Semantic fallback comparisons for DKIM and SPF
        if record_type.upper() == "TXT" and target.endswith("._domainkey"):
            result = _check_dkim_semantic(expected_value, found_values)
            if result:
                return result

        if record_type.upper() == "TXT" and expected_value.startswith("v=spf1"):
            result = _check_spf_semantic(expected_value, found_values)
            if result:
                return result

        return {"status": "incorrect", "found": found_values}

    except dns.resolver.NXDOMAIN:
        return {"status": "missing", "error": "Domain not found"}
    except dns.resolver.NoAnswer:
        return {"status": "missing", "error": "No records found"}
    except dns.resolver.NoNameservers:
        return {"status": "missing", "error": "No nameservers found"}
    except dns.resolver.Timeout:
        return {"status": "error", "error": "DNS query timeout"}
    except dns.resolver.YXDOMAIN:
        return {"status": "error", "error": "Domain name too long"}
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"status": "error", "error": f"DNS query failed: {str(e)}"}


def check_dns_records(maildomain: MailDomain) -> List[Dict[str, any]]:
    """
    Check DNS records for a mail domain against expected records.

    Args:
        maildomain: The MailDomain instance to check

    Returns:
        List of records with their check status
    """
    expected_records = maildomain.get_expected_dns_records()
    results = []

    # Collect expected MX values for conflicting detection
    expected_mx_values = {
        record["value"] for record in expected_records if record["type"].upper() == "MX"
    }

    for expected_record in expected_records:
        result_record = expected_record.copy()
        result_record["_check"] = check_single_record(maildomain, expected_record)

        # For MX records that are correct, check for extra (conflicting) MX entries
        if (
            expected_record["type"].upper() == "MX"
            and result_record["_check"]["status"] == "correct"
        ):
            found = result_record["_check"].get("found", [])
            extra_mx = [v for v in found if v not in expected_mx_values]
            if extra_mx:
                result_record["_check"]["status"] = "conflicting"

        results.append(result_record)

    return results
