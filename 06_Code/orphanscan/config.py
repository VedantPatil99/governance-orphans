"""Tunable constants and heuristics. Every heuristic states why it exists, so it can be defended or changed."""
import re
from pathlib import Path

# --- Project folders (CaseStudy/06_Code/orphanscan/config.py -> CaseStudy/) --------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "05_Data_and_Results"
RESULTS = DATA / "results"
VALIDATION = DATA / "validation"
RAW = DATA / "raw_snapshots_PRIVATE"
FIGURES = ROOT / "04_Figures"
ROSTER = DATA / "consortium_roster.csv"
SCAN_RESULTS = RESULTS / "governance_decay_scan_results.csv"
O5_RESULTS = RESULTS / "policy_orphan_datasets.csv"

# --- EGA public metadata API -------------------------------------------------------------------
BASE = "https://metadata.ega-archive.org"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 15      # seconds per URL-liveness check
API_TIMEOUT = 45          # seconds per API page; /dacs at offsets > 4,000 takes 30-50 s
MAX_RETRIES = 6           # a census with a missing page is not a census, so retry hard, then abort
POLITE_DELAY = 0.1        # seconds between calls, to avoid loading a public service
USER_AGENT = "governance-decay-scanner/2.0 (course research project)"
DEFAULT_SNAPSHOT = str(RAW / "raw_ega_snapshot")

# Real EGA DAC accessions are EGAC + 11 digits. Anything else (numeric ids such as "52") is a stub
# mirroring an NIH/dbGaP committee, i.e. a reference to another archive, not an EGA committee.
EGA_DAC_ID = re.compile(r"EGAC\d{11}")
EGA_DATASET_ID = re.compile(r"EGAD\d{11}")

# --- Contact assessment ------------------------------------------------------------------------
# Personal webmail: a committee reachable only through someone's private mailbox has no institutional
# continuity. List = the providers that actually occur among EGA contact domains plus the major global ones.
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "protonmail.com", "proton.me",
    "qq.com", "163.com", "126.com", "foxmail.com", "sina.com", "yandex.ru", "mail.ru",
    "gmx.de", "gmx.net", "web.de", "naver.com", "hanmail.net",
}
# A local part like dac@, access@, helpdesk@ is a role mailbox that survives staff turnover; a
# personal name does not. Words were taken from role addresses observed in EGA contact data.
ROLE_LOCALPART = re.compile(
    r"(dac|daco|access|data|request|helpdesk|help|info|admin|office|committee|"
    r"governance|compliance|secretariat|ethics|support|contact|team|ega|biobank|enquir)",
    re.IGNORECASE,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
DNS_LIFETIME = 8          # seconds per DNS query before it counts as "unknown" (not "dead")

# --- Roster matching ---------------------------------------------------------------------------
STATUS_PRIORITY = {"ended": 0, "past_driver_project": 1, "active": 2}
# EGA is the archive being scanned: almost any DAC can mention it, so an EGA hit identifies no
# consortium and only wins when nothing more specific matches.
GENERIC_ROWS = {"European Genome-phenome Archive"}

# --- Record hygiene ----------------------------------------------------------------------------
# Test / placeholder / obsolete committees left in production. "ctDNA test" and "genetic test" are
# clinical studies, not test records.
TEST_NAME = re.compile(
    r"(?<!ctDNA )(?<!genetic )\b(?:test|dummy|placeholder|obsolete|do not use|very interesting|daccy)\b", re.I)
