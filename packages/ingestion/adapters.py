"""Collection stays separate from rule review. All extraction is needs_review."""
import csv
import hashlib
import io
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from html import unescape
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class RegulatoryAdapter(Protocol):
    def fetch(self, url): ...
    def extract_metadata(self, content, url): ...
    def snapshot(self, content): ...
    def normalize_candidate_rules(self, records): ...


class GenericPageAdapter:
    allowed_hosts = None

    def fetch(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Source collection requires a public HTTPS URL')
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise ValueError('URL is outside this adapter source registry')
        for address in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
            if not ipaddress.ip_address(address[4][0]).is_global:
                raise ValueError('Private source URLs are not allowed')
        # No redirects: a public source must not redirect collection into private networks.
        from urllib.request import HTTPRedirectHandler, build_opener
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError('Source redirects require a new registered URL')
        with build_opener(NoRedirect).open(Request(url, headers={'User-Agent':'ClearedForTakeoff/1.0 evidence-snapshot'}), timeout=10) as response:
            content = response.read(2_000_001)
            if len(content) > 2_000_000:
                raise ValueError('Source exceeds 2 MB collection limit')
            return content.decode('utf-8', errors='replace')

    def extract_metadata(self, content, url):
        title = re.search(r'<title[^>]*>(.*?)</title>', content, re.S | re.I)
        return {'canonical_url':url,'title':unescape(re.sub('<[^>]+>', '', title[1])).strip() if title else url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_tier':'official' if self.allowed_hosts else 'authoritative_secondary'}

    def snapshot(self, content):
        return {'content_hash':hashlib.sha256(content.encode()).hexdigest(),'content':content}

    def normalize_candidate_rules(self, records):
        return [{**r,'review_status':'needs_review','last_verified_at':None} for r in records]


class ECFRAdapter(GenericPageAdapter):
    allowed_hosts = {'www.ecfr.gov','ecfr.gov'}


class EURLexAdapter(GenericPageAdapter):
    allowed_hosts = {'eur-lex.europa.eu'}


class GeographyProvider(Protocol):
    def countries(self): ...
    def routes(self, jurisdiction): ...


class CachedGeographyProvider:
    def __init__(self, dataset):
        self.dataset = dataset

    def countries(self):
        return [{'iso_code':j['iso_code'],'latitude':j.get('latitude'),'longitude':j.get('longitude'),'source':'imported dataset'} for j in self.dataset.get('jurisdictions',[])]

    def routes(self, jurisdiction):
        return [r for r in self.dataset.get('routes',[]) if r['jurisdiction'] == jurisdiction]


class LogisticsAdapter(Protocol):
    def normalize(self, records): ...


class JSONLogisticsAdapter:
    def normalize(self, records):
        results = []
        for record in records:
            if not record.get('jurisdiction') or not record.get('source_url'):
                raise ValueError('Logistics event requires jurisdiction and source_url')
            if float(record.get('transit_delay_days',0)) < 0:
                raise ValueError('Disruption delay cannot be negative')
            results.append({**record,'event_type':'logistics','review_status':'needs_review'})
        return results


def parse_records(payload):
    if isinstance(payload.get('records'),list):
        return payload['records']
    if isinstance(payload.get('csv'),str):
        rows = list(csv.DictReader(io.StringIO(payload['csv'])))
        for row in rows:
            try:
                row['value'] = json.loads(row['value'])
            except (ValueError, KeyError):
                pass
            for key in ('confidence',):
                if row.get(key):
                    row[key] = float(row[key])
            for key in ('effective_to','supersedes_id'):
                if not row.get(key):
                    row[key] = None
        return rows
    raise ValueError('Supply records array or CSV text')


def field_diff(old, new):
    return [{'field':key,'before':old.get(key),'after':new.get(key)} for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)]
