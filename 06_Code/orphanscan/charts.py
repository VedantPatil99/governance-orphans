"""Scanner charts (static figures: light surface, direct value labels)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from .config import FIGURES

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
TYPE_ORDER = ["O1_dissolution", "O2_succession", "O2b_delisted_from_GA4GH",
              "O3_contact_orphan", "O4_infrastructure_orphan", "no_orphan_signal_detected"]
TYPE_LABEL = {
    "O1_dissolution": "O1 Dissolution", "O2_succession": "O2 Succession",
    "O2b_delisted_from_GA4GH": "O2b Delisted (GA4GH)", "O3_contact_orphan": "O3 Contact orphan",
    "O4_infrastructure_orphan": "O4 Record deprecated", "no_orphan_signal_detected": "No orphan signal",
}
TYPE_COLOR = {
    "O1_dissolution": "#2a78d6", "O2_succession": "#eb6834", "O2b_delisted_from_GA4GH": "#1baf7a",
    "O3_contact_orphan": "#eda100", "O4_infrastructure_orphan": "#e87ba4", "no_orphan_signal_detected": "#c3c2b7",
}
CONTACT_ORDER = ["institutional", "single_individual", "freemail_only", "domain_unresolvable", "no_contact",
                 "external_reference_stub"]
CONTACT_LABEL = {
    "institutional": "Institutional / role address", "single_individual": "Single named individual",
    "freemail_only": "Personal webmail only", "domain_unresolvable": "Email domain unresolvable",
    "no_contact": "No contact published", "external_reference_stub": "Stub for non-EGA (NIH) DAC",
}


def style_axes(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def hbar(ax, labels, values, colors, fmt="{:,}"):
    bars = ax.barh(labels, values, color=colors, height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.invert_yaxis()
    vmax = max(values) if len(values) and max(values) > 0 else 1
    for b, v in zip(bars, values):
        ax.text(b.get_width() + vmax * 0.01, b.get_y() + b.get_height() / 2, fmt.format(v),
                va="center", fontsize=9, color=INK)
    ax.set_xlim(0, vmax * 1.15)
    style_axes(ax)


def make_charts(df):
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE})

    # 1 -- contact channel reachability
    counts = df["contact_status"].value_counts().reindex(CONTACT_ORDER, fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    colors = ["#2a78d6", "#eb6834", "#eda100", "#e34948", "#4a3aa7", "#c3c2b7"]
    hbar(ax, [CONTACT_LABEL[k] for k in counts.index], counts.values, colors)
    ax.set_title(f"How each EGA DAC can be contacted (n = {len(df):,} DACs)", loc="left", color=INK, fontsize=11)
    ax.set_xlabel("Number of DACs", color=INK2)
    plt.tight_layout()
    plt.savefig(FIGURES / "chart_reachability.png", dpi=200)
    plt.close(fig)

    # 2 -- orphan-type breakdown, by DACs and by datasets governed (two panels, one scale each)
    by_dac = df["orphan_type"].value_counts().reindex(TYPE_ORDER, fill_value=0)
    by_ds = df.groupby("orphan_type")["dataset_count"].sum().reindex(TYPE_ORDER, fill_value=0)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    labels = [TYPE_LABEL[k] for k in TYPE_ORDER]
    colors = [TYPE_COLOR[k] for k in TYPE_ORDER]
    hbar(axes[0], labels, by_dac.values, colors)
    axes[0].set_title("DACs", loc="left", color=INK, fontsize=10)
    hbar(axes[1], labels, by_ds.values, colors)
    axes[1].set_title("Datasets governed", loc="left", color=INK, fontsize=10)
    fig.suptitle("Governance orphan type breakdown", x=0.01, ha="left", color=INK, fontsize=11)
    plt.tight_layout()
    plt.savefig(FIGURES / "chart_orphan_types.png", dpi=200)
    plt.close(fig)

    # 3 -- top 15 DACs by datasets governed, coloured by orphan type
    top15 = df.sort_values("dataset_count", ascending=False).head(15)
    names = [f"{(t or a)[:48]}{'…' if len(t or a) > 48 else ''}  ({a})"
             for t, a in zip(top15["title"].fillna("").str.replace(r"\s+", " ", regex=True), top15["accession_id"])]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    hbar(ax, names, top15["dataset_count"].values, [TYPE_COLOR[t] for t in top15["orphan_type"]])
    present = [t for t in TYPE_ORDER if t in set(top15["orphan_type"])]
    ax.legend(handles=[Patch(color=TYPE_COLOR[t], label=TYPE_LABEL[t]) for t in present],
              loc="lower right", frameon=False, fontsize=9, labelcolor=INK2)
    ax.set_title("Top 15 DACs by datasets governed", loc="left", color=INK, fontsize=11)
    ax.set_xlabel("Datasets governed", color=INK2)
    plt.tight_layout()
    plt.savefig(FIGURES / "chart_top15_by_impact.png", dpi=200)
    plt.close(fig)
