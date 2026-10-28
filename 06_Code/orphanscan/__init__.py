"""orphanscan — census and classification of governance orphans in the European Genome-phenome Archive.

Modules
  config    every tunable constant and heuristic, each with its justification
  ega       EGA public metadata API client and raw-snapshot storage
  contacts  contact-channel assessment (URL liveness, email-domain DNS) and redaction of personal data
  roster    matching DAC text against the consortium roster
  census    governance join, DAC table, O1-O5 classification (pure functions, no network)
  charts    scanner charts
"""


def log(msg=""):
    print(msg, flush=True)
