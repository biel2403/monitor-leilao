from __future__ import annotations

import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from auction_monitor.models import RawLot
from auction_monitor.scrapers.base import AuctionScraper


BASE_URL = "https://www.freitasleiloeiro.com.br"
LIST_URL = BASE_URL + "/Leiloes/PesquisarLotes"


class Node:
    def __init__(self, tag: str = "", attrs: dict[str, str] | None = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node | str] = []

    def text(self) -> str:
        return " ".join(part.text() if isinstance(part, Node) else part for part in self.children).strip()

    def find(self, class_name: str) -> list[Node]:
        found = [self] if class_name in self.attrs.get("class", "").split() else []
        for child in self.children:
            if isinstance(child, Node):
                found.extend(child.find(class_name))
        return found

    def tags(self, tag: str) -> list[Node]:
        found = [self] if self.tag == tag else []
        for child in self.children:
            if isinstance(child, Node):
                found.extend(child.tags(tag))
        return found


class FragmentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in {"area", "br", "hr", "img", "input", "link", "meta", "source"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].children.append(data.strip())


def first_text(card: Node, class_name: str) -> str | None:
    matches = card.find(class_name)
    return matches[0].text() if matches else None


def parse_money(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"R\$\s*([\d.]+,\d{2})", value)
    return float(match.group(1).replace(".", "").replace(",", ".")) if match else None


def parse_lots(html: str) -> list[RawLot]:
    parser = FragmentParser()
    parser.feed(html)
    lots = []
    for card in parser.root.find("cardlote"):
        title = first_text(card, "cardLote-descVeic") or first_text(card, "cardLote-desc")
        link = next((node.attrs.get("href") for node in card.tags("a") if "LoteDetalhes" in node.attrs.get("href", "")), None)
        if not title or not link:
            continue
        url = urllib.parse.urljoin(BASE_URL, link)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        auction_id = params.get("leilaoId", [None])[0]
        lot_number = params.get("loteNumero", [None])[0]
        if not auction_id or not lot_number:
            continue
        date_text = first_text(card, "cardLote-data")
        closes_at = None
        if date_text:
            try:
                closes_at = datetime.strptime(" ".join(date_text.split()), "%d/%m/%Y %H:%M").isoformat()
            except ValueError:
                pass
        year_match = re.search(r"\b(\d{2})/(\d{2})\b", title)
        year = None
        if year_match:
            value = int(year_match.group(2))
            year = 2000 + value if value <= 35 else 1900 + value
        image = next((node.attrs.get("src") for node in card.tags("img") if "cardLote-img" in node.attrs.get("class", "")), None)
        price = parse_money(first_text(card, "cardLote-vlr"))
        price_label = (first_text(card, "cardLote-lance") or "").lower()
        lot = RawLot(
            title=title,
            url=url,
            external_id=f"{auction_id}:{lot_number}",
            source_site="Freitas Leiloeiro",
            category="veiculos",
            brand=title.removeprefix("I/").split("/", 1)[0].strip() if "/" in title else None,
            year=year,
            current_bid=price if "lance" in price_label else None,
            initial_value=price if "lance" not in price_label else None,
            closes_at=closes_at,
            images=[urllib.parse.urljoin(BASE_URL, image)] if image else [],
            auctioneer="Freitas Leiloeiro",
            status=first_text(card, "cardLote-btn"),
        )
        lots.append(lot)
    return lots


def trusted_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Freitas sends an obsolete intermediate; complete its chain without disabling verification.
    context.load_verify_locations(cafile=str(Path(__file__).resolve().parents[1] / "certs" / "globalsign-alphassl-2025.pem"))
    if hasattr(ssl, "enum_certificates"):
        for store in ("ROOT", "CA"):
            for certificate, encoding, _ in ssl.enum_certificates(store):
                if encoding == "x509_asn":
                    context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    return context


