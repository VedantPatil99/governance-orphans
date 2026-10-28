# Governance Orphans

Code and derived data for *Governance Orphans: A Lifecycle Taxonomy and Population-Scale Audit of Data Access
Committees in the European Genome-phenome Archive* (Vedant Prashant Patil, School of Computer Science and
Engineering, VIT Vellore; BCSE318L Data Privacy case study).

The study asks what happens to Data Access Committee (DAC) oversight when a genomic research consortium ends,
transfers or changes status. It combines three reconstructed cases (ICGC, CSER, 1000 Genomes) with a census of all
4,901 DAC records, 4,880 policies and 21,764 datasets in the European Genome-phenome Archive (EGA), collected from
EGA's public metadata API on 7 October 2026.

## Reproduce

```
cd 06_Code
pip install -r requirements.txt
python -m pytest -q                           # 37 unit tests
python governance_decay_scanner.py            # live census (~45 min; EGA's /dacs endpoint is slow at high offsets)
python study_analysis.py                      # validation, statistics, sensitivity, continuity checks, figures
```

The raw snapshots are **not** in this repository because EGA's public DAC records contain named people's contact
email addresses. A live run of the scanner downloads a fresh snapshot (to `05_Data_and_Results/raw_snapshots_PRIVATE/`,
which is git-ignored) and stores SHA-256 checksums and frozen network checks next to it, so later `--cached` runs are
fully offline and exactly reproducible. Because the archive changes over time, a new snapshot will give numbers close
to, but not identical with, the published ones; the published outputs are in `05_Data_and_Results/`.

## Tools

| Command (from `06_Code/`) | What it does |
|---|---|
| `python governance_decay_scanner.py` | Live census: fetch all DACs, policies and datasets, save a snapshot, analyse |
| `python governance_decay_scanner.py --cached` | Re-analyse the saved snapshot offline |
| `python governance_decay_scanner.py --snapshot DIR --fetch-only` | Save a new snapshot only |
| `python compare_snapshots.py OLD NEW` | Governance changes between two snapshots |
| `python check_dac.py EGAC… [--live]` | Continuity report card (C1–C8 checklist, orphan type, fixes) for any committee |
| `python study_analysis.py` | Matcher validation, confidence intervals, record-age statistics, sensitivity analysis, figures |

## Layout

| Path | Contents |
|---|---|
| `06_Code/orphanscan/` | Package: `config.py` (constants and heuristics, each justified), `ega.py` (API client with fail-safe pagination), `contacts.py` (URL/DNS checks; only email domains leave this module), `roster.py` (consortium matching), `census.py` (governance join and O1–O5 classification), `continuity.py` (C1–C8 checklist), `charts.py` |
| `06_Code/tests/` | Unit tests; most pin down a bug found and fixed during the study |
| `06_Code/governance_orphans_study.ipynb` | Notebook running the whole pipeline |
| `05_Data_and_Results/consortium_roster.csv` | The 37-body consortium roster with status and source |
| `05_Data_and_Results/results/` | Per-DAC census table, policy-orphan datasets, statistics (`study_results.json`), sensitivity, continuity checks, snapshot comparison |
| `05_Data_and_Results/validation/` | Random-sample and precision validation sheets |
| `05_Data_and_Results/logs/` | Console output of every run reported in the paper |
| `04_Figures/` | Figures used in the paper |

## Taxonomy

O1 dissolution · O2 succession (with unfinished transfers) · O2b delisted · O3 contact orphan ·
O4 record/infrastructure retired · O5 policy orphan · plus record migration as a mechanism producing O3 and O5.

## Privacy and ethics

Only public metadata were used; no genomic data were accessed and no one was contacted. Only email **domains** are
resolved and stored, email addresses in free text are redacted, and no address appears in any output file (checked
by regex over every output and by a unit test). Test files use made-up addresses only.
