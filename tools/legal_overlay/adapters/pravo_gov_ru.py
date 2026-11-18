"""Conservative read-only adapter for the legacy pravo.gov.ru IPS."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_from_bytes, urljoin, urlparse

import httpx

from ..config import ConfigurationError, ProviderConnection
from ..models import ProviderDescriptor, ProviderHealth
from .base import ProviderAdapter


DEFAULT_ENDPOINT = "http://pravo.gov.ru/proxy/ips/"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PAGE_CHARS = 200_000
EMPTY_TEXT_RETRIES = 1
TOOL_NAMES = {"pravo_resolve_act", "pravo_get_document", "pravo_get_article"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "fieldset", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "td", "th", "tr", "ul",
}


class _PortalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.anchors: list[dict[str, str]] = []
        self._skip_depth = 0
        self._anchor: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self._anchor = {"href": attributes.get("href", ""), "id": attributes.get("id", ""), "text": []}

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._anchor is not None:
            self.anchors.append(
                {
                    "href": str(self._anchor["href"]),
                    "id": str(self._anchor["id"]),
                    "text": _normalize_space(" ".join(self._anchor["text"])),
                }
            )
            self._anchor = None
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self.parts.append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)

    def text(self) -> str:
        lines = (_normalize_space(line) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_identity(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    return re.sub(r"[^0-9a-zа-я]+", "", value)


def _parse_date(value: Any) -> date:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ValueError("act_date must use YYYY-MM-DD or DD.MM.YYYY")


def _validate_act_number(value: Any) -> str:
    number = str(value or "")
    if not number or number != number.strip() or len(number) > 120 or any(char in number for char in "\r\n\t"):
        raise ValueError("act_number must be a trimmed single-line value of at most 120 characters")
    try:
        number.encode("cp1251", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("act_number must be representable in CP1251") from exc
    return number


def _validate_nd(value: Any) -> str:
    nd = str(value or "").strip()
    if not re.fullmatch(r"\d{6,30}", nd):
        raise ValueError("nd must contain 6-30 digits")
    return nd


def build_search_url(act_number: Any, act_date: Any) -> str:
    number = _validate_act_number(act_number)
    parsed_date = _parse_date(act_date)
    encoded_number = quote_from_bytes(number.encode("cp1251"), safe="")
    query = "&".join(
        (
            "list_itself=", "bpas=cd00000", "a7type=1",
            f"a7date={parsed_date.strftime('%d.%m.%Y')}",
            f"a8={encoded_number}", "a8type=2", "textpres=yes", "sort=7", "page=firstlast",
        )
    )
    return f"{DEFAULT_ENDPOINT}?{query}"


def build_document_url(nd: Any) -> str:
    return f"{DEFAULT_ENDPOINT}?doc_itself=&nd={_validate_nd(nd)}&fulltext=1"


def _validated_portal_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "pravo.gov.ru"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/proxy/ips/"
        or parsed.fragment
    ):
        raise ValueError("portal URL failed the pravo.gov.ru allowlist")
    return value


def _candidate_from_anchor(anchor: dict[str, str]) -> dict[str, str] | None:
    href = anchor.get("href", "")
    if not href:
        return None
    try:
        url = _validated_portal_url(urljoin(DEFAULT_ENDPOINT, href))
    except (TypeError, ValueError):
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False)
    if any(len(values) != 1 for values in query.values()):
        return None
    docbody_keys = set(query)
    if docbody_keys in ({"docbody", "link_id", "nd"}, {"docbody", "link_id", "nd", "firstDoc"}):
        link_id = query["link_id"][0]
        if not re.fullmatch(r"\d{1,6}", link_id) or anchor.get("id") != f"link_{link_id}":
            return None
        if "firstDoc" in query and query["firstDoc"][0] != "1":
            return None
    elif set(query) == {"doc_itself", "nd", "fulltext"}:
        if query["fulltext"][0] != "1":
            return None
    else:
        return None
    try:
        nd = _validate_nd(query["nd"][0])
    except ValueError:
        return None
    return {"nd": nd, "label": anchor.get("text", ""), "document_url": build_document_url(nd)}


def _validated_health_redirect(location: str) -> str:
    target = _validated_portal_url(urljoin(DEFAULT_ENDPOINT, location))
    query = parse_qs(urlparse(target).query, keep_blank_values=True, strict_parsing=False)
    if query != {"start_search": [""], "fattrib": ["1"]}:
        raise ValueError("portal root returned an unexpected redirect target")
    return target


class PravoGovRuAdapter(ProviderAdapter):
    def __init__(
        self,
        connection: ProviderConnection,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.connection = connection
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id=self.connection.provider_id,
            adapter=self.connection.adapter,
            enabled=self.connection.enabled,
            configured=self.connection.configured,
            endpoint=self.connection.endpoint or DEFAULT_ENDPOINT,
            priority=self.connection.priority,
            capabilities=self.connection.capabilities,
            transitional_external_proxy=False,
            missing_secrets=self.connection.missing_secrets,
        )

    def owns_tool(self, name: str) -> bool:
        return name in TOOL_NAMES

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
            headers={"User-Agent": "legal-copilot-local-overlay/0.2"},
        )

    def _get(self, url: str) -> bytes:
        _validated_portal_url(url)
        with self._client() as client, client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("pravo.gov.ru response exceeds the 8 MiB safety limit")
                chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _parse(content: bytes) -> _PortalParser:
        parser = _PortalParser()
        parser.feed(content.decode("cp1251", errors="replace"))
        parser.close()
        return parser

    def _fetch_with_text(self, url: str) -> _PortalParser | None:
        """Parsed page with non-empty text, or None after one retry.

        The portal occasionally answers with a page that carries no text at all.
        Such a page is a fetch failure, not evidence that an act or article is
        absent, so it is requested once more and never reported as NOT_FOUND.
        """
        for _attempt in range(1 + EMPTY_TEXT_RETRIES):
            parser = self._parse(self._get(url))
            if parser.text():
                return parser
        return None

    @staticmethod
    def _empty_text_failure(reason: str, **context: Any) -> dict[str, Any]:
        return {
            "status": "FAILED",
            "reason": reason,
            **context,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }

    def health(self) -> ProviderHealth:
        if not self.connection.enabled:
            return ProviderHealth(self.connection.provider_id, "disabled")
        try:
            with self._client() as client:
                response = client.get(DEFAULT_ENDPOINT)
            if response.status_code == 200:
                return ProviderHealth(
                    self.connection.provider_id,
                    "connected",
                    data={"probe": "portal_root", "behavior": "direct_response"},
                )
            if response.status_code in {301, 302, 307, 308}:
                location = response.headers.get("location", "")
                target = _validated_health_redirect(location)
                return ProviderHealth(
                    self.connection.provider_id,
                    "connected",
                    data={
                        "probe": "portal_root",
                        "behavior": "expected_same_portal_redirect",
                        "target": target,
                    },
                )
            response.raise_for_status()
        except Exception as exc:
            return ProviderHealth(self.connection.provider_id, "not_responding", detail=str(exc))
        return ProviderHealth(self.connection.provider_id, "not_responding", detail="unexpected portal response")

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "pravo_resolve_act",
                "description": "Resolve one Russian act on pravo.gov.ru by exact number and date; never auto-selects ambiguous results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "act_number": {"type": "string"},
                        "act_date": {"type": "string", "description": "YYYY-MM-DD or DD.MM.YYYY"},
                        "title_hint": {"type": "string"},
                    },
                    "required": ["act_number", "act_date"],
                },
            },
            {
                "name": "pravo_get_document",
                "description": "Get a bounded page of official document text by a previously resolved pravo.gov.ru nd.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nd": {"type": "string", "pattern": "^[0-9]{6,30}$"},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_PAGE_CHARS, "default": 50000},
                    },
                    "required": ["nd"],
                },
            },
            {
                "name": "pravo_get_article",
                "description": "Fetch an official pravo.gov.ru document by nd and return one bounded article section.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "nd": {"type": "string", "pattern": "^[0-9]{6,30}$"},
                        "article_number": {"type": ["string", "number"]},
                    },
                    "required": ["nd", "article_number"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "pravo_resolve_act":
            return self.resolve_act(
                arguments.get("act_number"),
                arguments.get("act_date"),
                title_hint=str(arguments.get("title_hint") or "").strip(),
            )
        if name == "pravo_get_document":
            return self.get_document(
                arguments.get("nd"),
                offset=arguments.get("offset", 0),
                limit=arguments.get("limit", 50_000),
            )
        if name == "pravo_get_article":
            return self.get_article(arguments.get("nd"), arguments.get("article_number"))
        raise KeyError(f"unknown pravo.gov.ru tool: {name}")

    def resolve_act(self, act_number: Any, act_date: Any, *, title_hint: str = "") -> dict[str, Any]:
        number = _validate_act_number(act_number)
        parsed_date = _parse_date(act_date)
        search_url = build_search_url(number, parsed_date)
        retrieved_at = datetime.now(timezone.utc).isoformat()
        try:
            search_parser = self._fetch_with_text(search_url)
        except Exception as exc:
            return {"status": "FAILED", "reason": str(exc), "search_url": search_url, "retrieved_at": retrieved_at}
        if search_parser is None:
            return self._empty_text_failure("empty_search_response", search_url=search_url)

        candidates_by_nd: dict[str, dict[str, str]] = {}
        for anchor in search_parser.anchors:
            candidate = _candidate_from_anchor(anchor)
            if candidate is not None:
                candidates_by_nd.setdefault(candidate["nd"], candidate)
        candidates = list(candidates_by_nd.values())
        if not candidates:
            return {"status": "NOT_FOUND", "candidates": [], "search_url": search_url, "retrieved_at": retrieved_at}
        if len(candidates) > 1:
            return {"status": "AMBIGUOUS", "candidates": candidates, "search_url": search_url, "retrieved_at": retrieved_at}

        candidate = candidates[0]
        try:
            document_parser = self._fetch_with_text(candidate["document_url"])
        except Exception as exc:
            return {
                "status": "FAILED", "reason": str(exc), "candidates": candidates,
                "search_url": search_url, "retrieved_at": retrieved_at,
            }
        if document_parser is None:
            return self._empty_text_failure(
                "empty_document_text", candidates=candidates, search_url=search_url
            )
        document_text = document_parser.text()
        search_text = search_parser.text()
        combined_identity = _normalize_identity(f"{candidate['label']} {search_text} {document_text[:100000]}")
        number_confirmed = _normalize_identity(number) in combined_identity
        date_confirmed = parsed_date.strftime("%d.%m.%Y") in search_text
        title_confirmed = True
        if title_hint:
            title_confirmed = _normalize_identity(title_hint) in combined_identity
        if not number_confirmed or not date_confirmed or not title_confirmed:
            return {
                "status": "FAILED",
                "reason": "resolved candidate did not pass identity checks",
                "candidate": candidate,
                "identity": {
                    "number_confirmed": number_confirmed,
                    "date_confirmed": date_confirmed,
                    "title_hint_confirmed": title_confirmed,
                },
                "search_url": search_url,
                "retrieved_at": retrieved_at,
            }
        return {
            "status": "RESOLVED",
            "act_number": number,
            "act_date": parsed_date.isoformat(),
            "nd": candidate["nd"],
            "label": candidate["label"],
            "document_url": candidate["document_url"],
            "search_url": search_url,
            "retrieved_at": retrieved_at,
            "content_hash": hashlib.sha256(document_text.encode("utf-8")).hexdigest(),
            "total_chars": len(document_text),
            "identity": {
                "number_confirmed": True,
                "date_confirmed": True,
                "title_hint_confirmed": title_confirmed,
            },
        }

    def get_document(self, nd: Any, *, offset: Any = 0, limit: Any = 50_000) -> dict[str, Any]:
        document_id = _validate_nd(nd)
        try:
            start = int(offset)
            page_size = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("offset and limit must be integers") from exc
        if start < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= page_size <= MAX_PAGE_CHARS:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_CHARS}")
        url = build_document_url(document_id)
        parser = self._fetch_with_text(url)
        if parser is None:
            return self._empty_text_failure("empty_document_text", nd=document_id, source_url=url)
        full_text = parser.text()
        total = len(full_text)
        end = min(start + page_size, total)
        truncated = end < total
        return {
            "status": "OK",
            "nd": document_id,
            "source_url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            "total_chars": total,
            "offset": start,
            "limit": page_size,
            "next_offset": end if truncated else None,
            "truncated": truncated,
            "text": full_text[start:end],
        }

    def get_article(self, nd: Any, article_number: Any) -> dict[str, Any]:
        document_id = _validate_nd(nd)
        number = str(article_number or "").strip()
        number = re.sub(r"(?i)^статья\s+|^ст\.\s*", "", number).strip().rstrip(".")
        if not re.fullmatch(r"\d+(?:\.\d+)*", number):
            raise ValueError("article_number must contain a numeric article identifier")
        url = build_document_url(document_id)
        parser = self._fetch_with_text(url)
        if parser is None:
            return self._empty_text_failure(
                "empty_document_text", nd=document_id, article_number=number, source_url=url
            )
        full_text = parser.text()
        heading = re.compile(
            rf"(?im)^\s*статья\s+{re.escape(number)}(?!\d)(?!\.\d)"
            r"(?:\s*[.\-–—:]?\s*.*)?$"
        )
        match = heading.search(full_text)
        if match is None:
            return {
                "status": "NOT_FOUND",
                "nd": document_id,
                "article_number": number,
                "source_url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            }
        next_heading = re.compile(r"(?im)^\s*статья\s+\d+(?:\.\d+)*\b").search(full_text, match.end())
        end = next_heading.start() if next_heading else len(full_text)
        article_text = full_text[match.start() : end].strip()
        truncated = len(article_text) > MAX_PAGE_CHARS
        return {
            "status": "OK",
            "nd": document_id,
            "article_number": number,
            "source_url": url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            "article_hash": hashlib.sha256(article_text.encode("utf-8")).hexdigest(),
            "text": article_text[:MAX_PAGE_CHARS],
            "truncated": truncated,
        }