def decode_page(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def parse_detail(html: str) -> dict[str, Any]:
    parser = FragmentParser()
    parser.feed(html)
    descriptors = [
        node for node in parser.root.find("text-secondary")
        if {"d-flex", "flex-column"}.issubset(node.attrs.get("class", "").split())
    ]
    classification = None
    for descriptor in descriptors:
        for span in descriptor.tags("span"):
            if {"fw-bold", "small"}.issubset(span.attrs.get("class", "").split()):
                classification = span.text().strip()
                break
        if classification:
            break
    if not classification:
        raise ValueError("Classificacao do lote indisponivel")

    commission = None
    fixed_fees = 0.0
    for item in parser.root.tags("li"):
        label = " ".join(item.text().split())
        if "comiss" in label.lower() and "leiloeiro" in label.lower():
            match = re.search(r"(\d+(?:,\d+)?)\s*%", label)
            if match:
                commission = float(match.group(1).replace(",", "."))
        elif "despesas" in label.lower() and "comprador" in label.lower():
            amount = parse_money(label)
            if amount is not None:
                fixed_fees += amount
    if commission is None:
        raise ValueError("Comissao do lote indisponivel")
    condition_nodes = [
        node for node in parser.root.find("text-secondary")
        if {"pt-2", "small"}.issubset(node.attrs.get("class", "").split())
    ]
    condition_text = " ".join(condition_nodes[0].text().split()) if condition_nodes else ""
    links = [urllib.parse.urljoin(BASE_URL, node.attrs.get("href", "")) for node in parser.root.tags("a")]
    image_urls = [
        url for url in dict.fromkeys(links)
        if re.search(r"/FOTOS/.*\.(?:jpe?g|png|webp)$", urllib.parse.urlparse(url).path, re.I)
        and urllib.parse.urlparse(url).hostname.endswith(".freitasleiloeiro.com.br")
    ][:4]
    notice_url = next((url for url in links if "/edital/" in urllib.parse.urlparse(url).path.lower()), None)
    return {
        "classification": classification,
        "commission_percent": commission,
        "fixed_fees": fixed_fees,
        "condition_text": condition_text,
        "image_urls": image_urls,
        "notice_url": notice_url,
    }


class FreitasScraper(AuctionScraper):
    source_name = "Freitas Leiloeiro"

    def __init__(self, max_pages: int = 50, delay_seconds: float = 1.0):
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds

    def fetch_lots(self) -> list[RawLot]:
        lots: list[RawLot] = []
        seen: set[str] = set()
        context = trusted_context()
        for page in range(1, self.max_pages + 1):
            query = urllib.parse.urlencode({"Categoria": 1, "TipoLoteId": 0, "PageNumber": page, "TopRows": 12})
            request = urllib.request.Request(
                f"{LIST_URL}?{query}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "Accept": "text/html"},
            )
            with urllib.request.urlopen(request, timeout=20, context=context) as response:
                html = decode_page(response.read())
            if "Erro ao tentar retornar os dados" in html:
                raise ValueError(f"Freitas retornou erro na pagina {page}")
            page_lots = parse_lots(html)
            if page == 1 and not page_lots and "Nenhum lote localizado" not in html:
                raise ValueError("Freitas retornou uma pagina sem cartoes de lote")
            fresh = [lot for lot in page_lots if lot.external_id not in seen]
            if not fresh:
                break
            lots.extend(fresh)
            seen.update(lot.external_id for lot in fresh)
            if len(page_lots) < 12:
                break
            time.sleep(self.delay_seconds)
        return lots

    def fetch_detail(self, url: str) -> dict[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "www.freitasleiloeiro.com.br" or parsed.path.lower() != "/leiloes/lotedetalhes":
            raise ValueError("URL de lote invalida")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36", "Accept": "text/html"},
        )
        with urllib.request.urlopen(request, timeout=20, context=trusted_context()) as response:
            return parse_detail(decode_page(response.read()))
