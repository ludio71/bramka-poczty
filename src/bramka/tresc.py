"""Obróbka treści maili: struktura MIME z BODYSTRUCTURE, dekodowanie części tekstowych, HTML na tekst."""

from __future__ import annotations

import base64
import binascii
import quopri
import re
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.policy import default as polityka
from html.parser import HTMLParser
from urllib.parse import unquote


@dataclass
class Czesc:
    """Jedna część wiadomości, bez treści."""

    numer: str  # numer części dla BODY[...], np. "1", "1.2"
    typ: str  # np. "text/plain"
    parametry: dict[str, str]
    kodowanie: str  # np. "base64"
    rozmiar: int
    zalacznik: bool
    nazwa: str | None


def _s(wartosc) -> str:
    if wartosc is None:
        return ""
    if isinstance(wartosc, bytes):
        return wartosc.decode("utf-8", "replace")
    return str(wartosc)


def _slownik(pary) -> dict[str, str]:
    if not isinstance(pary, (tuple, list)):
        return {}
    wynik = {}
    for i in range(0, len(pary) - 1, 2):
        wynik[_s(pary[i]).lower()] = _s(pary[i + 1])
    return wynik


def _dekoduj_nazwe(parametry: dict[str, str]) -> str | None:
    for klucz in ("filename*", "name*"):
        if klucz in parametry:
            # RFC 2231: zestaw'język'wartość-z-kodowaniem-procentowym
            czesci_nazwy = parametry[klucz].split("'", 2)
            if len(czesci_nazwy) != 3:
                return unquote(parametry[klucz])
            zestaw, _, wartosc = czesci_nazwy
            try:
                return unquote(wartosc, encoding=zestaw or "utf-8", errors="replace")
            except LookupError:
                return unquote(wartosc, errors="replace")
    for klucz in ("filename", "name"):
        if klucz in parametry:
            return dekoduj_naglowek(parametry[klucz])
    return None


def dekoduj_naglowek(wartosc: str) -> str:
    """Nagłówek kodowany według RFC 2047 na zwykły tekst."""
    try:
        return str(make_header(decode_header(wartosc)))
    except Exception:
        return wartosc


def czesci(struktura, numer: str = "") -> list[Czesc]:
    """Płaska lista części liści z BODYSTRUCTURE (w postaci `BodyData` z imapclient).

    Części `message/rfc822` (załączone maile) traktujemy jak załączniki i nie schodzimy w głąb.
    """
    if isinstance(struktura[0], list):  # multipart
        wynik = []
        for i, podczesc in enumerate(struktura[0], start=1):
            wynik.extend(czesci(podczesc, f"{numer}.{i}" if numer else str(i)))
        return wynik

    typ = f"{_s(struktura[0])}/{_s(struktura[1])}".lower()
    parametry = _slownik(struktura[2])
    kodowanie = _s(struktura[5]).lower()
    rozmiar = struktura[6] if isinstance(struktura[6], int) else 0
    # Pola rozszerzeń zaczynają się po polach podstawowych, których liczba zależy od typu.
    if typ.startswith("text/"):
        poczatek_rozszerzen = 8
    elif typ == "message/rfc822":
        poczatek_rozszerzen = 10
    else:
        poczatek_rozszerzen = 7
    dyspozycja, parametry_dyspozycji = "", {}
    if len(struktura) > poczatek_rozszerzen + 1 and isinstance(struktura[poczatek_rozszerzen + 1], (tuple, list)):
        d = struktura[poczatek_rozszerzen + 1]
        dyspozycja = _s(d[0]).lower()
        parametry_dyspozycji = _slownik(d[1]) if len(d) > 1 else {}
    nazwa = _dekoduj_nazwe(parametry_dyspozycji) or _dekoduj_nazwe(parametry)
    zalacznik = (
        dyspozycja == "attachment"
        or typ == "message/rfc822"
        or (not typ.startswith("text/") and nazwa is not None and dyspozycja != "inline")
    )
    return [Czesc(numer or "1", typ, parametry, kodowanie, rozmiar, zalacznik, nazwa)]


