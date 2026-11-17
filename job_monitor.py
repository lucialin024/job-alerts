#!/usr/bin/env python3
"""
Job posting monitor with configurable priority tiers.

Polls official career-site APIs, detects newly published postings that match
your target roles, and emails one alert per new position.

    python job_monitor.py                  # run forever (recommended)
    python job_monitor.py --once           # one pass over every company, then exit
    python job_monitor.py --dry-run        # print alerts instead of emailing
    python job_monitor.py --test-email     # send one sample HIGH PRIORITY email
    python job_monitor.py --show-matches   # list currently open matching jobs (title match only)

Everything you would want to change (companies, the high-priority group,
polling speed, target roles, email) lives in config.yaml. The config file is
re-read automatically whenever it changes; no restart needed.

Requires:  pip install requests pyyaml
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import random
import re
import smtplib
import sqlite3
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field, asdict
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Callable, Iterable

import requests
import yaml

log = logging.getLogger("job_monitor")


# ════════════════════════════════════════════════════════════════════════════
# Data model
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Job:
    company: str
    listing_id: str            # ID of this listing on the career site
    title: str
    url: str = ""              # direct, job-specific URL
    req_id: str = ""           # requisition ID shared by every copy of the same position
    locations: list[str] = field(default_factory=list)
    posted: str = ""
    workplace: str = ""        # remote / hybrid / on-site, when the site says
    extra_text: str = ""       # division, job function, level: used for matching
    description: str = ""
    url_verified: bool = False
    extra_links: dict[str, str] = field(default_factory=dict)
    detail_ref: str = ""       # adapter-private handle for fetching details
    level: str = ""            # corporate title / career level, when the site gives one
    countries: list[str] = field(default_factory=list)   # country codes or names, when known
    min_years: int | None = None                         # lowest "N years of experience" in the description

    @property
    def dedupe_key(self) -> str:
        return (self.req_id or self.listing_id).strip().upper()


class FetchError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


# ════════════════════════════════════════════════════════════════════════════
# HTTP helper
# ════════════════════════════════════════════════════════════════════════════
class Http:
    def __init__(self, user_agent: str, timeout: float, page_delay: float):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
        self.timeout = timeout
        self.page_delay = page_delay

    def request(self, method: str, url: str, **kw) -> requests.Response:
        try:
            r = self.s.request(method, url, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            raise FetchError(f"{method} {url}: {e}") from e
        if r.status_code in (429, 503):
            ra = r.headers.get("Retry-After", "")
            raise FetchError(f"{method} {url}: HTTP {r.status_code} (rate limited)",
                             retry_after=float(ra) if ra.isdigit() else None)
        if r.status_code >= 400:
            raise FetchError(f"{method} {url}: HTTP {r.status_code}")
        return r

    def json(self, method: str, url: str, **kw):
        r = self.request(method, url, **kw)
        try:
            return r.json()
        except ValueError as e:
            raise FetchError(f"{method} {url}: response was not JSON") from e

    def pause(self):
        time.sleep(self.page_delay)


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


# ════════════════════════════════════════════════════════════════════════════
# Adapters: one per applicant tracking system
#   list_jobs(full) -> newest-first listings (full=False: only the newest page(s))
#   enrich(job)     -> fills description, verified URL, req_id, locations
# ════════════════════════════════════════════════════════════════════════════
class Adapter:
    def __init__(self, company: dict, http: Http):
        self.c = company
        self.name = company["name"]
        self.http = http

    def list_jobs(self, full: bool) -> list[Job]:
        raise NotImplementedError

    def enrich(self, job: Job) -> None:   # optional
        pass


class WorkdayAdapter(Adapter):
    """Workday public career-site API (the one the career page itself calls).

    config:  workday: {host: capitalone.wd12.myworkdayjobs.com, tenant: capitalone, site: Capital_One}
    Listings come back newest first, 20 per page (the API rejects larger pages).
    """
    PAGE = 20

    def __init__(self, company, http):
        super().__init__(company, http)
        w = company["workday"]
        self.search_text = w.get("search_text", "")
        self.site_url = w.get("site_url") or f"https://{w['host']}/{w['site']}"
        self.api = f"https://{w['host']}/wday/cxs/{w['tenant']}/{w['site']}"

    def list_jobs(self, full: bool) -> list[Job]:
        max_pages = 10_000 if full else int(self.c.get("fast_pages", 3))
        jobs, offset, total = [], 0, None
        for _ in range(max_pages):
            data = self.http.json("POST", f"{self.api}/jobs", json={
                "appliedFacets": {}, "limit": self.PAGE, "offset": offset, "searchText": self.search_text})
            if total is None:               # Workday only reports the total on page one
                total = data.get("total") or 0
            page = data.get("jobPostings") or []
            for p in page:
                path = p.get("externalPath") or ""
                if not path:
                    continue
                req = (p.get("bulletFields") or [""])[0] or self._req_from_path(path)
                jobs.append(Job(
                    company=self.name, listing_id=path, title=p.get("title", "").strip(),
                    url=self.site_url + path, req_id=req,
                    locations=[p["locationsText"]] if p.get("locationsText") else [],
                    posted=p.get("postedOn", ""), workplace=p.get("remoteType", "") or "",
                    detail_ref=path))
            offset += self.PAGE
            if len(page) < self.PAGE or offset >= total:
                break
            self.http.pause()
        return jobs

    @staticmethod
    def _req_from_path(path: str) -> str:
        m = re.search(r"_([A-Za-z]{0,6}-?\d{3,})(?:-\d+)?$", path)
        return m.group(1) if m else ""

    def enrich(self, job: Job) -> None:
        info = self.http.json("GET", self.api + job.detail_ref).get("jobPostingInfo") or {}
        job.description = strip_html(info.get("jobDescription", ""))
        job.req_id = info.get("jobReqId") or job.req_id
        locs = [info.get("location")] + list(info.get("additionalLocations") or [])
        job.locations = [l for l in locs if l] or job.locations
        job.posted = info.get("startDate") or job.posted
        job.workplace = info.get("remoteType") or job.workplace
        for c in (info.get("country"), (info.get("jobRequisitionLocation") or {}).get("country")):
            for v in ((c or {}).get("alpha2Code"), (c or {}).get("descriptor")):
                if v and v not in job.countries:
                    job.countries.append(v)
        if info.get("externalUrl"):
            job.url = info["externalUrl"]
            job.url_verified = True


class GoldmanSachsAdapter(Adapter):
    """Goldman Sachs careers (higher.gs.com), in-house site backed by Oracle Recruiting.
    Uses the GraphQL endpoint the career site itself calls."""
    API = "https://api-higher.gs.com/gateway/api/v1/graphql"
    PAGE = 100
    LIST_Q = ("query GetRoles($searchQueryInput: RoleSearchQueryInput!) { "
              "roleSearch(searchQueryInput: $searchQueryInput) { totalCount items { "
              "roleId corporateTitle jobTitle jobFunction "
              "locations { primary state country city } status division "
              "externalSource { sourceId } } } }")
    ROLE_Q = ("query GetRoleById($externalSourceId: String!, $externalSourceFetch: Boolean) { "
              "role(externalSourceId: $externalSourceId, externalSourceFetch: $externalSourceFetch) { "
              "roleId jobTitle descriptionHtml status applyActive "
              "locations { primary state country city } "
              "externalSource { externalApplicationUrl sourceId } } }")

    def _gql(self, op: str, query: str, variables: dict) -> dict:
        data = self.http.json("POST", self.API,
                              json={"operationName": op, "query": query, "variables": variables})
        if data.get("errors"):
            raise FetchError(f"Goldman Sachs GraphQL error: {str(data['errors'])[:200]}")
        return data.get("data") or {}

    @staticmethod
    def _locs(items) -> list[str]:
        out = []
        for l in items or []:
            s = ", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x)
            if s and s not in out:
                out.append(s)
        return out

    def list_jobs(self, full: bool) -> list[Job]:
        experiences = self.c.get("experiences", ["EARLY_CAREER", "PROFESSIONAL"])
        max_pages = 10_000 if full else int(self.c.get("fast_pages", 1))
        jobs, page_no = [], 0
        for _ in range(max_pages):
            rs = self._gql("GetRoles", self.LIST_Q, {"searchQueryInput": {
                "page": {"pageSize": self.PAGE, "pageNumber": page_no},
                "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
                "filters": [], "experiences": experiences, "searchTerm": ""}}).get("roleSearch") or {}
            items = rs.get("items") or []
            for it in items:
                sid = (it.get("externalSource") or {}).get("sourceId") or ""
                if not sid:
                    continue
                jobs.append(Job(
                    company=self.name, listing_id=it.get("roleId") or sid, req_id=sid,
                    title=(it.get("jobTitle") or "").strip(),
                    url=f"https://higher.gs.com/roles/{sid}",
                    locations=self._locs(it.get("locations")),
                    level=it.get("corporateTitle") or "",
                    countries=sorted({l.get("country") for l in it.get("locations") or [] if l.get("country")}),
                    extra_text=" ".join(x for x in (it.get("corporateTitle"), it.get("jobFunction"),
                                                    it.get("division")) if x),
                    detail_ref=sid))
            page_no += 1
            if len(items) < self.PAGE or page_no * self.PAGE >= (rs.get("totalCount") or 0):
                break
            self.http.pause()
        return jobs

    def enrich(self, job: Job) -> None:
        role = self._gql("GetRoleById", self.ROLE_Q, {
            "externalSourceId": job.detail_ref, "externalSourceFetch": False}).get("role") or {}
        if not role:
            return
        job.description = strip_html(role.get("descriptionHtml", ""))
        job.locations = self._locs(role.get("locations")) or job.locations
        job.url_verified = True      # the role resolves by this ID, so /roles/<id> is live
        apply_url = (role.get("externalSource") or {}).get("externalApplicationUrl")
        if apply_url:
            job.extra_links["Apply"] = apply_url


class DeutscheBankAdapter(Adapter):
    """Deutsche Bank careers (careers.db.com). The site's search API is hosted by
    Beesite; each posting links through to Deutsche Bank's Workday tenant."""
    API = "https://api-deutschebank.beesite.de"
    PAGE = 200
    FIELDS = ["PositionID", "PositionTitle", "PositionURI", "OrganizationName",
              "PositionLocation.CountryName", "PositionLocation.CountrySubDivisionName",
              "PositionLocation.CityName", "PositionLocation.CountryCode", "CareerLevel.Name", "PositionSchedule.Name",
              "PositionOfferingType.Name", "PublicationStartDate"]

    def list_jobs(self, full: bool) -> list[Job]:
        max_pages = 10_000 if full else int(self.c.get("fast_pages", 1))
        jobs, first = [], 1
        for _ in range(max_pages):
            q = {"LanguageCode": "en", "SearchParameters": {
                    "FirstItem": first, "CountItem": self.PAGE,
                    "MatchedObjectDescriptor": self.FIELDS,
                    "Sort": [{"Criterion": "PublicationStartDate", "Direction": "DESC"}]},
                 "SearchCriteria": []}
            sr = self.http.json("GET", f"{self.API}/search/",
                                params={"data": json.dumps(q, separators=(",", ":"))}
                                ).get("SearchResult") or {}
            items = sr.get("SearchResultItems") or []
            for it in items:
                d = it.get("MatchedObjectDescriptor") or {}
                pid = str(d.get("PositionID") or it.get("MatchedObjectId") or "")
                if not pid:
                    continue
                locs = []
                for l in d.get("PositionLocation") or []:
                    s = ", ".join(x for x in (l.get("CityName"), l.get("CountrySubDivisionName"),
                                              l.get("CountryName")) if x)
                    if s and s not in locs:
                        locs.append(s)
                level = " ".join(x.get("Name", "") for x in d.get("CareerLevel") or [])
                jobs.append(Job(
                    company=self.name, listing_id=pid, title=(d.get("PositionTitle") or "").strip(),
                    url=f"https://careers.db.com/professionals/search-roles/#/professional/job/{pid}",
                    locations=locs, posted=d.get("PublicationStartDate", ""),
                    level=level,
                    countries=sorted({l.get("CountryCode") for l in d.get("PositionLocation") or []
                                      if l.get("CountryCode")}),
                    extra_text=level, detail_ref=pid))
            first += self.PAGE
            if len(items) < self.PAGE or first > (sr.get("SearchResultCountAll") or 0):
                break
            self.http.pause()
        return jobs

    def enrich(self, job: Job) -> None:
        d = self.http.json("GET", f"{self.API}/jobhtml/{job.detail_ref}.json")
        raw = d.get("html", "")
        job.description = strip_html(raw)
        m = re.search(r"Job ID:\s*(?:</strong>)?\s*([A-Za-z]*\d+)", raw)
        if m:
            job.req_id = m.group(1)
        if d.get("pro_div_name"):
            job.extra_text = f"{job.extra_text} {d['pro_div_name']}".strip()
        job.url_verified = True      # the posting resolves by this ID
        apply_uri = d.get("apply_uri") or ""
        if apply_uri:
            job.extra_links["Careers page"] = job.url
            job.extra_links["Apply"] = apply_uri
            job.url = re.sub(r"/apply/?$", "", apply_uri)   # job-specific Workday posting


