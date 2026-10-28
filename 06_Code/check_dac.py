"""
DAC continuity checker — scores one or more Data Access Committees against the C1-C8 continuity checklist
and the O1-O5 governance-orphan taxonomy, and says what to fix.

  python check_dac.py EGAC00001000010                 report from the census results (offline)
  python check_dac.py EGAC00001000010 --live          check the committee against EGA right now
  python check_dac.py EGAC00000000014 EGAC00001003442 several at once

Personal data: contact addresses are never printed — only their email domains.
"""
import argparse
import sys

import pandas as pd

from orphanscan import census
from orphanscan.config import BASE, PAGE_SIZE, SCAN_RESULTS
from orphanscan.contacts import contact_domains, resolve_domains
from orphanscan.continuity import CHECKS, OBSERVABLE, continuity_checks
from orphanscan.ega import check_url_liveness, get_json
from orphanscan.roster import build_matcher, load_roster

FIX = {
    "C1_reachable_contact": "publish at least one contact on a working institutional domain",
    "C2_role_or_institutional_contact": "add a role mailbox (e.g. dac@institution) that outlives any one person",
    "C3_redundant_contacts": "list a second named member so the committee survives one person leaving",
    "C4_self_description": "describe what the committee governs and which body it acts for",
    "C5_policy_linked_datasets": "link every dataset to the committee through a policy record",
    "C6_live_status": "close or replace the deprecated / placeholder record and move its datasets",
    "C7_parent_body_field": "record the parent consortium or institution (needs a new schema field)",
    "C8_successor_field": "record a successor committee for when the parent body ends (needs a new schema field)",
}
ORPHAN_MEANING = {
    "O1_dissolution": "its consortium has ended with no successor",
    "O2_succession": "its consortium has ended; a successor exists but the record was not handed over",
    "O2b_delisted_from_GA4GH": "its consortium is no longer a GA4GH Driver Project",
    "O3_contact_orphan": "no reachable contact is published",
    "O4_infrastructure_orphan": "the record or all of its datasets are deprecated",
    "no_orphan_signal_detected": "no orphan signal in the record",
}


def live_row(acc, matcher):
    """Builds the same one-row table the census produces, from live API calls."""
    dac = get_json(f"{BASE}/dacs/{acc}")
    if not dac:
        return None
    datasets, offset = [], 0
    while True:
        page = get_json(f"{BASE}/dacs/{acc}/datasets?limit={PAGE_SIZE}&offset={offset}") or []
        datasets += page
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    # datasets listed under the DAC but without a policy have no policy link (fails C5)
    agg = {acc: {"n": 0, "released": 0, "deprecated": 0, "controlled": 0, "samples": 0}}
    for d in datasets:
        census._count(agg[acc], d)
        if not d.get("policy_accession_id"):
            agg[acc]["no_policy"] = agg[acc].get("no_policy", 0) + 1
    url_status = {acc: check_url_liveness(dac["url"])} if dac.get("url") else {}
    domain_status = resolve_domains(set(contact_domains(dac.get("contacts"))))
    df = census.dac_table([dac], agg, url_status, domain_status, {}, {})   # policy text not available live
    return census.classify(census.apply_matching(df, matcher)).iloc[0]


def report(row, source):
    checks = continuity_checks(pd.DataFrame([row])).iloc[0]
    passed = sum(bool(checks[c]) for c in OBSERVABLE)
    title = " ".join(str(row["title"]).split())
    print(f"\n{row['accession_id']} — {title[:90]}")
    print(f"  source:      {source}")
    print(f"  governs:     {int(row['dataset_count'])} datasets ({int(row['released_dataset_count'])} released), "
          f"{int(row['total_samples']):,} samples")
    if isinstance(row.get("consortium_name"), str):
        succ = row.get("consortium_successor")
        status = row["consortium_status"] + (f", successor {succ}" if isinstance(succ, str) and succ else "")
        print(f"  consortium:  {row['consortium_name']} ({status}) — matched in {row['match_source']} text")
    else:
        print("  consortium:  none named in the record")
    doms = row["contact_domains"] if isinstance(row["contact_domains"], str) and row["contact_domains"] else "—"
    dstat = row["contact_domain_status"] if isinstance(row["contact_domain_status"], str) else "—"
    print(f"  contact:     {row['contact_status']}; domains: {doms} ({dstat})")
    print(f"  orphan type: {row['orphan_type']} — {ORPHAN_MEANING[row['orphan_type']]}")
    print(f"  continuity:  {passed}/{len(OBSERVABLE)} observable checks passed")
    for c, (label, why) in CHECKS.items():
        ok = bool(checks[c])
        print(f"    [{'PASS' if ok else 'FAIL'}] {label:<34} {'' if ok else '→ ' + FIX[c]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accessions", nargs="+", help="EGA DAC accession(s), e.g. EGAC00001000010")
    ap.add_argument("--live", action="store_true", help="query EGA now instead of the census results")
    ap.add_argument("--results", default=str(SCAN_RESULTS))
    args = ap.parse_args()

    if args.live:
        matcher = build_matcher(load_roster())
        for acc in args.accessions:
            row = live_row(acc, matcher)
            if row is None:
                print(f"\n{acc} — not found in EGA")
                continue
            report(row, "live EGA API (policy-text affiliation not available in live mode)")
        return

    df = pd.read_csv(args.results).set_index("accession_id", drop=False)
    for acc in args.accessions:
        if acc not in df.index:
            print(f"\n{acc} — not in {args.results}; try --live")
            continue
        report(df.loc[acc], f"census {args.results}")


if __name__ == "__main__":
    sys.exit(main())
