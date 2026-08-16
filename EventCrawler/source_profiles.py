import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urlunparse


@dataclass(frozen=True)
class SourceProfile:
    key: str
    base_url: str
    event_url_re: re.Pattern
    event_link_selectors: tuple[str, ...]
    event_path_marker: str
    product_selectors: tuple[str, ...] = ()
    product_name_selectors: tuple[str, ...] = ()
    price_selectors: tuple[str, ...] = ()
    availability_selectors: tuple[str, ...] = ()

    def parse_event_ref(self, href: str | None):
        match = self.event_url_re.search(href or "")
        if not match:
            return None
        external_id = match.group("id")
        slug = match.groupdict().get("slug") or f"{self.key}-{external_id}"
        return {"slug": slug, "external_id": external_id, "source": self.key}

    def normalize_event_url(self, url: str | None):
        if not url:
            return url
        absolute = urljoin(self.base_url, str(url).strip())
        parsed = urlparse(absolute)
        path = re.sub(r"/+", "/", parsed.path).rstrip("/")
        match = self.event_url_re.search(path)
        if match:
            if self.key == "kiwol":
                return f"{self.base_url}/billetterie/{match.group('id')}"
            return f"{self.base_url}/events/details/{match.group('slug')}/{match.group('id')}"
        return urlunparse(("https", parsed.netloc.lower(), path, "", "", ""))


SOURCE_PROFILES = {
    "bizouk": SourceProfile(
        key="bizouk",
        base_url="https://www.bizouk.com",
        event_url_re=re.compile(r"/events/details/(?P<slug>[^/]+)/(?P<id>\d+)"),
        event_link_selectors=("a[href*='/events/details/']",),
        event_path_marker="/events/details/",
        product_selectors=("[class*='ticket']", "[class*='billet']", "[data-ticket-id]", "[data-product-id]"),
        product_name_selectors=("[class*='name']", "[class*='title']", "h3", "h4", "strong"),
        price_selectors=("[class*='price']", "[data-price]"),
        availability_selectors=("[class*='status']", "[class*='availability']", "button", "input"),
    ),
    "kiwol": SourceProfile(
        key="kiwol",
        base_url="https://www.kiwol.com",
        event_url_re=re.compile(r"/billetterie/(?P<id>\d+)"),
        event_link_selectors=("a.ticketing-card-search-container[href]", "a[href*='/billetterie/']"),
        event_path_marker="/billetterie/",
    ),
}


def detect_source(url: str | None):
    host = (urlparse(url or "").netloc or "").lower()
    if "kiwol.com" in host:
        return "kiwol"
    return "bizouk"


def get_source_profile(source_or_url: str | None):
    source = source_or_url if source_or_url in SOURCE_PROFILES else detect_source(source_or_url)
    return SOURCE_PROFILES.get(source, SOURCE_PROFILES["bizouk"])


def source_base_url(source: str | None):
    return get_source_profile(source).base_url


def normalize_event_url(url: str | None, source: str | None = None):
    profile = get_source_profile(source or url)
    return profile.normalize_event_url(url)


def parse_event_ref(href: str | None, source: str | None = None):
    profile = get_source_profile(source or href)
    return profile.parse_event_ref(href)
