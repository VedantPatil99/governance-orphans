"""Governance join, per-DAC table and O1-O5 classification. Pure functions: no network, no files."""
import pandas as pd

from .config import EGA_DAC_ID, EGA_DATASET_ID, GENERIC_ROWS
from .contacts import assess_contact, contact_domains, redact
from .roster import MATCH_COLUMNS


def _empty_agg():
    return {"n": 0, "released": 0, "deprecated": 0, "controlled": 0, "samples": 0}


def _count(a, d):
    a["n"] += 1
    a["released"] += bool(d.get("is_released"))
    a["deprecated"] += bool(d.get("is_deprecated"))
    a["controlled"] += d.get("access_type") == "controlled"
    a["samples"] += d.get("num_samples") or 0


def index_policies(policies):
    """Returns (policy -> DAC, DAC -> list of policy titles, DAC -> policy count)."""
    policy_to_dac = {p.get("accession_id"): p.get("dac_accession_id") for p in policies if p.get("accession_id")}
    policy_text_by_dac, policy_count_by_dac = {}, {}
    for p in policies:
        dac_id = p.get("dac_accession_id")
        if dac_id:
            policy_count_by_dac[dac_id] = policy_count_by_dac.get(dac_id, 0) + 1
            policy_text_by_dac.setdefault(dac_id, []).append(p.get("title") or "")
    return policy_to_dac, policy_text_by_dac, policy_count_by_dac


def governance_join(datasets, policy_to_dac):
    """dataset -> policy -> DAC. Returns ({DAC: counts}, number of datasets with no resolvable DAC)."""
    agg, unmatched = {}, 0
    for d in datasets:
        dac_id = policy_to_dac.get(d.get("policy_accession_id"))
        if not dac_id:
            unmatched += 1
            continue
        _count(agg.setdefault(dac_id, _empty_agg()), d)
    return agg, unmatched


def policy_orphans(datasets, policy_to_dac):
    """O5: datasets with no policy, hence no DAC on record."""
    return pd.DataFrame([{
        "accession_id": d.get("accession_id"),
        "policy_accession_id": d.get("policy_accession_id"),
        "access_type": d.get("access_type"),
        "is_released": d.get("is_released"),
        "released_date": d.get("released_date"),
        "is_deprecated": d.get("is_deprecated"),
        "num_samples": d.get("num_samples"),
    } for d in datasets if not policy_to_dac.get(d.get("policy_accession_id"))])


def annotate_policy_orphans(o5, recovered):
    """Splits O5 by whether a secondary route (dataset -> DAC directly, or via files) finds a committee."""
    o5 = o5.copy()
    o5["n_files"] = o5["accession_id"].map(lambda a: recovered[a]["n_files"])
    o5["dac_direct"] = o5["accession_id"].map(lambda a: "; ".join(recovered[a]["dacs_direct"]))
    o5["dac_via_files"] = o5["accession_id"].map(lambda a: "; ".join(recovered[a]["dacs_files"]))
    o5["malformed_accession"] = ~o5["accession_id"].astype(str).str.fullmatch(EGA_DATASET_ID.pattern)
    o5["o5_subtype"] = o5["accession_id"].map(
        lambda a: "recoverable_secondary_route" if recovered[a]["dacs"] else "no_public_path")
    return o5


def credit_secondary_route(agg, datasets, recovered):
    """Credit policy-less datasets to the DAC a secondary route finds, so a DAC that governs data with no
    policy link (e.g. an ended consortium whose policy links were never recorded) shows its real impact."""
    by_id = {d.get("accession_id"): d for d in datasets}
    for ds_id, info in recovered.items():
        for dac_id in info["dacs"]:
            a = agg.setdefault(dac_id, _empty_agg())
            _count(a, by_id[ds_id])
            a["no_policy"] = a.get("no_policy", 0) + 1
    return agg


