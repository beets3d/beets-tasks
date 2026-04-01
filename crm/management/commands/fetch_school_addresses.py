from django.core.management.base import BaseCommand
import csv
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from django.db.models import Q

from crm.models import Customer, CustomerType


class Command(BaseCommand):
    help = "Fetch addresses from school website_url and save suggestions to CSV"

    def add_arguments(self, parser):
        parser.add_argument("--delay", type=float, default=0.6, help="Delay between requests in seconds")

    def handle(self, *args, **options):
        delay = options.get("delay", 0.6)
        s_types = list(CustomerType.objects.filter(Q(label__icontains="school") | Q(label__icontains="學校") | Q(key__iexact="school")))
        qs = (
            Customer.objects.filter(Q(customer_type__in=s_types) | Q(customer_type__key__iexact="school"))
            .filter(Q(street_address__isnull=True) | Q(street_address=""))
            .filter(website_url__isnull=False)
            .exclude(website_url="")
        )
        self.stdout.write(f"Candidates: {qs.count()}")

        headers = {"User-Agent": "beets-tasks-bot/1.0 (+https://example.local)"}
        addr_tag_re = re.compile(r"<address[^>]*>(.*?)</address>", re.I | re.S)
        contact_link_re = re.compile(r"href=[\"']([^\"']*contact[^\"']*)[\"']", re.I)
        addr_keywords_re = re.compile(r"(地址|Address|addr|No\.|號|路|街|道|灣|徑|樓|Block|Building)", re.I)
        strip_tags_re = re.compile(r"<[^>]+>")

        rows = []
        found = 0
        for c in qs.order_by("id"):
            url = (c.website_url or "").strip()
            if not url:
                continue
            if not urlparse(url).scheme:
                url = "http://" + url
            suggestion = None
            method = ""
            excerpt = ""
            try:
                r = requests.get(url, headers=headers, timeout=10)
                text = r.text
                # JSON-LD
                for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text, re.I | re.S):
                    try:
                        data = json.loads(m.group(1))
                    except Exception:
                        continue
                    items = data if isinstance(data, list) else [data]
                    for it in items:
                        ad = None
                        if isinstance(it, dict):
                            if "postalAddress" in it:
                                ad = it["postalAddress"]
                            elif "address" in it:
                                ad = it["address"]
                        if ad:
                            if isinstance(ad, dict):
                                parts = [ad.get(k, "") for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
                                suggestion = " ".join([p for p in parts if p])
                            else:
                                suggestion = str(ad)
                            method = "json-ld"
                            excerpt = json.dumps(ad, ensure_ascii=False)
                            break
                    if suggestion:
                        break

                # <address> tag
                if not suggestion:
                    m = addr_tag_re.search(text)
                    if m:
                        t = strip_tags_re.sub("", m.group(1)).strip()
                        if t:
                            suggestion = " ".join([ln.strip() for ln in t.splitlines() if ln.strip()])
                            method = "address-tag"
                            excerpt = suggestion[:300]

                # contact page
                if not suggestion:
                    m = contact_link_re.search(text)
                    if m:
                        href = m.group(1)
                        contact_url = urljoin(r.url, href)
                        try:
                            r2 = requests.get(contact_url, headers=headers, timeout=10)
                            t2 = r2.text
                            m2 = addr_tag_re.search(t2)
                            if m2:
                                t = strip_tags_re.sub("", m2.group(1)).strip()
                                suggestion = " ".join([ln.strip() for ln in t.splitlines() if ln.strip()])
                                method = "contact-page-address"
                                excerpt = suggestion[:300]
                        except Exception:
                            pass

                # heuristic lines
                if not suggestion:
                    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.I | re.S)
                    body_text = strip_tags_re.sub("\n", body)
                    lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
                    candidates = [ln for ln in lines if addr_keywords_re.search(ln) and len(ln) > 10]
                    if candidates:
                        candidates_sorted = sorted(candidates, key=lambda s: len(s))
                        suggestion = candidates_sorted[0]
                        method = "heuristic-line"
                        excerpt = suggestion[:300]

                if suggestion:
                    rows.append([c.id, c.name, c.website_url, suggestion, method, excerpt])
                    found += 1
                    self.stdout.write(f"Found {c.id} {c.name} ({method})")
                else:
                    self.stdout.write(f"No addr for {c.id} {c.name}")
            except Exception as e:
                self.stdout.write(f"Error {c.id} {e}")
            time.sleep(delay)

        # write CSV
        with open("suggested_addresses.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "name", "website_url", "suggested_address", "method", "excerpt"])
            for r in rows:
                w.writerow(r)

        self.stdout.write(json.dumps({"candidates": qs.count(), "found": found, "csv": "suggested_addresses.csv"}, ensure_ascii=False))
