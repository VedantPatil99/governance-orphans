"""
Study analysis for the Governance Orphans case study.

Runs on the outputs of governance_decay_scanner.py (no network access):
  governance_decay_scan_results.csv, policy_orphan_datasets.csv, validation_sample_labels.csv

  1. Matcher validation      precision / miss-rate with exact (Clopper-Pearson) intervals
  2. Headline proportions    with Wilson 95% intervals
  3. Record-age analysis     governance defects by accession cohort (chi-square, Cramer's V, trend)
  4. Sensitivity analysis    headline counts under alternative definitions
  5. Continuity validator    how many DAC records meet a minimum continuity standard
  6. Figures for the paper

Writes results/study_results.json, results/*.csv and fig_*.png.
Run:  python study_analysis.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from orphanscan.config import EGA_DAC_ID, FIGURES, O5_RESULTS, RESULTS, SCAN_RESULTS, TEST_NAME, VALIDATION
from orphanscan.continuity import OBSERVABLE, continuity_checks

OUT = RESULTS
os.makedirs(OUT, exist_ok=True)

INK, INK2, GRID, SURFACE, AXIS = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"

df = pd.read_csv(SCAN_RESULTS)
o5 = pd.read_csv(O5_RESULTS)
labels = pd.read_csv(VALIDATION / "validation_sample_labels.csv")
results = {}


def wilson(k, n):
    lo, hi = proportion_confint(k, n, alpha=0.05, method="wilson")
    return {"k": int(k), "n": int(n), "p": round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def exact(k, n):
    lo, hi = proportion_confint(k, n, alpha=0.05, method="beta")
    return {"k": int(k), "n": int(n), "p": round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}


# EGA DACs proper (exclude the 16 non-EGAC stubs/blank record)
ega = df[df["accession_id"].astype(str).str.fullmatch(EGA_DAC_ID.pattern)].copy()
ega["is_test_like"] = ega["title"].fillna("").str.contains(TEST_NAME)
ega["no_policy_link_only"] = (ega["datasets_without_policy_link"] > 0) & (ega["datasets_without_policy_link"] == ega["dataset_count"])
ega["governs_data"] = ega["dataset_count"] > 0

# ---------------------------------------------------------------------------
# 1. Matcher validation
# ---------------------------------------------------------------------------
own_text = df[(df["match_source"] == "dac") & (df["consortium_name"] != "European Genome-phenome Archive")]
# precision set reviewed by hand: all own-text, non-generic matches judged correct (see notes in README)
precision = exact(len(own_text), len(own_text))
misses = int(labels["true_roster_member"].sum())
miss_rate = exact(misses, len(labels))
n_unmatched = int((ega["consortium_name"].isna()).sum())
upper_missed = int(round(miss_rate["ci95"][1] * n_unmatched))
domain_check = {"consortium_domain_DACs": 26, "caught_by_matcher": 26,
                "domains": ["icgc.org (24)", "icgc-argo.org (1)", "h3africa.org (1)"]}
results["validation"] = {
    "precision_own_text_matches": precision,
    "random_unmatched_sample_miss_rate": miss_rate,
    "unmatched_population": n_unmatched,
    "missed_DACs_upper_bound_95": upper_missed,
    "independent_domain_check": domain_check,
    "note": "Labels judged from DAC title, description and own policy titles. Membership that a record never "
            "states is unobservable to both matcher and labeller -- this is the identifiability gap itself.",
}

# ---------------------------------------------------------------------------
# 2. Headline proportions
# ---------------------------------------------------------------------------
released_gov = ega[ega["released_dataset_count"] > 0]
named = ega[(ega["match_source"] == "dac") & (ega["consortium_name"] != "European Genome-phenome Archive")
            & (ega["roster_source"] != "scan_discovered")]
o5_live = o5[(o5["is_released"] == True) & (o5["is_deprecated"] != True)]
results["headline"] = {
    "ega_dacs": int(len(ega)),
    "dacs_governing_data": wilson(ega["governs_data"].sum(), len(ega)),
    "empty_dacs": wilson((~ega["governs_data"]).sum(), len(ega)),
    "self_identify_roster_consortium": wilson(len(named), len(ega)),
    "single_named_individual_among_released_governing": wilson(
        (released_gov["contact_status"] == "single_individual").sum(), len(released_gov)),
    "no_or_dead_contact_among_governing": wilson(ega.loc[ega["governs_data"], "O3_contact_orphan"].sum(),
                                                 ega["governs_data"].sum()),
    "controlled_datasets_without_policy": wilson(len(o5), 21764),
    "o5_released_live": {"datasets": int(len(o5_live)), "samples": int(o5_live["num_samples"].fillna(0).sum())},
    "o5_no_public_path_released": {
        "datasets": int((o5_live["o5_subtype"] != "recoverable_secondary_route").sum()),
        "samples": int(o5_live.loc[o5_live["o5_subtype"] != "recoverable_secondary_route", "num_samples"].fillna(0).sum())},
    "test_like_dacs": int(ega["is_test_like"].sum()),
    "test_like_dacs_with_released_data": int((ega["is_test_like"] & (ega["released_dataset_count"] > 0)).sum()),
}

# ---------------------------------------------------------------------------
# 3. Record age: accession cohort (ids are issued sequentially)
# ---------------------------------------------------------------------------
def cohort(acc):
    if acc.startswith(("EGAC00000000", "EGAC01")):
        return "0 Legacy"
    if acc.startswith("EGAC5"):
        return "5 EGAC5 (current system)"
    return {"EGAC00001000": "1 EGAC1-000", "EGAC00001001": "2 EGAC1-001",
            "EGAC00001002": "3 EGAC1-002", "EGAC00001003": "4 EGAC1-003"}.get(acc[:12], "?")


ega["cohort"] = ega["accession_id"].map(cohort)
ega["defect_hard"] = (ega["O3_contact_orphan"] | ega["O4_infrastructure_orphan"] | ega["no_policy_link_only"]
                      | ega["lifecycle_class"].isin(["O1_dissolution", "O2_succession"]))
ega["single_person"] = ega["contact_status"] == "single_individual"
gov = ega[ega["governs_data"]]
by = gov.groupby("cohort").agg(dacs=("accession_id", "size"), defect=("defect_hard", "sum"),
                               single_person=("single_person", "sum"), datasets=("dataset_count", "sum"))
by["defect_rate"] = by["defect"] / by["dacs"]
by["single_person_rate"] = by["single_person"] / by["dacs"]
by.to_csv(os.path.join(OUT, "defects_by_cohort.csv"))

ct = pd.crosstab(gov["cohort"], gov["defect_hard"])
chi2, p_chi, dof, _ = stats.chi2_contingency(ct)
cramer = float(np.sqrt(chi2 / (ct.values.sum() * (min(ct.shape) - 1))))
legacy = gov["cohort"] == "0 Legacy"
fisher_tab = [[int(gov.loc[legacy, "defect_hard"].sum()), int((~gov.loc[legacy, "defect_hard"]).sum())],
              [int(gov.loc[~legacy, "defect_hard"].sum()), int((~gov.loc[~legacy, "defect_hard"]).sum())]]
odds, p_fisher = stats.fisher_exact(fisher_tab)
# trend across the ordered cohorts (Spearman on cohort rank vs defect)
rank = gov["cohort"].str[0].astype(int)
rho, p_trend = stats.spearmanr(rank, gov["defect_hard"].astype(int))
ct2 = pd.crosstab(gov["cohort"], gov["single_person"])
chi2_s, p_s, _, _ = stats.chi2_contingency(ct2)
rho_s, p_trend_s = stats.spearmanr(rank, gov["single_person"].astype(int))
results["record_age"] = {
    "table": json.loads(by.round(4).to_json(orient="index")),
    "hard_defect_chi2": {"chi2": round(chi2, 2), "dof": int(dof), "p": float(p_chi), "cramers_v": round(cramer, 3)},
    "legacy_vs_rest_fisher": {"table": fisher_tab, "odds_ratio": None if np.isinf(odds) else round(float(odds), 2),
                              "p": float(p_fisher)},
    "hard_defect_trend_spearman": {"rho": round(float(rho), 3), "p": float(p_trend)},
    "single_person_chi2": {"chi2": round(chi2_s, 2), "p": float(p_s)},
    "single_person_trend_spearman": {"rho": round(float(rho_s), 3), "p": float(p_trend_s)},
}

# ---------------------------------------------------------------------------
# 4. Sensitivity analysis
# ---------------------------------------------------------------------------
def counts(frame, o3_extra=None, drop=None):
    f = frame if drop is None else frame[~drop]
    o3 = f["O3_contact_orphan"].copy()
    if o3_extra is not None:
        o3 = o3 | o3_extra.loc[f.index]
    lc = f["lifecycle_class"]
    out = {}
    for name, mask in (("O1", lc == "O1_dissolution"), ("O2", lc == "O2_succession"),
                       ("O3", o3 & ~lc.isin(["O1_dissolution", "O2_succession"])),
                       ("O4", f["O4_infrastructure_orphan"] & ~o3 & ~lc.isin(["O1_dissolution", "O2_succession"]))):
        out[name] = {"dacs": int(mask.sum()), "datasets": int(f.loc[mask, "dataset_count"].sum()),
                     "samples": int(f.loc[mask, "total_samples"].sum())}
    any_orphan = (lc.isin(["O1_dissolution", "O2_succession", "O2b_delisted_from_GA4GH"]) | o3
                  | f["O4_infrastructure_orphan"])
    out["any_orphan_share_of_datasets"] = round(f.loc[any_orphan, "dataset_count"].sum() / f["dataset_count"].sum(), 4)
    return out


unknown_dns = ega["contact_domain_status"].fillna("").str.contains("unknown") & \
    ~ega["contact_domain_status"].fillna("").str.contains("live")
variants = {
    "V0 baseline": counts(ega),
    "V1 single named individual counts as O3": counts(ega, o3_extra=ega["contact_status"] == "single_individual"),
    "V2 personal webmail counts as O3": counts(ega, o3_extra=ega["contact_status"] == "freemail_only"),
    "V3 DNS timeout treated as dead": counts(ega, o3_extra=unknown_dns),
    "V4 exclude scan-discovered consortia": counts(
        ega.assign(lifecycle_class=np.where(ega["roster_source"] == "scan_discovered", "unmatched",
                                            ega["lifecycle_class"]))),
    "V5 exclude test-like DACs": counts(ega, drop=ega["is_test_like"]),
}
sens = pd.DataFrame({k: {f"{o}_{m}": v[o][m] for o in ("O1", "O2", "O3", "O4") for m in ("dacs", "datasets")}
                     | {"any_orphan_share_of_datasets": v["any_orphan_share_of_datasets"]}
                     for k, v in variants.items()}).T
sens.to_csv(os.path.join(OUT, "sensitivity.csv"))
results["sensitivity"] = variants

# ---------------------------------------------------------------------------
# 5. Continuity validator: minimum fields a DAC record needs to survive its parent body
# ---------------------------------------------------------------------------
checks = continuity_checks(ega)
checks.index = ega["accession_id"]
checks.to_csv(os.path.join(OUT, "continuity_checks.csv"))
gov_checks = checks[ega["governs_data"].values]
observable = OBSERVABLE
results["continuity"] = {
    "pass_rate_each_check_governing_dacs": {c: wilson(gov_checks[c].sum(), len(gov_checks)) for c in checks.columns},
    "pass_all_observable_checks": wilson(gov_checks[observable].all(axis=1).sum(), len(gov_checks)),
    "fail_at_least_one_observable": wilson((~gov_checks[observable].all(axis=1)).sum(), len(gov_checks)),
    "note": "C7/C8 fail for every record because the EGA DAC schema has no field for a parent body or successor.",
}

with open(os.path.join(OUT, "study_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, default=str)

# ---------------------------------------------------------------------------
# 6. Figures
# ---------------------------------------------------------------------------
plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})


def style(ax, grid="x"):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis=grid, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def label_bars(ax, bars, values, fmt, vmax):
    for b, v in zip(bars, values):
        ax.text(b.get_width() + vmax * 0.012, b.get_y() + b.get_height() / 2, fmt(v), va="center", fontsize=9, color=INK)


# Fig A -- orphan types by datasets and samples affected (O1-O5), "no signal" stated in caption, not plotted
lc = ega["lifecycle_class"]
cats = [
    ("O1 Dissolution", lc == "O1_dissolution", BLUE),
    ("O2 Succession", lc == "O2_succession", ORANGE),
    ("O2b Delisted (GA4GH)", lc == "O2b_delisted_from_GA4GH", AQUA),
    ("O3 Contact orphan", (ega["orphan_type"] == "O3_contact_orphan"), YELLOW),
    ("O4 Record deprecated", (ega["orphan_type"] == "O4_infrastructure_orphan"), MAGENTA),
]
names = [c[0] for c in cats] + ["O5 Policy orphan (no DAC)"]
ds_vals = [int(ega.loc[m, "dataset_count"].sum()) for _, m, _ in cats] + [len(o5)]
sm_vals = [int(ega.loc[m, "total_samples"].sum()) for _, m, _ in cats] + [int(o5["num_samples"].fillna(0).sum())]
colors = [c[2] for c in cats] + ["#4a3aa7"]
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
for ax, vals, title in ((axes[0], ds_vals, "Datasets affected"), (axes[1], sm_vals, "Samples affected")):
    bars = ax.barh(names, vals, color=colors, height=0.6, edgecolor=SURFACE, linewidth=2)
    vmax = max(vals)
    label_bars(ax, bars, vals, lambda v: f"{v:,}", vmax)
    ax.set_xlim(0, vmax * 1.18)
    ax.set_title(title, loc="left", color=INK, fontsize=10)
    style(ax)
axes[0].invert_yaxis()
total_ds = int(ega["dataset_count"].sum())
fig.suptitle(f"Governance orphan types in EGA (census of {len(ega):,} DACs, {21764:,} datasets)",
             x=0.01, ha="left", color=INK, fontsize=11)
plt.tight_layout()
plt.savefig(FIGURES / "fig_orphan_impact.png", dpi=200)
plt.close(fig)

# Fig B -- defect and single-person rates by record cohort
by_plot = by.copy()
by_plot.index = ["Legacy", "EGAC1\n000xxx", "EGAC1\n001xxx", "EGAC1\n002xxx", "EGAC1\n003xxx", "EGAC5\n(current)"]
x = np.arange(len(by_plot))
fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))
for ax, col, color, title in ((axes[0], "defect_rate", ORANGE, "Hard governance defect (O1-O4 or no policy link)"),
                              (axes[1], "single_person_rate", BLUE, "Single named individual as only contact")):
    bars = ax.bar(x, by_plot[col] * 100, color=color, width=0.6, edgecolor=SURFACE, linewidth=2)
    for b, v, n in zip(bars, by_plot[col] * 100, by_plot["dacs"]):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1, f"{v:.0f}%", ha="center", fontsize=11, color=INK)
    ax.set_xticks(x, [f"{i}\nn={n}" for i, n in zip(by_plot.index, by_plot["dacs"])], fontsize=10)
    ax.set_ylabel("% of DACs governing data", color=INK2, fontsize=10.5)
    ax.set_ylim(0, max(by_plot[col] * 100) * 1.2 + 2)
    ax.set_title(title, loc="left", color=INK, fontsize=11.5)
    style(ax, grid="y")
    ax.tick_params(labelsize=10)   # larger than style()'s default: these labels carry the cohort sizes
fig.suptitle("Governance defects by record age (accession cohorts, oldest -> newest)", x=0.01, ha="left",
             color=INK, fontsize=11)
plt.tight_layout()
plt.savefig(FIGURES / "fig_defects_by_cohort.png", dpi=200)
plt.close(fig)

# Fig C -- continuity checklist pass rates
cc = results["continuity"]["pass_rate_each_check_governing_dacs"]
cnames = {"C1_reachable_contact": "C1 Reachable contact", "C2_role_or_institutional_contact": "C2 Role / institutional contact",
          "C3_redundant_contacts": "C3 Two or more contacts", "C4_self_description": "C4 Describes itself",
          "C5_policy_linked_datasets": "C5 Datasets linked via policy", "C6_live_status": "C6 Live, non-test record",
          "C7_parent_body_field": "C7 Names parent body (no field)", "C8_successor_field": "C8 Names successor (no field)"}
vals = [cc[k]["p"] * 100 for k in cnames]
fig, ax = plt.subplots(figsize=(8.5, 4))
bars = ax.barh(list(cnames.values()), vals, color=[AQUA if v >= 90 else (YELLOW if v >= 50 else ORANGE) for v in vals],
               height=0.6, edgecolor=SURFACE, linewidth=2)
label_bars(ax, bars, vals, lambda v: f"{v:.1f}%", 100)
ax.invert_yaxis()
ax.set_xlim(0, 112)
ax.set_xlabel("% of DACs governing data that pass", color=INK2)
ax.set_title(f"DAC record continuity checklist (n = {len(gov_checks):,} DACs governing data)", loc="left",
             color=INK, fontsize=11)
style(ax)
plt.tight_layout()
plt.savefig(FIGURES / "fig_continuity_checklist.png", dpi=200)
plt.close(fig)

print(json.dumps(results, indent=2, default=str))
