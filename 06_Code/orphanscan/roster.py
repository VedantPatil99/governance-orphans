"""Matching DAC text against the consortium roster."""
import re

import pandas as pd

from .config import GENERIC_ROWS, ROSTER, STATUS_PRIORITY

NO_MATCH = (None,) * 8
MATCH_COLUMNS = ["consortium_name", "consortium_status", "consortium_end_date", "consortium_successor",
                 "matched_keyword", "match_source", "all_roster_hits", "roster_source"]


def load_roster(path=ROSTER):
    roster = pd.read_csv(path)
    roster["match_keywords"] = roster["match_keywords"].fillna("")
    return roster


def build_matcher(roster):
    """
    Returns match(dac_text, policy_text) -> tuple in MATCH_COLUMNS order.

    Whole-word matching: plain substring matching made short keywords hit inside unrelated words
    ("EGA" in "legal", "ARGO" in "embargo"). Single-token keywords (acronyms: ICGC, ClinGen, HPP) are
    case-sensitive so they don't hit ordinary words or lowercase identifiers; multi-word names are
    case-insensitive.
    """
    compiled = []
    for _, r in roster.iterrows():
        # split on commas, except a thousands separator (digit , three digits) as in "100,000 Genomes"
        keywords = [k.strip() for k in re.split(r"(?<!\d),|,(?!\d{3}\b)", r["match_keywords"]) if k.strip()]
        for group, flags in (([k for k in keywords if " " not in k], 0),
                             ([k for k in keywords if " " in k], re.IGNORECASE)):
            if group:
                pattern = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in group) + r")\b", flags)
                compiled.append((pattern, r))

    # email addresses and URLs are identifiers, not statements of membership ("x@clingen.gu.se")
    strip_identifiers = re.compile(r"\S+@\S+|https?://\S+|www\.\S+")

    def match_consortium(dac_text, policy_text):
        """
        Collects every roster hit, then resolves overlaps:
          * a hit whose span sits inside a longer hit is dropped ("ICGC" inside "ICGC ARGO");
          * the generic EGA row loses to any specific consortium;
          * DAC-authored text beats policy text; then ended > past > active.
        """
        dac_text = strip_identifiers.sub(" ", dac_text or "")
        policy_text = strip_identifiers.sub(" ", policy_text or "")
        hits = []
        for source, text in (("dac", dac_text), ("policy", policy_text)):
            spans = []
            for pattern, r in compiled:
                for m in pattern.finditer(text):
                    spans.append((m.start(), m.end(), r, m.group(0)))
            for s, e, r, kw in spans:
                if any(s2 <= s and e <= e2 and (e2 - s2) > (e - s) for s2, e2, _, _ in spans):
                    continue
                hits.append((source, r, kw))
        if not hits:
            return NO_MATCH
        names = sorted({r["consortium_name"] for _, r, _ in hits})
        specific = [h for h in hits if h[1]["consortium_name"] not in GENERIC_ROWS] or hits
        specific.sort(key=lambda h: (h[0] != "dac", STATUS_PRIORITY.get(h[1]["status"], 9)))
        source, r, kw = specific[0]
        return (r["consortium_name"], r["status"], r["end_date"], r["successor"], kw, source, "; ".join(names),
                r.get("roster_source", "ga4gh"))

    return match_consortium