def dac_table(dacs, agg, url_status, domain_status, policy_text_by_dac, policy_count_by_dac):
    """One row per DAC record. Personal data: only email domains are kept; free text is redacted."""
    rows = []
    for dac in dacs:
        acc = dac.get("accession_id")
        contacts = dac.get("contacts") or []
        us = url_status.get(acc, "no_url")
        cstatus, o3 = assess_contact(contacts, us, domain_status)
        if not EGA_DAC_ID.fullmatch(str(acc)):
            # Non-EGA stubs (numeric ids mirroring NIH/dbGaP committees, e.g. "NCI/NHGRI TCGA DAC"):
            # references to a committee in another archive, not EGA DACs that lost their contact.
            cstatus, o3 = "external_reference_stub", False
        doms = sorted(set(contact_domains(contacts)))
        a = agg.get(acc, _empty_agg())
        title = dac.get("title") or ""
        o4 = bool(dac.get("is_deprecated")) or "deprecated" in title.lower() or (a["n"] > 0 and a["deprecated"] == a["n"])
        rows.append({
            "accession_id": acc,
            "title": redact(title),
            "description": redact(dac.get("description")),
            "url": dac.get("url"),
            "url_status": us,
            "n_contacts": len(contacts),
            "contact_domains": "; ".join(doms),
            "contact_domain_status": "; ".join(domain_status.get(x, "unknown") for x in doms),
            "contact_status": cstatus,
            "is_released": dac.get("is_released"),
            "is_deprecated": dac.get("is_deprecated", False),
            "policy_count": policy_count_by_dac.get(acc, 0),
            "dataset_count": a["n"],
            "released_dataset_count": a["released"],
            "deprecated_dataset_count": a["deprecated"],
            "controlled_dataset_count": a["controlled"],
            "total_samples": a["samples"],
            "datasets_without_policy_link": a.get("no_policy", 0),
            "O3_contact_orphan": o3,
            "O4_infrastructure_orphan": o4,
            "_policy_text": " | ".join(policy_text_by_dac.get(acc, [])),
        })
    return pd.DataFrame(rows)


def apply_matching(df, match_consortium):
    """Roster match: the DAC's own title/description first, then its own policy titles."""
    matched = df.apply(
        lambda row: match_consortium(f"{row['title']} {row['description'] or ''}", row["_policy_text"]),
        axis=1, result_type="expand")
    matched.columns = MATCH_COLUMNS
    return pd.concat([df.drop(columns="_policy_text"), matched], axis=1)


def lifecycle_class(row):
    if pd.isna(row["consortium_name"]):
        return "unmatched"
    # A hit only in policy text ("data access follows ICGC guidelines") means the DAC is an
    # institution's own committee affiliated with the consortium, not one the consortium ran --
    # so the consortium ending does not by itself orphan it.
    if row["match_source"] == "policy":
        return "affiliated_institutional_DAC"
    if row["consortium_name"] in GENERIC_ROWS:
        return "archive_generic_DAC"
    status = row["consortium_status"]
    has_successor = isinstance(row["consortium_successor"], str) and row["consortium_successor"].strip() != ""
    if status == "ended":
        return "O2_succession" if has_successor else "O1_dissolution"
    if status == "past_driver_project":
        return "O2b_delisted_from_GA4GH"
    return "active_consortium"


def primary_orphan_type(row):
    # Lifecycle orphaning is the stronger claim, so it takes precedence for the one-label view;
    # the O3/O4 flags are still recorded separately for every DAC.
    if row["lifecycle_class"] in ("O1_dissolution", "O2_succession", "O2b_delisted_from_GA4GH"):
        return row["lifecycle_class"]
    if row["O3_contact_orphan"]:
        return "O3_contact_orphan"
    if row["O4_infrastructure_orphan"]:
        return "O4_infrastructure_orphan"
    return "no_orphan_signal_detected"


def classify(df):
    df = df.copy()
    df["lifecycle_class"] = df.apply(lifecycle_class, axis=1)
    df["orphan_type"] = df.apply(primary_orphan_type, axis=1)
    return df
