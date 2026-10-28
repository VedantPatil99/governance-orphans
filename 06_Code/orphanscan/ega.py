"""EGA public metadata API client and raw-snapshot storage."""
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

from . import log
from .config import API_TIMEOUT, BASE, MAX_RETRIES, PAGE_SIZE, POLITE_DELAY, REQUEST_TIMEOUT, USER_AGENT

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def connectivity_check():
    url = f"{BASE}/dacs?limit=1&offset=0"
    log(f"Connectivity check: {url}")
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.json()
    except Exception as e:
        log(f"FAILED: {type(e).__name__}: {e}")
        log("This network cannot reach metadata.ega-archive.org — try another network.")
        sys.exit(1)
    log(f"OK (HTTP {resp.status_code})\n")


def fetch_paginated(endpoint, label):
    """
    Fetch every page of `endpoint` (e.g. "/dacs"), with retries and a timeout
    on every single HTTP call so a dead connection can never hang forever.
    Prints progress after every page so you can see it moving.
    """
    results = []
    offset = 0
    page_num = 0
    while True:
        page_num += 1
        url = f"{BASE}{endpoint}?limit={PAGE_SIZE}&offset={offset}"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = session.get(url, timeout=API_TIMEOUT)
                resp.raise_for_status()
                page = resp.json()
                break
            except Exception as e:
                if attempt >= MAX_RETRIES:
                    # A census with a missing page is not a census -- abort rather than
                    # silently treating the failure as end-of-data.
                    raise RuntimeError(
                        f"[{label}] page {page_num} (offset {offset}) failed after {MAX_RETRIES} attempts: {e}"
                    ) from e
                log(f"  [{label}] retry {attempt}/{MAX_RETRIES} on page {page_num} (offset {offset}): {e}")
                time.sleep(3 * attempt)

        if not page:
            break
        results.extend(page)
        log(f"  [{label}] page {page_num}: +{len(page)} records (total so far: {len(results)})")

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(POLITE_DELAY)

    return results


def fetch_or_load(snapshot, endpoint, label, use_cache):
    """Fetch an endpoint in full and save the raw JSON, or load a saved snapshot. Returns (records, date)."""
    path = os.path.join(snapshot, f"{label}.json")
    if use_cache:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        log(f"  [{label}] loaded {len(snap['records'])} records from {path} (retrieved {snap['retrieval_date']})")
        return snap["records"], snap["retrieval_date"]
    records = fetch_paginated(endpoint, label)
    date = today()
    os.makedirs(snapshot, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"retrieval_date": date, "endpoint": endpoint, "records": records}, f)
    return records, date


def get_json(url):
    """One GET with retries; 404 or an empty body -> None."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=API_TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json() if resp.text.strip() else None
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"{url} failed after {MAX_RETRIES} attempts: {e}") from e
            time.sleep(3 * attempt)


def resolve_orphan_dacs(snapshot, dataset_ids, use_cache):
    """
    For each policy-less dataset, look for its committee by the two secondary routes the API offers:
      direct:  /datasets/{id}/dacs
      files:   /datasets/{id}/files -> /files/{id}/dacs (first few files)
    Cached in the snapshot. Returns {dataset: {"n_files", "dacs_direct", "dacs_files", "dacs"}}.
    """
    path = os.path.join(snapshot, "policy_orphan_dacs.json")
    if use_cache and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        if all(d in cached for d in dataset_ids):
            log(f"  [o5] loaded secondary-route DAC resolution for {len(dataset_ids)} datasets from {path}")
            return cached
    out = {}
    log(f"  [o5] resolving DACs by secondary routes for {len(dataset_ids)} policy-less datasets...")
    for i, ds in enumerate(dataset_ids, 1):
        direct = {d["accession_id"] for d in get_json(f"{BASE}/datasets/{ds}/dacs") or [] if d.get("accession_id")}
        files = get_json(f"{BASE}/datasets/{ds}/files?limit=5&offset=0") or []
        via_files = set()
        for fl in files[:3]:
            for dac in get_json(f"{BASE}/files/{fl['accession_id']}/dacs") or []:
                if dac.get("accession_id"):
                    via_files.add(dac["accession_id"])
        out[ds] = {"n_files": len(files), "dacs_direct": sorted(direct), "dacs_files": sorted(via_files),
                   "dacs": sorted(direct | via_files)}
        if i % 25 == 0 or i == len(dataset_ids):
            log(f"  [o5] {i}/{len(dataset_ids)}")
        time.sleep(POLITE_DELAY)
    os.makedirs(snapshot, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def check_url_liveness(url):
    """Returns 'no_url', 'reachable', or 'broken'. Timeout-bounded, never hangs."""
    if not url:
        return "no_url"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return "reachable" if resp.status_code < 400 else "broken"
    except Exception:
        return "broken"
