"""
Snapshot comparison — measures governance change between two EGA census snapshots.

  python compare_snapshots.py raw_ega_snapshot raw_ega_snapshot_2

Reports committees, policies and datasets added or removed; DAC records whose contacts, status or title
changed; datasets whose governance link changed (re-linked, newly policy-less, policy-less resolved);
and the continuity profile of newly created committees. Writes results/snapshot_diff.json and
results/snapshot_diff_changes.csv. Contact changes are compared by email DOMAIN only — no addresses
are written out.
"""
import argparse
import json
import os

import pandas as pd

from orphanscan.config import EGA_DAC_ID, RESULTS
from orphanscan.contacts import assess_contact, contact_domains, redact


def load(snapshot):
    out = {}
    for label in ("dacs", "policies", "datasets"):
        with open(os.path.join(snapshot, f"{label}.json"), encoding="utf-8") as f:
            snap = json.load(f)
        out[label] = {r.get("accession_id"): r for r in snap["records"]}
        out["date"] = snap["retrieval_date"]
    return out


def dac_view(d):
    contacts = d.get("contacts") or []
    return {"title": (d.get("title") or "").strip(), "is_deprecated": bool(d.get("is_deprecated")),
            "is_released": bool(d.get("is_released")), "url": d.get("url"), "n_contacts": len(contacts),
            "contact_domains": "; ".join(sorted(set(contact_domains(contacts))))}


def diff_ids(a, b):
    return sorted(set(b) - set(a)), sorted(set(a) - set(b)), sorted(set(a) & set(b))


def compare(old, new):
    """old, new: outputs of load(). Returns (summary dict, list of change records)."""
    changes = []
    summary = {"old_snapshot": {"date": old["date"]}, "new_snapshot": {"date": new["date"]}}

    # --- committees -----------------------------------------------------------------------------
    added, removed, common = diff_ids(old["dacs"], new["dacs"])
    changed = {"contacts": 0, "deprecated": 0, "released": 0, "title": 0, "url": 0}
    for acc in common:
        a, b = dac_view(old["dacs"][acc]), dac_view(new["dacs"][acc])
        for field, key in (("contact_domains", "contacts"), ("n_contacts", "contacts"), ("is_deprecated", "deprecated"),
                           ("is_released", "released"), ("title", "title"), ("url", "url")):
            if a[field] != b[field]:
                changed[key] += 1
                changes.append({"kind": "dac_changed", "accession_id": acc, "field": field,
                                "old": redact(str(a[field])), "new": redact(str(b[field]))})
                break
    for acc in added:
        changes.append({"kind": "dac_added", "accession_id": acc, "field": "title",
                        "old": "", "new": redact(dac_view(new["dacs"][acc])["title"])})
    for acc in removed:
        changes.append({"kind": "dac_removed", "accession_id": acc, "field": "title",
                        "old": redact(dac_view(old["dacs"][acc])["title"]), "new": ""})
    # contact profile of new committees; their domains are not DNS-checked here ("unknown" counts as not dead)
    new_profiles = [assess_contact(new["dacs"][a].get("contacts") or [], "no_url", {})[0]
                    for a in added if EGA_DAC_ID.fullmatch(str(a))]
    summary["dacs"] = {"old": len(old["dacs"]), "new": len(new["dacs"]), "added": len(added), "removed": len(removed),
                       "changed": changed,
                       "new_dac_contact_profile": pd.Series(new_profiles, dtype=str).value_counts().to_dict()}

    # --- policies -------------------------------------------------------------------------------
    p_added, p_removed, p_common = diff_ids(old["policies"], new["policies"])
    relinked = [p for p in p_common
                if old["policies"][p].get("dac_accession_id") != new["policies"][p].get("dac_accession_id")]
    for p in relinked:
        changes.append({"kind": "policy_dac_changed", "accession_id": p, "field": "dac_accession_id",
                        "old": old["policies"][p].get("dac_accession_id"),
                        "new": new["policies"][p].get("dac_accession_id")})
    summary["policies"] = {"old": len(old["policies"]), "new": len(new["policies"]), "added": len(p_added),
                           "removed": len(p_removed), "moved_to_another_dac": len(relinked)}

    # --- datasets -------------------------------------------------------------------------------
    d_added, d_removed, d_common = diff_ids(old["datasets"], new["datasets"])
    counts = {"policy_changed": 0, "moved_to_another_dac": 0, "became_policy_less": 0, "policy_less_resolved": 0,
              "newly_released": 0, "newly_deprecated": 0}
    for d in d_common:
        a, b = old["datasets"][d], new["datasets"][d]
        pa, pb = a.get("policy_accession_id"), b.get("policy_accession_id")
        if pa != pb:
            key = "became_policy_less" if not pb else ("policy_less_resolved" if not pa else "policy_changed")
            counts[key] += 1
            changes.append({"kind": f"dataset_{key}", "accession_id": d, "field": "policy_accession_id",
                            "old": pa, "new": pb})
            dac_a = (old["policies"].get(pa) or {}).get("dac_accession_id")
            dac_b = (new["policies"].get(pb) or {}).get("dac_accession_id")
            if dac_a and dac_b and dac_a != dac_b:
                # governance transferred to another committee -- the record keeps no trace of why or from whom
                counts["moved_to_another_dac"] += 1
                changes.append({"kind": "dataset_moved_to_another_dac", "accession_id": d,
                                "field": "governing_dac", "old": dac_a, "new": dac_b})
        if not a.get("is_released") and b.get("is_released"):
            counts["newly_released"] += 1
        if not a.get("is_deprecated") and b.get("is_deprecated"):
            counts["newly_deprecated"] += 1
            changes.append({"kind": "dataset_deprecated", "accession_id": d, "field": "is_deprecated",
                            "old": False, "new": True})
    new_policyless = [d for d in d_added if not new["datasets"][d].get("policy_accession_id")]
    summary["datasets"] = {"old": len(old["datasets"]), "new": len(new["datasets"]), "added": len(d_added),
                           "removed": len(d_removed), "added_without_policy": len(new_policyless), **counts}
    return summary, changes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old")
    ap.add_argument("new")
    args = ap.parse_args()
    summary, changes = compare(load(args.old), load(args.new))
    summary["old_snapshot"]["path"], summary["new_snapshot"]["path"] = args.old, args.new
    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "snapshot_diff.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    pd.DataFrame(changes, columns=["kind", "accession_id", "field", "old", "new"]).to_csv(
        RESULTS / "snapshot_diff_changes.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
