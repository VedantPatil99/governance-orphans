"""
Unit tests for the governance-orphan scanner. Every test pins down a rule the study's results depend on,
most of them a bug found and fixed during the study. Run:  python -m pytest -q
"""
import json

import pandas as pd
import pytest

from orphanscan import census
from orphanscan.config import TEST_NAME
from orphanscan.contacts import assess_contact, contact_domains, redact
from orphanscan.roster import MATCH_COLUMNS, NO_MATCH, build_matcher


def roster(*rows):
    df = pd.DataFrame(rows, columns=["consortium_name", "match_keywords", "status", "end_date", "successor",
                                     "roster_source"])
    df["match_keywords"] = df["match_keywords"].fillna("")
    return df


ROSTER = roster(
    ("European Genome-phenome Archive", "EGA,European Genome-phenome Archive", "active", None, None, "ga4gh"),
    ("ICGC ARGO", "ARGO,ICGC ARGO", "active", None, None, "ga4gh"),
    ("International Cancer Genome Consortium", "ICGC,International Cancer Genome", "ended", "2024-06", "ICGC ARGO",
     "phase_a_case"),
    ("Clinical Genome Resource", "ClinGen,Clinical Genome Resource", "active", None, None, "ga4gh"),
    ("Genomics England", "Genomics England,100000 Genomes,100,000 Genomes", "active", None, None, "ga4gh"),
    ("GABRIEL Consortium", "Gabriel Consortium,GABRIEL", "ended", "2010-08", None, "scan_discovered"),
    ("Australian Genomics", "Australian Genomics", "past_driver_project", None, None, "ga4gh"),
)
match = build_matcher(ROSTER)


def name(result):
    return dict(zip(MATCH_COLUMNS, result))["consortium_name"]


# --- roster matching ---------------------------------------------------------------------------

class TestMatching:
    def test_whole_word_only(self):
        # substring matching once made "EGA" hit "legal" and "ARGO" hit "embargo"
        assert match("Legal embargo applies to this cohort", "") == NO_MATCH

    def test_specific_consortium_beats_generic_archive(self):
        # the bug that mis-filed ICGC's 807-dataset DACO under EGA
        assert name(match("ICGC Data Access Compliance Office for data held at the EGA", "")) == \
            "International Cancer Genome Consortium"

    def test_longer_overlapping_name_wins(self):
        # "ICGC" sits inside "ICGC ARGO": the successor, not the ended consortium
        assert name(match("ICGC ARGO Data Access Office", "")) == "ICGC ARGO"

    def test_acronyms_are_case_sensitive(self):
        assert match("Lab of clingen studies", "") == NO_MATCH
        assert name(match("ClinGen curation committee", "")) == "Clinical Genome Resource"

    def test_email_addresses_are_not_membership(self):
        # "x@clingen.gu.se" once matched ClinGen
        assert match("Contact x.y@clingen.gu.se for access", "") == NO_MATCH

    def test_thousands_separator_is_not_a_keyword_split(self):
        # "100,000 Genomes" once split into "100" and "000 Genomes"
        assert match("DAC for a 100 sample cohort", "") == NO_MATCH
        assert name(match("100,000 Genomes Project access", "")) == "Genomics England"

    def test_dac_text_beats_policy_text(self):
        r = dict(zip(MATCH_COLUMNS, match("GABRIEL Consortium DAC", "Follows ICGC guidelines")))
        assert (r["consortium_name"], r["match_source"]) == ("GABRIEL Consortium", "dac")

    def test_policy_only_hit_is_recorded_as_policy_source(self):
        r = dict(zip(MATCH_COLUMNS, match("UHN Genomics DAC", "ICGC policy")))
        assert r["match_source"] == "policy"


# --- classification ----------------------------------------------------------------------------

def classified(dac_text, policy_text="", o3=False, o4=False):
    row = dict(zip(MATCH_COLUMNS, match(dac_text, policy_text)))
    row.update({"O3_contact_orphan": o3, "O4_infrastructure_orphan": o4})
    row["lifecycle_class"] = census.lifecycle_class(row)
    return row["lifecycle_class"], census.primary_orphan_type(row)