class GreenhouseAdapter(Adapter):
    """config:  greenhouse: {board: <board token>}"""
    def list_jobs(self, full: bool) -> list[Job]:
        board = self.c["greenhouse"]["board"]
        data = self.http.json("GET", f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                              params={"content": "true"})
        return [Job(company=self.name, listing_id=str(j["id"]), title=j.get("title", "").strip(),
                    url=j.get("absolute_url", ""), req_id=str(j.get("internal_job_id") or ""),
                    locations=[x for x in [(j.get("location") or {}).get("name", "")]
                               + [o.get("name", "") for o in j.get("offices") or []] if x],
                    posted=j.get("first_published") or j.get("updated_at", ""),
                    description=strip_html(html.unescape(j.get("content", ""))),
                    url_verified=bool(j.get("absolute_url")))
                for j in data.get("jobs") or []]


class LeverAdapter(Adapter):
    """config:  lever: {company: <lever site name>}"""
    def list_jobs(self, full: bool) -> list[Job]:
        site = self.c["lever"]["company"]
        data = self.http.json("GET", f"https://api.lever.co/v0/postings/{site}", params={"mode": "json"})
        out = []
        for j in data or []:
            cat = j.get("categories") or {}
            out.append(Job(company=self.name, listing_id=j["id"], title=j.get("text", "").strip(),
                           url=j.get("hostedUrl", ""), locations=[cat.get("location", "")],
                           workplace=j.get("workplaceType", ""), extra_text=cat.get("team", "") or "",
                           description=j.get("descriptionPlain", ""),
                           url_verified=bool(j.get("hostedUrl"))))
        return out


