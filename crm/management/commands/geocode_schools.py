from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
from decimal import Decimal

from django.core.management.base import BaseCommand

from crm.models import Customer


class Command(BaseCommand):
    help = "Geocode school customers using OSM Nominatim and save latitude/longitude."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Limit number of schools to process")
        parser.add_argument("--dry-run", action="store_true", default=False, help="Do not save results")
        parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests (respect Nominatim)")
        parser.add_argument("--photon-only", action="store_true", default=False, help="Use Photon (komoot) as the primary geocoder and skip Nominatim")

    def handle(self, *args, **options):
        limit = options.get("limit")
        dry_run = options.get("dry_run")
        delay = float(options.get("delay") or 1.0)
        photon_only = bool(options.get("photon_only"))

        qs = Customer.objects.filter(customer_type__key="school")
        qs = qs.filter(latitude__isnull=True, longitude__isnull=True)
        total = qs.count()
        if limit:
            qs = qs[:limit]

        self.stdout.write(f"Geocoding {qs.count()} schools (total missing coords: {total}), dry_run={dry_run}, delay={delay}s")

        headers = {"User-Agent": "beets-tasks-geocoder/1.0 (+https://tasks.beets3d.cn)"}

        def clean_text(s: str) -> str:
            if not s:
                return ""
            # remove common noise and labels, keep first meaningful line
            s = s.replace('\r', '\n')
            # strip labels
            for label in ['地址：', '地址:', 'Contact:', 'Contact：', '聯絡人', '電話', 'Tel:', 'Tel：']:
                s = s.replace(label, ' ')
            # only keep first line which usually contains street info
            first = s.split('\n', 1)[0].strip()
            # collapse whitespace
            first = ' '.join(first.split())
            return first

        def build_candidate_queries(obj: Customer) -> list:
            # try different query forms from most specific to fallback
            sa = clean_text(obj.street_address or '')
            city = (obj.city or '').strip()
            country = (obj.country or '').strip() or 'Hong Kong'
            company = clean_text(obj.company_name or '')
            name = clean_text(obj.name or '')

            candidates = []
            # prefer street + city + country
            if sa:
                candidates.append(' '.join([sa, city, country]).strip())
                candidates.append(' '.join([sa, country]).strip())
            # try company or school name with city/country
            if company:
                candidates.append(' '.join([company, city, country]).strip())
            if name:
                candidates.append(' '.join([name, city, country]).strip())
            # lastly try the original verbose combination
            parts = [obj.street_address or '', obj.city or '', obj.state or '', obj.zip_code or '', obj.country or '', obj.company_name or '', obj.name or '']
            verbose = ' '.join([p.strip() for p in parts if p and p.strip()])
            if verbose and verbose not in candidates:
                candidates.append(verbose)
            # dedupe while preserving order
            seen = set()
            out = []
            for c in candidates:
                if c and c not in seen:
                    seen.add(c)
                    out.append(c)
            return out

        def try_photon(query: str):
            # Photon (komoot) is a public geocoder that can be used as a fallback
            try:
                import requests

                r = requests.get("https://photon.komoot.io/api/", params={"q": query, "limit": 1}, headers=headers, timeout=10)
                js = r.json()
                feats = js.get("features") or []
                if not feats:
                    return None
                geom = feats[0].get("geometry") or {}
                coords = geom.get("coordinates") or []
                if len(coords) >= 2:
                    # photon returns [lon, lat]
                    return (Decimal(str(coords[1])), Decimal(str(coords[0])))
            except Exception:
                return None
            return None

        for obj in qs.iterator():
            queries = build_candidate_queries(obj)
            if not queries:
                self.stdout.write(f"SKIP {obj.id} no address fields")
                continue

            # Try Photon-only mode if requested
            if photon_only:
                got = False
                for query in queries:
                    coords = try_photon(query)
                    if coords:
                        lat, lon = coords
                        if dry_run:
                            self.stdout.write(f"FOUND (dry-photon) {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        else:
                            obj.latitude = lat
                            obj.longitude = lon
                            obj.save(update_fields=["latitude", "longitude"])
                            self.stdout.write(f"SAVED (photon) {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        got = True
                        break
                    else:
                        self.stdout.write(f"PHOTON NO RESULT {obj.id} {obj.name} for '{query[:120]}'")
                    time.sleep(delay)
                if got:
                    continue

            data = []
            for idx, query in enumerate(queries):
                q = urllib.parse.quote_plus(query)
                url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={q}"
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        body = resp.read().decode("utf-8")
                        data = json.loads(body)
                except Exception as exc:
                    self.stderr.write(f"ERROR {obj.id} {obj.name}: {exc}")
                    data = []

                if data:
                    hit = data[0]
                    try:
                        lat = Decimal(str(hit.get("lat")))
                        lon = Decimal(str(hit.get("lon")))
                    except Exception as exc:
                        self.stderr.write(f"PARSE ERROR {obj.id}: {exc}")
                        lat = lon = None

                    if lat is not None and lon is not None:
                        if dry_run:
                            self.stdout.write(f"FOUND (dry) {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        else:
                            obj.latitude = lat
                            obj.longitude = lon
                            obj.save(update_fields=["latitude", "longitude"])
                            self.stdout.write(f"SAVED {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        break
                    else:
                        self.stdout.write(f"NO COORDS {obj.id} {obj.name} for query '{query[:120]}'")
                else:
                    # Try Photon as fallback for this query
                    photon_coords = try_photon(query)
                    if photon_coords:
                        lat, lon = photon_coords
                        if dry_run:
                            self.stdout.write(f"FOUND (dry-photon) {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        else:
                            obj.latitude = lat
                            obj.longitude = lon
                            obj.save(update_fields=["latitude", "longitude"])
                            self.stdout.write(f"SAVED (photon-fallback) {obj.id} {obj.name} -> {lat},{lon} (query: {query[:80]})")
                        break
                    else:
                        self.stdout.write(f"NO RESULT {obj.id} {obj.name} for '{query[:120]}'")

                # be polite and delay between attempts
                time.sleep(delay)

        self.stdout.write("Done")
