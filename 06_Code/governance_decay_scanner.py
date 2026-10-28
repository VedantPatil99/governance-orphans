"""
Governance Decay Scanner — census of governance orphans in the European Genome-phenome Archive (EGA)

Fetches every Data Access Committee (DAC), policy and dataset record from the EGA public metadata API,
joins dataset -> policy -> DAC (with a dataset -> files -> DAC fallback), assesses whether each DAC can
still be contacted (URL liveness and email-domain DNS; only domains are stored, never addresses),
matches each DAC against the consortium roster, and classifies it on two axes:
  lifecycle (roster status):   O1 dissolution / O2 succession / O2b delisted
  observable (every DAC):      O3 contact orphan / O4 deprecated record
plus O5 (policy orphan) at dataset level.

Run:
  python governance_decay_scanner.py                    live fetch; saves a raw snapshot, then analyses it
  python governance_decay_scanner.py --cached           re-analyse the saved snapshot (fully offline)
  python governance_decay_scanner.py --snapshot DIR --fetch-only    save a new snapshot only (for comparisons)
Folders are set in orphanscan/config.py: reads 05_Data_and_Results/consortium_roster.csv, writes
05_Data_and_Results/results/*.csv and three charts to 04_Figures/.
"""
import argparse

import pandas as pd

from orphanscan import census, log
from orphanscan.charts import TYPE_ORDER, make_charts
from orphanscan.config import DEFAULT_SNAPSHOT, FIGURES, O5_RESULTS, RESULTS, SCAN_RESULTS
from orphanscan.contacts import contact_checks
from orphanscan.ega import connectivity_check, fetch_or_load, resolve_orphan_dacs
from orphanscan.roster import build_matcher, load_roster


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cached", action="store_true", help="re-analyse the saved snapshot instead of fetching")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT, help="snapshot folder (default: %(default)s)")
    ap.add_argument("--fetch-only", action="store_true", help="save a raw snapshot and stop (no analysis/outputs)")
    ap.add_argument("--recheck-contacts", action="store_true", help="re-run URL/DNS checks instead of the frozen ones")
    return ap.parse_args()


def log_o5_summary(o5):
    log(f"O5 policy orphans: {len(o5)} datasets, {int(o5['num_samples'].fillna(0).sum())} samples "
        f"(released: {o5['is_released'].sum()}, deprecated: {o5['is_deprecated'].sum()}, "
        f"controlled: {(o5['access_type'] == 'controlled').sum()})")
    rel = o5[o5["is_released"] == True]
    live = rel[rel["is_deprecated"] != True]
    log(f"  released and not deprecated (requestable with no committee on record): {len(live)} datasets, "
        f"{int(live['num_samples'].fillna(0).sum())} samples")
    log("  O5 subtype (all | released & not deprecated):")
    log(pd.concat([o5.groupby("o5_subtype").agg(datasets=("accession_id", "size"), samples=("num_samples", "sum")),
                   live.assign(o5_subtype=o5.loc[live.index, "o5_subtype"]).groupby("o5_subtype")
                   .agg(live_datasets=("accession_id", "size"), live_samples=("num_samples", "sum"))],
                  axis=1).fillna(0).astype(int).to_string() + "\n")


def log_summary(df, datasets, roster, retrieval_date):
    with pd.option_context("display.max_colwidth", 50, "display.width", 220):
        for label, pat in (("ICGC / ICGC ARGO", "ICGC|International Cancer Genome"), ("ClinGen", "Clinical Genome"),
                           ("CSER", "CSER"), ("1000 Genomes", "1000 Genomes")):
            s = df[df["consortium_name"].str.contains(pat, case=False, na=False)]
            log(f"Sanity check — {label}: {len(s)} DACs, {s['dataset_count'].sum()} datasets")
            if len(s):
                log(s.sort_values("dataset_count", ascending=False)[
                    ["accession_id", "title", "dataset_count", "contact_status", "consortium_name", "orphan_type"]
                ].head(12).to_string())
            log()
    total = len(df)
    log(f"Retrieval date: {retrieval_date}")
    log(f"Total DACs scanned: {total}  (released: {df['is_released'].sum()}, "
        f"governing >=1 dataset: {(df['dataset_count'] > 0).sum()})")
    log(f"Datasets attributed to a DAC: {df['dataset_count'].sum()} / {len(datasets)}\n")
    for title, col in (("URL status breakdown:", "url_status"), ("Contact status breakdown:", "contact_status"),
                       ("Lifecycle class:", "lifecycle_class")):
        log(title)
        log(df[col].value_counts().to_string() + "\n")
    log(f"O3 contact-orphan flags: {df['O3_contact_orphan'].sum()}   "
        f"O4 infrastructure-orphan flags: {df['O4_infrastructure_orphan'].sum()}\n")
    log("Primary orphan type (DACs | datasets | samples):")
    summary = df.groupby("orphan_type").agg(dacs=("accession_id", "size"), datasets=("dataset_count", "sum"),
                                            samples=("total_samples", "sum"))
    log(summary.reindex([t for t in TYPE_ORDER if t in summary.index]).to_string() + "\n")
    n_matched = df["consortium_name"].notna().sum()
    log(f"Match rate against the {len(roster)}-row roster: {n_matched} / {total} ({100 * n_matched / total:.1f}%)\n")