def czesc_tekstowa(lista: list[Czesc]) -> Czesc | None:
    """Pierwsza część `text/plain`, a gdy jej brak, pierwsza `text/html`. Pomija załączniki."""
    for typ in ("text/plain", "text/html"):
        for c in lista:
            if c.typ == typ and not c.zalacznik:
                return c
    return None


def zalaczniki(lista: list[Czesc]) -> list[dict]:
    return [{"nazwa": c.nazwa or "(bez nazwy)", "typ": c.typ, "rozmiar": c.rozmiar} for c in lista if c.zalacznik]


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.IGNORECASE)


def dekoduj_czesc(surowe: bytes, czesc: Czesc) -> str:
    """Zakodowana część (także początek części, pobrany częściowo) na tekst.

    HTML jest zamieniany na tekst.
    """
    if czesc.kodowanie == "base64":
        dane = re.sub(rb"[^A-Za-z0-9+/=]", b"", surowe)
        dane = dane[: len(dane) - len(dane) % 4]
        try:
            dane = base64.b64decode(dane)
        except (binascii.Error, ValueError):
            dane = b""
    elif czesc.kodowanie == "quoted-printable":
        dane = quopri.decodestring(surowe)
    else:
        dane = surowe

    zestaw = czesc.parametry.get("charset")
    if not zestaw and czesc.typ == "text/html":
        m = _META_CHARSET.search(dane[:4096])
        if m:
            zestaw = m.group(1).decode("ascii")
    try:
        tekst = dane.decode(zestaw or "utf-8", "replace")
    except LookupError:
        tekst = dane.decode("utf-8", "replace")

    if czesc.typ == "text/html":
        tekst = html_na_tekst(tekst)
    return tekst


class _HtmlNaTekst(HTMLParser):
    BLOKOWE = {
        "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "table", "section", "article", "header", "footer", "ul", "ol", "blockquote", "hr",
    }
    POMIJANE = {"script", "style", "head", "title", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.wynik: list[str] = []
        self._pomijaj = 0
        self._href: list[str | None] = []
        self._tekst_linku: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.POMIJANE:
            self._pomijaj += 1
        elif tag in self.BLOKOWE:
            self.wynik.append("\n")
            if tag == "li":
                self.wynik.append("- ")
        elif tag in ("td", "th"):
            self.wynik.append(" ")
        elif tag == "a":
            self._href.append(dict(attrs).get("href"))
            self._tekst_linku = []

    def handle_endtag(self, tag):
        if tag in self.POMIJANE:
            self._pomijaj = max(0, self._pomijaj - 1)
        elif tag in self.BLOKOWE:
            self.wynik.append("\n")
        elif tag == "a" and self._href:
            href = self._href.pop()
            tekst = "".join(self._tekst_linku).strip()
            if href and href.startswith(("http://", "https://")) and href != tekst:
                self.wynik.append(f" ({href})")

    def handle_data(self, data):
        if self._pomijaj:
            return
        self.wynik.append(data)
        if self._href:
            self._tekst_linku.append(data)


def html_na_tekst(html: str) -> str:
    p = _HtmlNaTekst()
    p.feed(html)
    p.close()
    return uporzadkuj_biale_znaki("".join(p.wynik))


def uporzadkuj_biale_znaki(tekst: str) -> str:
    linie = [re.sub(r"[ \t\r\f\v ​‌͏]+", " ", linia).strip() for linia in tekst.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linie)).strip()


def fragment(tekst: str, dlugosc: int = 300) -> str:
    return re.sub(r"\s+", " ", tekst).strip()[:dlugosc]


def naglowki(surowe: bytes) -> dict[str, str]:
    """Nagłówki From, To, Cc, Subject, Date, Message-ID jako zwykły tekst."""
    wiadomosc = BytesHeaderParser(policy=polityka).parsebytes(surowe)
    wynik = {}
    for klucz, nazwa in (("od", "From"), ("do", "To"), ("dw", "Cc"), ("temat", "Subject"), ("data", "Date"), ("message_id", "Message-ID")):
        try:
            wartosc = wiadomosc[nazwa]
            wynik[klucz] = str(wartosc) if wartosc is not None else ""
        except Exception:
            wynik[klucz] = ""
    return wynik
