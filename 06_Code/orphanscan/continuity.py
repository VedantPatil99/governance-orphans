"""The DAC continuity checklist (C1-C8): minimum record fields a committee needs to survive its parent body."""
import pandas as pd

from .config import TEST_NAME

CHECKS = {
    "C1_reachable_contact": ("C1 Reachable contact",
                             "at least one contact on a live email domain (or a working URL)"),
    "C2_role_or_institutional_contact": ("C2 Role / institutional contact",
                                         "a role mailbox or several institutional contacts, not one person"),
    "C3_redundant_contacts": ("C3 Two or more contacts", "survives one person leaving"),
    "C4_self_description": ("C4 Describes itself", "a description saying what the committee governs"),
    "C5_policy_linked_datasets": ("C5 Datasets linked via policy",
                                  "every dataset reaches the committee through a policy, not only through files"),
    "C6_live_status": ("C6 Live, non-test record", "not deprecated, not a test/placeholder record"),
    "C7_parent_body_field": ("C7 Names parent body (no field)",
                             "EGA's DAC schema has no field for the consortium or institution behind it"),
    "C8_successor_field": ("C8 Names successor (no field)", "EGA's DAC schema has no field for a successor DAC"),
}
OBSERVABLE = [c for c in CHECKS if c not in ("C7_parent_body_field", "C8_successor_field")]


def continuity_checks(dacs):
    """dacs: rows of governance_decay_scan_results.csv. Returns a boolean frame, one column per check."""
    is_test_like = dacs["title"].fillna("").str.contains(TEST_NAME)
    checks = pd.DataFrame(index=dacs.index)
    checks["C1_reachable_contact"] = ~dacs["contact_status"].isin(["no_contact", "domain_unresolvable"])
    checks["C2_role_or_institutional_contact"] = dacs["contact_status"] == "institutional"
    checks["C3_redundant_contacts"] = dacs["n_contacts"] >= 2
    checks["C4_self_description"] = dacs["description"].fillna("").str.strip().str.len() > 0
    checks["C5_policy_linked_datasets"] = ~(dacs["datasets_without_policy_link"] > 0)
    checks["C6_live_status"] = ~dacs["O4_infrastructure_orphan"].astype(bool) & ~is_test_like
    # No field exists in the EGA DAC schema for a parent body or a successor committee.
    checks["C7_parent_body_field"] = False
    checks["C8_successor_field"] = False
    return checks