def main():
    args = parse_args()
    snap, use_cache = args.snapshot, args.cached
    if not use_cache:
        connectivity_check()

    # Step 1-3 — fetch (or load) the three populations
    log("Fetching all DACs...")
    dacs, retrieval_date = fetch_or_load(snap, "/dacs", "dacs", use_cache)
    log(f"Retrieval date: {retrieval_date}")
    log(f"Done. Total DACs: {len(dacs)}\n")
    log("Fetching all policies...")
    policies, _ = fetch_or_load(snap, "/policies", "policies", use_cache)
    log(f"Done. Total policies: {len(policies)}")
    log("Fetching all datasets (this is usually the biggest endpoint)...")
    datasets, _ = fetch_or_load(snap, "/datasets", "datasets", use_cache)
    log(f"Done. Total datasets: {len(datasets)}")
    if args.fetch_only:
        log(f"Snapshot saved to {snap}/ (--fetch-only: no analysis).")
        return

    # Governance join: dataset -> policy -> DAC
    policy_to_dac, policy_text_by_dac, policy_count_by_dac = census.index_policies(policies)
    log(f"Policies with a DAC link: {sum(1 for v in policy_to_dac.values() if v)} / {len(policy_to_dac)}")
    agg, unmatched = census.governance_join(datasets, policy_to_dac)
    log(f"Datasets with no resolvable DAC (via policy link): {unmatched} / {len(datasets)}\n")

    # O5 policy orphans, and the second route to governance: dataset -> files -> DAC
    o5 = census.policy_orphans(datasets, policy_to_dac)
    if len(o5):
        recovered = resolve_orphan_dacs(snap, list(o5["accession_id"]), use_cache)
        o5 = census.annotate_policy_orphans(o5, recovered)
        log(f"  malformed dataset accessions among O5: {int(o5['malformed_accession'].sum())}")
        census.credit_secondary_route(agg, datasets, recovered)
    RESULTS.mkdir(parents=True, exist_ok=True)
    o5.to_csv(O5_RESULTS, index=False)
    if len(o5):
        log_o5_summary(o5)

    # Step 4 — contact assessment (frozen into the snapshot after the first measurement)
    url_status, domain_status = contact_checks(snap, dacs, use_cache, recheck=args.recheck_contacts)
    log(f"  live: {sum(v == 'live' for v in domain_status.values())}, "
        f"dead: {sum(v == 'dead' for v in domain_status.values())}, "
        f"unknown/timeout: {sum(v == 'unknown' for v in domain_status.values())}\n")

    # Step 5-6 — per-DAC table, roster match, classification
    roster = load_roster()
    df = census.dac_table(dacs, agg, url_status, domain_status, policy_text_by_dac, policy_count_by_dac)
    df = census.apply_matching(df, build_matcher(roster))
    log(f"Matched to a known consortium: {df['consortium_name'].notna().sum()} / {len(df)} "
        f"(via DAC text: {(df['match_source'] == 'dac').sum()}, via policy text: {(df['match_source'] == 'policy').sum()})\n")
    df = census.classify(df)

    # Step 7-9 — sanity checks, summary, outputs
    log_summary(df, datasets, roster, retrieval_date)
    df.to_csv(SCAN_RESULTS, index=False)
    make_charts(df)
    log(f"Wrote {SCAN_RESULTS.name}, {O5_RESULTS.name} -> {RESULTS}; charts -> {FIGURES}")


if __name__ == "__main__":
    main()