class AshbyAdapter(Adapter):
    """config:  ashby: {board: <job board name>}"""
    def list_jobs(self, full: bool) -> list[Job]:
        board = self.c["ashby"]["board"]
        data = self.http.json("GET", f"https://api.ashbyhq.com/posting-api/job-board/{board}")
        return [Job(company=self.name, listing_id=j["id"], title=j.get("title", "").strip(),
                    url=j.get("jobUrl", ""), locations=[j.get("location", "")],
                    posted=j.get("publishedAt", ""), extra_text=j.get("department", "") or "",
                    workplace="Remote" if j.get("isRemote") else "",
                    description=j.get("descriptionPlain", ""), url_verified=bool(j.get("jobUrl")))
                for j in data.get("jobs") or []]


ADAPTERS: dict[str, type[Adapter]] = {
    "workday": WorkdayAdapter,
    "goldman_sachs": GoldmanSachsAdapter,
    "deutsche_bank": DeutscheBankAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
}


# ════════════════════════════════════════════════════════════════════════════
# Matching
# ════════════════════════════════════════════════════════════════════════════
_SYNONYMS = {"sr": "senior", "snr": "senior", "senoir": "senior", "jr": "junior", "analysts": "analyst", "associates": "associate",
             "quant": "quantitative", "strategies": "strategy", "strategic": "strategy",
             "finance": "financial", "investments": "investment", "investing": "investment"}