class TestClassification:
    def test_ended_without_successor_is_o1(self):
        assert classified("Gabriel Consortium Data Access Committee") == ("O1_dissolution", "O1_dissolution")

    def test_ended_with_successor_is_o2(self):
        assert classified("ICGC DACO") == ("O2_succession", "O2_succession")

    def test_past_driver_project_is_o2b(self):
        assert classified("Australian Genomics DAC")[0] == "O2b_delisted_from_GA4GH"

    def test_policy_only_affiliation_is_not_orphaned(self):
        # institution-run committee that merely follows ICGC policy survives ICGC's end
        assert classified("UHN Genomics DAC", "ICGC policy") == ("affiliated_institutional_DAC",
                                                                 "no_orphan_signal_detected")

    def test_generic_archive_mention_is_not_a_consortium(self):
        assert classified("Access to public datasets in the EGA")[0] == "archive_generic_DAC"

    def test_lifecycle_label_takes_precedence_over_contact(self):
        assert classified("Gabriel Consortium DAC", o3=True)[1] == "O1_dissolution"

    def test_observable_axis_applies_to_unmatched_dacs(self):
        assert classified("Some hospital DAC", o3=True) == ("unmatched", "O3_contact_orphan")
        assert classified("Some hospital DAC", o4=True) == ("unmatched", "O4_infrastructure_orphan")


# --- contact assessment ------------------------------------------------------------------------

def person(email):
    return {"email": email}


class TestContacts:
    LIVE = {"uni.edu": "live", "gmail.com": "live", "gone.org": "dead"}

    def test_no_contact_is_o3_unless_url_works(self):
        assert assess_contact([], "no_url", self.LIVE) == ("no_contact", True)
        assert assess_contact([], "reachable", self.LIVE) == ("institutional", False)

    def test_all_domains_dead_is_o3(self):
        assert assess_contact([person("a@gone.org")], "no_url", self.LIVE) == ("domain_unresolvable", True)

    def test_one_live_domain_is_enough(self):
        assert assess_contact([person("a@gone.org"), person("b@uni.edu")], "no_url", self.LIVE)[1] is False

    def test_dns_timeout_is_not_counted_as_dead(self):
        assert assess_contact([person("a@slow.net")], "no_url", self.LIVE)[1] is False

    def test_personal_webmail(self):
        assert assess_contact([person("x@gmail.com")], "no_url", self.LIVE) == ("freemail_only", False)

    def test_single_named_person_vs_role_mailbox(self):
        assert assess_contact([person("jane.doe@uni.edu")], "no_url", self.LIVE)[0] == "single_individual"
        assert assess_contact([person("dac@uni.edu")], "no_url", self.LIVE)[0] == "institutional"

    def test_contact_domains_are_lowercased_and_cleaned(self):
        assert contact_domains([person("A@Uni.EDU."), {"email": None}, {}]) == ["uni.edu"]


# --- personal data -----------------------------------------------------------------------------

class TestPrivacy:
    def test_redact_removes_every_address(self):
        out = redact("Contact jane.doe@uni.edu or dac-office+eu@inst.ac.uk today")
        assert "@" not in out and out.count("[email redacted]") == 2

    def test_redact_leaves_non_text_alone(self):
        assert redact(None) is None

    def test_dac_table_never_stores_addresses(self):
        dacs = [{"accession_id": "EGAC00001000001", "title": "DAC (contact a.b@uni.edu)",
                 "description": "Write to c@uni.edu", "contacts": [person("a.b@uni.edu")]}]
        df = census.dac_table(dacs, {}, {}, {"uni.edu": "live"}, {}, {})
        text = df.astype(str).to_csv()
        assert "a.b@uni.edu" not in text and "c@uni.edu" not in text
        assert df.loc[0, "contact_domains"] == "uni.edu"


# --- governance join ---------------------------------------------------------------------------

class TestGovernanceJoin:
    POLICIES = [{"accession_id": "P1", "dac_accession_id": "EGAC00001000001", "title": "Policy one"}]
    DATASETS = [
        {"accession_id": "EGAD00000000001", "policy_accession_id": "P1", "is_released": True,
         "access_type": "controlled", "num_samples": 10},
        {"accession_id": "EGAD00000000002", "policy_accession_id": None, "is_released": True,
         "access_type": "controlled", "num_samples": 5},
    ]

    def test_dataset_policy_dac_join_and_o5(self):
        p2d, _, _ = census.index_policies(self.POLICIES)
        agg, unmatched = census.governance_join(self.DATASETS, p2d)
        assert agg["EGAC00001000001"]["n"] == 1 and agg["EGAC00001000001"]["samples"] == 10
        assert unmatched == 1
        assert list(census.policy_orphans(self.DATASETS, p2d)["accession_id"]) == ["EGAD00000000002"]

    def test_secondary_route_credits_the_recovered_dac(self):
        p2d, _, _ = census.index_policies(self.POLICIES)
        agg, _ = census.governance_join(self.DATASETS, p2d)
        recovered = {"EGAD00000000002": {"n_files": 2, "dacs": ["EGAC00000000014"]}}
        census.credit_secondary_route(agg, self.DATASETS, recovered)
        assert agg["EGAC00000000014"] == {"n": 1, "released": 1, "deprecated": 0, "controlled": 1, "samples": 5,
                                          "no_policy": 1}

    def test_non_ega_stub_is_not_a_contact_orphan(self):
        df = census.dac_table([{"accession_id": "63", "title": "NCI/NHGRI TCGA DAC", "contacts": None}],
                              {}, {}, {}, {}, {})
        assert (df.loc[0, "contact_status"], df.loc[0, "O3_contact_orphan"]) == ("external_reference_stub", False)

    def test_deprecated_when_every_dataset_is_deprecated(self):
        agg = {"EGAC00001000001": {"n": 2, "released": 0, "deprecated": 2, "controlled": 2, "samples": 0}}
        df = census.dac_table([{"accession_id": "EGAC00001000001", "title": "A DAC", "contacts": []}],
                              agg, {}, {}, {}, {})
        assert bool(df.loc[0, "O4_infrastructure_orphan"]) is True


