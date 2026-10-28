"""
Contact-channel assessment (O3) and personal-data handling.

DAC contacts are named individuals' email addresses, i.e. personal data: only the domain is resolved
and only domains are written out -- no addresses or names leave this package.
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import log
from .config import DNS_LIFETIME, EMAIL, FREEMAIL_DOMAINS, POLITE_DELAY, ROLE_LOCALPART
from .ega import check_url_liveness


def redact(text):
    """Free-text DAC fields sometimes embed personal email addresses; never write them out."""
    return EMAIL.sub("[email redacted]", text) if isinstance(text, str) else text


def contact_domains(contacts):
    out = []
    for c in contacts or []:
        email = (c.get("email") or "").strip()
        if "@" in email:
            out.append(email.rsplit("@", 1)[1].lower().strip(" .>"))
    return out


def resolve_domains(domains):
    """Return {domain: 'live' | 'dead' | 'unknown'} using MX, falling back to A records."""
    import dns.exception
    import dns.resolver

    resolver = dns.resolver.Resolver()
    resolver.lifetime = DNS_LIFETIME

    def check(domain):
        for rtype in ("MX", "A"):
            try:
                resolver.resolve(domain, rtype)
                return domain, "live"
            except dns.resolver.NXDOMAIN:
                return domain, "dead"
            except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                continue
            except dns.exception.Timeout:
                return domain, "unknown"
            except Exception:
                return domain, "unknown"
        return domain, "dead"   # domain exists but has neither MX nor A: cannot receive mail

    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(pool.map(check, sorted(domains)))


def assess_contact(contacts, url_status, domain_status):
    """
    Returns (contact_status, is_O3).
      no_contact            -- no contact entry and no working URL         (O3)
      domain_unresolvable   -- every contact email's domain fails DNS      (O3)
      freemail_only         -- only personal webmail addresses             (fragile)
      single_individual     -- exactly one named personal address          (fragile)
      institutional         -- role address or multiple institutional contacts
    """
    domains = contact_domains(contacts)
    if not domains:
        return ("institutional", False) if url_status == "reachable" else ("no_contact", True)
    statuses = [domain_status.get(d, "unknown") for d in domains]
    if all(s == "dead" for s in statuses):
        return "domain_unresolvable", True
    live = [d for d, s in zip(domains, statuses) if s != "dead"]
    if all(d in FREEMAIL_DOMAINS for d in live):
        return "freemail_only", False
    emails = [(c.get("email") or "") for c in contacts]
    if len(set(emails)) == 1 and not ROLE_LOCALPART.search(emails[0].split("@")[0]):
        return "single_individual", False
    return "institutional", False


def contact_checks(snapshot, dacs, use_cache, recheck=False):
    """
    URL liveness + email-domain DNS for every DAC. Both are live network measurements, so they are
    frozen into the snapshot: a cached run reproduces the original numbers exactly instead of
    re-measuring a changed internet. Returns (url_status, domain_status).
    """
    path = os.path.join(snapshot, "contact_checks.json")
    if use_cache and os.path.exists(path) and not recheck:
        with open(path, encoding="utf-8") as f:
            frozen = json.load(f)
        log(f"Loaded frozen contact checks from {path} (checked {frozen['checked_at']}): "
            f"{len(frozen['url_status'])} URLs, {len(frozen['domain_status'])} domains")
        return frozen["url_status"], frozen["domain_status"]
    n_urls = sum(1 for d in dacs if d.get("url"))
    log(f"Checking liveness for {n_urls} published DAC URLs...")
    url_status = {}
    for d in dacs:
        if d.get("url"):
            url_status[d.get("accession_id")] = check_url_liveness(d["url"])
            time.sleep(POLITE_DELAY)
    all_domains = {dom for d in dacs for dom in contact_domains(d.get("contacts"))}
    log(f"Resolving {len(all_domains)} distinct contact email domains (MX/A)...")
    domain_status = resolve_domains(all_domains)
    os.makedirs(snapshot, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "url_status": url_status, "domain_status": domain_status}, f)
    return url_status, domain_status