def token_list(s: str) -> list[str]:
    return [_SYNONYMS.get(t, t) for t in re.findall(r"[a-z0-9]+", (s or "").lower())]


def tokens(s: str) -> set[str]:
    return set(token_list(s))


def _contains_seq(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


# ── location ────────────────────────────────────────────────────────────────
_COUNTRY_ALIASES = {
    "US": {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"},
    "GB": {"GB", "UK", "UNITED KINGDOM"},
    "CA": {"CA", "CANADA"},
    "IN": {"IN", "INDIA"},
    "DE": {"DE", "GERMANY", "DEUTSCHLAND"},
}
_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH "
                 "NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


def location_state(job: Job, allowed: list[str], keywords: list[str] = ()) -> bool | None:
    """True = in an allowed country, False = known to be elsewhere, None = cannot tell."""
    if not allowed:
        return True
    want = set()
    for a in allowed:
        want |= _COUNTRY_ALIASES.get(a.upper(), {a.upper()})
    if any(c.upper() in want for c in job.countries):
        return True
    for loc in job.locations:
        if "US" in want and (re.search(r"\b(United States|USA|U\.S\.)", loc, re.I)
                             or re.search(r"\bUS\b", loc)
                             or any(st in _US_STATES for st in re.findall(r",\s*([A-Z]{2})\b", loc))):
            return True
        if any(k.lower() in loc.lower() for k in keywords):
            return True
    return False if job.countries else None


# ── years of experience ─────────────────────────────────────────────────────
_YEARS = re.compile(r"(?<![\d.$,])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|—|to)\s*\d{1,2}\s*\+?\s*)?"
                    r"(?:years?|yrs?)\b(?!\s*old)", re.I)


def min_years_required(description: str) -> int | None:
    """Lowest 'N years' figure that is stated as an experience requirement, or None."""
    vals = []
    for m in _YEARS.finditer(description or ""):
        n = int(m.group(1))
        if n > 20:
            continue
        ctx = description[max(0, m.start() - 40): m.end() + 60].lower()
        if "experience" in ctx or re.search(r"at least|minimum|min\.", ctx):
            vals.append(n)
    return min(vals) if vals else None


def _phrase_in(phrase: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", text) is not None


class Matcher:
    """Decides whether a job is relevant, in three steps:
       1. title contains every word of a target role (any order)       -> match
       2. title contains a related term (e.g. "analytics", "quant")    -> match
       3. title looks like the right kind of role (gate term) AND the
          description names a target role or enough target skills      -> match
    """
    def __init__(self, cfg: dict, company: dict):
        m = cfg.get("matching") or {}
        self.roles = list(company.get("roles") or m.get("default_roles") or [])
        self.role_tokens = [(r, tokens(r)) for r in self.roles]
        self.related = [t.lower() for t in (company.get("related_title_terms")
                                            or m.get("related_title_terms") or [])]
        self.gate = [t.lower() for t in m.get("description_gate_terms") or []]
        self.skills = [t.lower() for t in m.get("skills") or []]
        self.min_skills = int(m.get("min_skill_hits", 3))
        self.exclude = [t.lower() for t in (m.get("exclude_title_terms") or [])
                        + (company.get("exclude_title_terms") or [])]
        self.match_all = bool(company.get("match_all", False))
        self.strict = bool(company.get("strict_titles", False))
        my = company.get("max_years_experience", m.get("max_years_experience"))
        self.max_years = None if my in (None, "") else int(my)

    def excluded(self, job: Job) -> bool:
        t = f"{job.title} | {job.level}".lower()
        return any(_phrase_in(x, t) for x in self.exclude)

    def too_senior(self, job: Job) -> bool:
        """True when the description's lowest stated experience requirement exceeds the limit."""
        job.min_years = min_years_required(job.description)
        return self.max_years is not None and job.min_years is not None and job.min_years > self.max_years

    def title_match(self, job: Job) -> str | None:
        if self.match_all:
            return "all postings for this company"
        if self.strict:      # only titles that contain one of the roles, word for word
            tl = token_list(job.title)
            for role in self.roles:
                rl = token_list(role)
                # also accept the level word moved to the end: "Business Analyst, Senior"
                variants = [rl] + ([rl[1:] + rl[:1]] if len(rl) > 1 and rl[0] in ("senior", "junior") else [])
                if any(_contains_seq(tl, v) for v in variants):
                    return f"title contains “{role}”"
            return None
        tt = tokens(f"{job.title} {job.extra_text}")
        for role, rt in self.role_tokens:
            if rt and rt <= tt:
                return f"title matches “{role}”"
        low = f"{job.title} {job.extra_text}".lower()
        for term in self.related:
            if _phrase_in(term, low):
                return f"related title term “{term}”"
        return None

    def wants_description(self, job: Job) -> bool:
        if self.strict:
            return False
        low = f"{job.title} {job.extra_text}".lower()
        return any(_phrase_in(g, low) for g in self.gate)

    def description_match(self, job: Job) -> str | None:
        d = job.description.lower()
        if not d:
            return None
        for role in self.roles:
            if _phrase_in(role, d):
                return f"description mentions “{role}”"
        hits = [s for s in self.skills if _phrase_in(s, d)]
        if len(hits) >= self.min_skills:
            return "description skills: " + ", ".join(hits[:6])
        return None


# ════════════════════════════════════════════════════════════════════════════
# State (SQLite): what has been seen, what has been alerted
# ════════════════════════════════════════════════════════════════════════════
class State:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS seen     (company TEXT, listing_id TEXT, first_seen REAL,
                                                 PRIMARY KEY (company, listing_id));
            CREATE TABLE IF NOT EXISTS alerted  (company TEXT, dedupe_key TEXT, title TEXT, url TEXT,
                                                 alerted_at REAL, PRIMARY KEY (company, dedupe_key));
            CREATE TABLE IF NOT EXISTS pending  (company TEXT, dedupe_key TEXT, payload TEXT,
                                                 created REAL, PRIMARY KEY (company, dedupe_key));
            CREATE TABLE IF NOT EXISTS seeded   (company TEXT PRIMARY KEY, at REAL);
            CREATE TABLE IF NOT EXISTS meta     (key TEXT PRIMARY KEY, value REAL);
        """)

    def get_meta(self, key: str) -> float:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return float(row[0]) if row else 0.0

    def set_meta(self, key: str, value: float):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.db.commit()

    def title_alerted_since(self, company: str, title: str, since: float) -> bool:
        return self.db.execute(
            "SELECT 1 FROM alerted WHERE company=? AND lower(title)=? AND alerted_at>=?",
            (company, title.strip().lower(), since)).fetchone() is not None

    def is_seeded(self, company): return self.db.execute(
        "SELECT 1 FROM seeded WHERE company=?", (company,)).fetchone() is not None

    def mark_seeded(self, company):
        self.db.execute("INSERT OR REPLACE INTO seeded VALUES (?,?)", (company, time.time()))
        self.db.commit()

    def unseen(self, company: str, jobs: Iterable[Job]) -> list[Job]:
        out, dup = [], set()
        for j in jobs:
            if j.listing_id in dup:
                continue
            dup.add(j.listing_id)
            if not self.db.execute("SELECT 1 FROM seen WHERE company=? AND listing_id=?",
                                   (company, j.listing_id)).fetchone():
                out.append(j)
        return out

    def mark_seen(self, jobs: Iterable[Job]):
        self.db.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?)",
                            [(j.company, j.listing_id, time.time()) for j in jobs])
        self.db.commit()

    def was_alerted(self, company, key): return self.db.execute(
        "SELECT 1 FROM alerted WHERE company=? AND dedupe_key=?", (company, key)).fetchone() is not None

    def mark_alerted(self, job: Job):
        self.db.execute("INSERT OR REPLACE INTO alerted VALUES (?,?,?,?,?)",
                        (job.company, job.dedupe_key, job.title, job.url, time.time()))
        self.db.execute("DELETE FROM pending WHERE company=? AND dedupe_key=?",
                        (job.company, job.dedupe_key))
        self.db.commit()

    def add_pending(self, job: Job, reason: str):
        self.db.execute("INSERT OR REPLACE INTO pending VALUES (?,?,?,?)",
                        (job.company, job.dedupe_key,
                         json.dumps({"job": asdict(job), "reason": reason}), time.time()))
        self.db.commit()

    def pending(self, company: str) -> list[tuple[Job, str]]:
        rows = self.db.execute("SELECT payload FROM pending WHERE company=? ORDER BY created",
                               (company,)).fetchall()
        out = []
        for (p,) in rows:
            d = json.loads(p)
            out.append((Job(**d["job"]), d["reason"]))
        return out


# ════════════════════════════════════════════════════════════════════════════
# Email
# ════════════════════════════════════════════════════════════════════════════
class Emailer:
    def __init__(self, cfg: dict, dry_run: bool = False):
        e = cfg.get("email") or {}
        self.host = os.environ.get("SMTP_HOST") or e.get("smtp_host", "smtp.gmail.com")
        self.port = int(os.environ.get("SMTP_PORT") or e.get("smtp_port", 465))
        self.user = os.environ.get("SMTP_USER") or e.get("smtp_user", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")     # never stored in config
        self.sender = os.environ.get("EMAIL_FROM") or e.get("from") or self.user
        to = os.environ.get("EMAIL_TO") or e.get("to") or self.user
        self.to = [a.strip() for a in (to if isinstance(to, list) else str(to).split(",")) if a.strip()]
        self.dry_run = dry_run

    def check(self):
        if self.dry_run:
            return
        missing = [n for n, v in (("SMTP_USER / email.smtp_user", self.user),
                                  ("SMTP_PASSWORD (environment variable)", self.password),
                                  ("EMAIL_TO / email.to", self.to)) if not v]
        if missing:
            sys.exit("Email is not configured. Missing: " + "; ".join(missing))

    @staticmethod
    def subject(prefix: str, job: Job) -> str:
        parts = [prefix] if prefix else []
        return " | ".join(parts + [job.company, job.title, "NEW JOB"])

    def build(self, tier: dict, job: Job, reason: str, others: list[Job]) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = self.subject(tier.get("subject_prefix", ""), job)
        msg["From"], msg["To"] = self.sender, ", ".join(self.to)
        msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid()
        if str(tier.get("email_importance", "")).lower() == "high":
            msg["X-Priority"], msg["Importance"], msg["X-MSMail-Priority"] = "1", "High", "High"

        rows = [("Company", job.company), ("Title", job.title),
                ("Location(s)", "; ".join(l for l in job.locations if l) or "Not listed"),
                ("Level", job.level), ("Workplace", job.workplace), ("Posted", job.posted),
                ("Experience asked", f"{job.min_years}+ years" if job.min_years is not None else ""),
                ("Requisition ID", job.req_id), ("Why it matched", reason),
                ("Link check", "Verified against the career site's posting record"
                 if job.url_verified else "NOT verified: open the link to confirm")]
        rows = [(k, v) for k, v in rows if v]
        text = [f"{k}: {v}" for k, v in rows] + ["", f"Job posting: {job.url}"]
        text += [f"{k}: {v}" for k, v in job.extra_links.items()]
        if others:
            text += ["", "Same title also posted as separate requisitions:"]
            text += [f"  - {'; '.join(o.locations) or 'location not listed'} ({o.req_id or o.listing_id}): {o.url}"
                     for o in others]
        msg.set_content("\n".join(text))

        esc = html.escape
        h = ["<table cellpadding='4' style='font-family:Arial,sans-serif;font-size:14px'>"]
        h += [f"<tr><td><b>{esc(k)}</b></td><td>{esc(str(v))}</td></tr>" for k, v in rows]
        h.append("</table>")
        h.append(f"<p style='font-family:Arial,sans-serif;font-size:15px'>"
                 f"<a href='{esc(job.url, quote=True)}'><b>Open the job posting</b></a><br>"
                 f"<span style='font-size:12px;color:#555'>{esc(job.url)}</span></p>")
        for k, v in job.extra_links.items():
            h.append(f"<p style='font-family:Arial,sans-serif;font-size:13px'>{esc(k)}: "
                     f"<a href='{esc(v, quote=True)}'>{esc(v)}</a></p>")
        if others:
            h.append("<p style='font-family:Arial,sans-serif;font-size:13px'>"
                     "Same title also posted as separate requisitions:</p><ul>")
            h += [f"<li><a href='{esc(o.url, quote=True)}'>{esc('; '.join(o.locations) or 'location not listed')}"
                  f"</a> ({esc(o.req_id or o.listing_id)})</li>" for o in others]
            h.append("</ul>")
        msg.add_alternative("".join(h), subtype="html")
        return msg

    def send(self, msg: EmailMessage):
        if self.dry_run:
            print("\n" + "=" * 78 + f"\nSUBJECT: {msg['Subject']}\n"
                  + msg.get_body(preferencelist=("plain",)).get_content())
            return
        ctx = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30) as s:
                s.login(self.user, self.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(self.user, self.password)
                s.send_message(msg)


# ════════════════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════════════════
DEFAULT_TIERS = {
    "high":   {"poll_seconds": 90,  "full_sweep_minutes": 60,  "subject_prefix": "🚨 HIGH PRIORITY",
               "email_importance": "high"},
    "normal": {"poll_seconds": 900, "full_sweep_minutes": 360, "subject_prefix": "",
               "email_importance": "normal"},
}


class Config:
    def __init__(self, path: Path):
        self.path = path
        self.mtime = 0.0
        self.data: dict = {}
        self.reload()

    def changed(self) -> bool:
        try:
            return self.path.stat().st_mtime != self.mtime
        except OSError:
            return False

    def reload(self):
        mtime = self.path.stat().st_mtime
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        names = [c.get("name") for c in data.get("companies") or []]
        for c in data.get("companies") or []:
            if not c.get("name") or c.get("adapter") not in ADAPTERS:
                raise ValueError(f"company {c.get('name')!r}: 'adapter' must be one of {sorted(ADAPTERS)}")
        unknown = [n for n in data.get("high_priority_companies") or [] if n not in names]
        if unknown:
            log.warning("high_priority_companies lists names with no entry under companies: %s", unknown)
        self.data, self.mtime = data, mtime

    def tier_of(self, company: dict) -> tuple[str, dict]:
        high = {n.strip().lower() for n in self.data.get("high_priority_companies") or []}
        name = "high" if company["name"].strip().lower() in high else company.get("priority", "normal")
        tiers = {**DEFAULT_TIERS, **(self.data.get("priority_tiers") or {})}
        return name, {**DEFAULT_TIERS.get(name, DEFAULT_TIERS["normal"]), **(tiers.get(name) or {})}

    def companies(self) -> list[dict]:
        return [c for c in self.data.get("companies") or [] if c.get("enabled", True)]


# ════════════════════════════════════════════════════════════════════════════
# Monitor
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class Sched:
    next_due: float = 0.0
    next_sweep: float = 0.0
    failures: int = 0
    running: Future | None = None
    full: bool = False


class Monitor:
    def __init__(self, cfg: Config, dry_run: bool):
        self.cfg, self.dry_run = cfg, dry_run
        s = cfg.data.get("settings") or {}
        base = cfg.path.parent
        self.state = State(str(base / s.get("state_file", "job_monitor_state.db")))
        self.http_args = (s.get("user_agent", "job-alert-monitor/1.0 (personal job search)"),
                          float(s.get("request_timeout_seconds", 20)),
                          float(s.get("page_delay_seconds", 0.4)))
        self.emailer = Emailer(cfg.data, dry_run)
        self.sched: dict[str, Sched] = {}
        self.pool = ThreadPoolExecutor(max_workers=int(s.get("max_parallel_companies", 6)))

    def adapter(self, company: dict) -> Adapter:
        return ADAPTERS[company["adapter"]](company, Http(*self.http_args))

    # ── one company, one cycle ────────────────────────────────────────────
    def process(self, company: dict, jobs: list[Job], full: bool, adapter: Adapter):
        name = company["name"]
        tier_name, tier = self.cfg.tier_of(company)
        matcher = Matcher(self.cfg.data, company)

        if not self.state.is_seeded(name):
            # First contact: record what is already open so only later postings alert.
            if not full:
                jobs = adapter.list_jobs(full=True)
            self.state.mark_seen(jobs)
            self.state.mark_seeded(name)
            log.info("%s: baseline recorded (%d open postings). Alerts start with the next new posting.",
                     name, len(jobs))
            return

        to_send: list[tuple[Job, str]] = self.state.pending(name)   # earlier emails that failed
        retry_keys = {j.dedupe_key for j, _ in to_send}
        new = self.state.unseen(name, jobs)
        if new:
            log.info("%s: %d new posting(s)", name, len(new))
        done: list[Job] = []
        lf = self.cfg.data.get("location_filter") or {}
        allowed, loc_kw = list(lf.get("countries") or []), list(lf.get("extra_keywords") or [])
        repeat_days = float((self.cfg.data.get("matching") or {}).get("suppress_same_title_days", 0) or 0)
        for job in new:
            try:
                if matcher.excluded(job) or location_state(job, allowed, loc_kw) is False:
                    done.append(job)
                    continue
                reason = matcher.title_match(job)
                if reason or matcher.wants_description(job):
                    adapter.enrich(job)              # description + verified URL + requisition ID
                    reason = reason or matcher.description_match(job)
                done.append(job)
                if not reason:
                    continue
                where = location_state(job, allowed, loc_kw)
                if where is False or (where is None and not lf.get("include_unknown", False)):
                    log.info("%s: skipped (outside allowed countries): %s | %s", name, job.title,
                             "; ".join(job.locations))
                    continue
                if matcher.too_senior(job):
                    log.info("%s: skipped (asks for %d+ years): %s", name, job.min_years, job.title)
                    continue
                if repeat_days and self.state.title_alerted_since(
                        name, job.title, time.time() - repeat_days * 86400):
                    log.info("%s: skipped (same title already alerted recently): %s", name, job.title)
                    continue
                key = job.dedupe_key
                if self.state.was_alerted(name, key) or key in retry_keys \
                        or any(key == j.dedupe_key for j, _ in to_send):
                    log.info("%s: duplicate of an already-alerted position, skipped: %s", name, job.title)
                    continue
                self.state.add_pending(job, reason)
                to_send.append((job, reason))
            except FetchError as e:
                log.warning("%s: could not load details for %r, will retry next cycle (%s)",
                            name, job.title, e)
        self.state.mark_seen(done)

        # Same title posted as several requisitions in one cycle -> one email listing all of them.
        groups: dict[str, list[tuple[Job, str]]] = {}
        for job, reason in to_send:
            groups.setdefault(" ".join(sorted(tokens(job.title))), []).append((job, reason))
        for grp in groups.values():
            (lead, reason), others = grp[0], [j for j, _ in grp[1:]]
            try:
                self.emailer.send(self.emailer.build(tier, lead, reason, others))
            except Exception as e:                   # keep it pending; retried next cycle
                log.error("%s: email failed for %r, will retry: %s", name, lead.title, e)
                continue
            for j, _ in grp:
                self.state.mark_alerted(j)
            log.info("%s: ALERT SENT [%s] %s -> %s", name, tier_name, lead.title, lead.url)

    def fetch(self, company: dict, full: bool):
        adapter = self.adapter(company)
        return adapter, adapter.list_jobs(full=full)

    # ── scheduling ────────────────────────────────────────────────────────
    def run_once(self):
        for c in self.cfg.companies():
            try:
                adapter, jobs = self.fetch(c, full=True)
                self.process(c, jobs, True, adapter)
            except FetchError as e:
                log.warning("%s: fetch failed: %s", c["name"], e)

    def run_forever(self, minutes: float = 0):
        log.info("Monitoring %d companies. Ctrl+C to stop.", len(self.cfg.companies()))
        deadline = time.time() + minutes * 60 if minutes else None
        while True:
            if deadline and time.time() >= deadline and not any(
                    sc.running is not None for sc in self.sched.values()):
                log.info("Reached --run-minutes limit, exiting cleanly.")
                return
            if self.cfg.changed():
                try:
                    self.cfg.reload()
                    self.emailer = Emailer(self.cfg.data, self.dry_run)
                    log.info("config.yaml reloaded")
                except Exception as e:
                    log.error("config.yaml has an error, keeping the previous settings: %s", e)
                    self.cfg.mtime = self.cfg.path.stat().st_mtime
            now = time.time()
            for c in self.cfg.companies():
                name = c["name"]
                tier_name, tier = self.cfg.tier_of(c)
                sweep_every = float(c.get("full_sweep_minutes") or tier["full_sweep_minutes"]) * 60
                if name not in self.sched:      # sweep times survive restarts
                    self.sched[name] = Sched(next_sweep=self.state.get_meta(f"sweep:{name}") + sweep_every)
                sc = self.sched[name]
                if sc.running is not None:
                    if not sc.running.done():
                        continue
                    fut, sc.running = sc.running, None
                    poll = float(c.get("poll_seconds") or tier["poll_seconds"])
                    try:
                        adapter, jobs = fut.result()
                        self.process(c, jobs, sc.full, adapter)
                        sc.failures = 0
                        delay = poll
                        if sc.full:
                            self.state.set_meta(f"sweep:{name}", time.time())
                            sc.next_sweep = time.time() + sweep_every
                    except FetchError as e:
                        sc.failures += 1
                        delay = e.retry_after or min(poll * 2 ** sc.failures, 300)
                        log.warning("%s: fetch failed (%s). Retrying in %.0fs.", name, e, delay)
                    except Exception:
                        sc.failures += 1
                        delay = min(poll * 2 ** sc.failures, 300)
                        log.exception("%s: unexpected error. Retrying in %.0fs.", name, delay)
                    sc.next_due = time.time() + delay * random.uniform(0.9, 1.1)
                    continue
                if now >= sc.next_due and not (deadline and now >= deadline):
                    sc.full = now >= sc.next_sweep or not self.state.is_seeded(name)
                    sc.running = self.pool.submit(self.fetch, c, sc.full)
            time.sleep(1)


# ════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    ap.add_argument("--once", action="store_true", help="check every company once, then exit")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of emailing")
    ap.add_argument("--test-email", action="store_true", help="send a sample alert and exit")
    ap.add_argument("--show-matches", action="store_true",
                    help="list open jobs whose title matches (no email, no state change)")
    ap.add_argument("--run-minutes", type=float, default=0,
                    help="run the loop for this many minutes, then exit (for GitHub Actions)")
    ap.add_argument("--company", help="limit --show-matches / --once to one company")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    cfg = Config(Path(a.config))
    if a.company:
        cfg.data["companies"] = [c for c in cfg.data.get("companies") or []
                                 if c["name"].lower() == a.company.lower()]
        if not cfg.data["companies"]:
            sys.exit(f"No company named {a.company!r} in {a.config}")
    mon = Monitor(cfg, a.dry_run)

    if a.show_matches:
        for c in cfg.companies():
            tier_name, _ = cfg.tier_of(c)
            try:
                _, jobs = mon.fetch(c, full=True)
            except FetchError as e:
                print(f"\n{c['name']}: FAILED ({e})")
                continue
            m = Matcher(cfg.data, c)
            lf = cfg.data.get("location_filter") or {}
            hits = [(j, m.title_match(j)) for j in jobs if not m.excluded(j)
                    and location_state(j, list(lf.get("countries") or []),
                                       list(lf.get("extra_keywords") or [])) is not False]
            hits = [(j, r) for j, r in hits if r]
            print(f"\n{c['name']} [{tier_name}]: {len(jobs)} open postings, {len(hits)} title matches")
            for j, r in hits:
                print(f"  - {j.title} | {'; '.join(j.locations)} | {j.url}\n      {r}")
        return

    mon.emailer.check()
    if a.test_email:
        _, tier = "high", {**DEFAULT_TIERS["high"], **((cfg.data.get("priority_tiers") or {}).get("high") or {})}
        sample = Job(company="Capital One", listing_id="TEST", req_id="R0000000",
                     title="Senior Data Analyst", locations=["McLean, VA"], posted="test message",
                     url="https://capitalone.wd12.myworkdayjobs.com/Capital_One", url_verified=False)
        mon.emailer.send(mon.emailer.build(tier, sample, "test message, not a real posting", []))
        print("Test email sent to", ", ".join(mon.emailer.to))
        return
    if a.once:
        mon.run_once()
        return
    try:
        mon.run_forever(a.run_minutes)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