# --- record hygiene ----------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Placeholder DAC", True), ("Dummy DAC", True), ("Obsolete DAC - Do Not Use", True), ("test dac 4", True),
    ("Evaluation of commercial Guardant360 ctDNA test in prostate cancer", False),
    ("Testis tumour sequencing DAC", False),
])
def test_test_record_detection(title, expected):
    assert bool(TEST_NAME.search(title)) is expected


# --- secondary routes and snapshot comparison --------------------------------------------------

def test_policy_orphan_subtypes():
    o5 = pd.DataFrame({"accession_id": ["EGAD00000000044", "EGAD00000000099"]})
    recovered = {
        "EGAD00000000044": {"n_files": 0, "dacs_direct": ["EGAC00000000008"], "dacs_files": [],
                            "dacs": ["EGAC00000000008"]},
        "EGAD00000000099": {"n_files": 0, "dacs_direct": [], "dacs_files": [], "dacs": []},
    }
    out = census.annotate_policy_orphans(o5, recovered)
    assert list(out["o5_subtype"]) == ["recoverable_secondary_route", "no_public_path"]
    assert out.loc[0, "dac_direct"] == "EGAC00000000008"


def snapshot(date, dacs, policies, datasets):
    return {"date": date, "dacs": {d["accession_id"]: d for d in dacs},
            "policies": {p["accession_id"]: p for p in policies},
            "datasets": {d["accession_id"]: d for d in datasets}}


def test_compare_snapshots_detects_governance_change():
    from compare_snapshots import compare
    old = snapshot("2026-10-07",
                   [{"accession_id": "EGAC00000000001", "title": "Old DAC", "contacts": [person("a@uni.edu")]}],
                   [{"accession_id": "P1", "dac_accession_id": "EGAC00000000001"},
                    {"accession_id": "P2", "dac_accession_id": "EGAC00000000001"}],
                   [{"accession_id": "D1", "policy_accession_id": None},
                    {"accession_id": "D2", "policy_accession_id": "P1"},
                    {"accession_id": "D3", "policy_accession_id": "P2"}])
    new = snapshot("2026-10-09",
                   [{"accession_id": "EGAC00000000001", "title": "Old DAC", "contacts": [person("a@new.org")]},
                    {"accession_id": "EGAC00000000002", "title": "New DAC", "contacts": [person("jo@uni.edu")]}],
                   [{"accession_id": "P1", "dac_accession_id": "EGAC00000000002"},
                    {"accession_id": "P2", "dac_accession_id": "EGAC00000000001"},
                    {"accession_id": "P3", "dac_accession_id": "EGAC00000000002"}],
                   [{"accession_id": "D1", "policy_accession_id": "P1"},
                    {"accession_id": "D2", "policy_accession_id": None, "is_deprecated": True},
                    {"accession_id": "D3", "policy_accession_id": "P3"}])
    summary, changes = compare(old, new)
    assert summary["dacs"]["added"] == 1 and summary["dacs"]["changed"]["contacts"] == 1
    assert summary["dacs"]["new_dac_contact_profile"] == {"single_individual": 1}
    assert summary["policies"]["moved_to_another_dac"] == 1
    assert summary["datasets"]["policy_less_resolved"] == 1 and summary["datasets"]["became_policy_less"] == 1
    assert summary["datasets"]["newly_deprecated"] == 1
    assert summary["datasets"]["moved_to_another_dac"] == 1   # D3: P2 (DAC 1) -> P3 (DAC 2)
    assert "a@new.org" not in json.dumps(changes) and "new.org" in json.dumps(changes)
