from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_FILE = BASE_DIR / "products.json"
OUTPUT_DIR = BASE_DIR / "output"
JSON_OUT = OUTPUT_DIR / "price_report.json"
MD_OUT = OUTPUT_DIR / "price_report.md"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

UNAVAILABLE_MARKERS = [
    "tijdelijk niet leverbaar",
    "helaas niet meer beschikbaar",
    "niet leverbaar",
    "price & voorraadmelding",
]


@dataclass
class ProductResult:
    name: str
    url: str
    price_eur: float | None
    price_text: str | None
    available: bool
    note: str | None = None


def load_products() -> list[dict[str, str]]:
    return json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))


def normalize_price(value: str) -> float | None:
    cleaned = value.replace("€", "").replace("\xa0", " ").strip()
    cleaned = cleaned.replace(".", "").replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def format_eur(value: float) -> str:
    euros = f"{value:,.2f}"
    euros = euros.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {euros}"


def extract_price_from_json_ld(soup: BeautifulSoup) -> float | None:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items: list[Any]
        if isinstance(data, list):
            items = data
        else:
            items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price")
                if price is not None:
                    parsed = normalize_price(str(price))
                    if parsed is not None:
                        return parsed
    return None


def extract_price_from_meta(soup: BeautifulSoup) -> float | None:
    meta_candidates = [
        ("meta", {"property": "product:price:amount"}, "content"),
        ("meta", {"property": "og:price:amount"}, "content"),
        ("meta", {"itemprop": "price"}, "content"),
        ("meta", {"name": "price"}, "content"),
    ]
    for tag_name, attrs, attr_name in meta_candidates:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get(attr_name):
            parsed = normalize_price(str(tag[attr_name]))
            if parsed is not None:
                return parsed
    return None


def extract_price_from_text(html: str, soup: BeautifulSoup) -> float | None:
    # Prefer prices near purchase CTA labels.
    snippets = []
    lower_html = html.lower()
    for marker in ["in winkelmand", "bestel", "prijs", "meest getoonde prijs"]:
        idx = lower_html.find(marker)
        if idx != -1:
            start = max(0, idx - 300)
            end = min(len(html), idx + 300)
            snippets.append(html[start:end])

    # Add a soup text fallback.
    snippets.append(soup.get_text(" ", strip=True))

    pattern = re.compile(r"€\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})")
    candidates: list[float] = []
    for snippet in snippets:
        for match in pattern.findall(snippet):
            parsed = normalize_price(match)
            if parsed is not None:
                candidates.append(parsed)

    if not candidates:
        return None

    # Heuristic: first reasonable non-zero price usually is the live product price.
    for price in candidates:
        if price > 0:
            return price
    return None


def scrape_product(session: requests.Session, product: dict[str, str]) -> ProductResult:
    response = session.get(product["url"], timeout=30)
    response.raise_for_status()

    html = response.text
    lowered = html.lower()
    soup = BeautifulSoup(html, "html.parser")

    unavailable = any(marker in lowered for marker in UNAVAILABLE_MARKERS)

    price = (
        extract_price_from_json_ld(soup)
        or extract_price_from_meta(soup)
        or extract_price_from_text(html, soup)
    )

    if unavailable and price is None:
        return ProductResult(
            name=product["name"],
            url=product["url"],
            price_eur=None,
            price_text=None,
            available=False,
            note="Product appears unavailable",
        )

    if price is None:
        return ProductResult(
            name=product["name"],
            url=product["url"],
            price_eur=None,
            price_text=None,
            available=not unavailable,
            note="Could not extract price",
        )

    return ProductResult(
        name=product["name"],
        url=product["url"],
        price_eur=price,
        price_text=format_eur(price),
        available=not unavailable,
        note=None if not unavailable else "Product may be unavailable but price was still found",
    )


def build_markdown(results: list[ProductResult], total: float, timestamp: str) -> str:
    lines = [
        "# Daily Megekko price report",
        "",
        f"Generated: `{timestamp}`",
        "",
        "| Product | Status | Price |",
        "|---|---:|---:|",
    ]
    for item in results:
        status = "available" if item.available else "unavailable"
        price = item.price_text or "-"
        lines.append(f"| [{item.name}]({item.url}) | {status} | {price} |")
    lines.extend([
        "",
        f"**Total:** {format_eur(total)}",
        "",
    ])
    unavailable_notes = [f"- {item.name}: {item.note}" for item in results if item.note]
    if unavailable_notes:
        lines.append("## Notes")
        lines.append("")
        lines.extend(unavailable_notes)
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    products = load_products()
    session = requests.Session()
    session.headers.update(HEADERS)

    results = [scrape_product(session, product) for product in products]
    total = sum(item.price_eur or 0.0 for item in results if item.available and item.price_eur is not None)
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    payload = {
        "generated_at": timestamp,
        "currency": "EUR",
        "total_eur": round(total, 2),
        "products": [asdict(item) for item in results],
    }

    JSON_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MD_OUT.write_text(build_markdown(results, total, timestamp), encoding="utf-8")

    print(f"Wrote {JSON_OUT}")
    print(f"Wrote {MD_OUT}")
    print(f"Total: {format_eur(total)}")


if __name__ == "__main__":
    main()
