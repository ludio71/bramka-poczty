"""Struktura MIME i dekodowanie treści na odpowiedziach w formacie IMAP (parser imapclient)."""

from __future__ import annotations

import base64

from imapclient.response_parser import parse_fetch_response

from bramka import tresc


def struktura(bodystructure: bytes):
    odp = parse_fetch_response([b"1 (UID 7 BODYSTRUCTURE " + bodystructure + b")"])
    return odp[7][b"BODYSTRUCTURE"]


MIXED = (
    b'((("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "QUOTED-PRINTABLE" 120 4 NIL NIL NIL NIL)'
    b'("TEXT" "HTML" ("CHARSET" "UTF-8") NIL NIL "BASE64" 900 12 NIL NIL NIL NIL) "ALTERNATIVE" ("BOUNDARY" "a") NIL NIL NIL)'
    b'("APPLICATION" "PDF" ("NAME" "=?UTF-8?Q?faktura_=C5=BC.pdf?=") NIL NIL "BASE64" 50000 NIL ("ATTACHMENT" ("FILENAME" "=?UTF-8?Q?faktura_=C5=BC.pdf?=")) NIL NIL)'
    b' "MIXED" ("BOUNDARY" "m") NIL NIL NIL)'
)


def test_czesci_multipart():
    lista = tresc.czesci(struktura(MIXED))
    assert [(c.numer, c.typ, c.zalacznik) for c in lista] == [
        ("1.1", "text/plain", False),
        ("1.2", "text/html", False),
        ("2", "application/pdf", True),
    ]
    assert tresc.czesc_tekstowa(lista).numer == "1.1"
    assert tresc.zalaczniki(lista) == [{"nazwa": "faktura ż.pdf", "typ": "application/pdf", "rozmiar": 50000}]


def test_czesc_pojedyncza_html():
    s = struktura(b'("TEXT" "HTML" NIL NIL NIL "8BIT" 300 10 NIL NIL NIL NIL)')
    lista = tresc.czesci(s)
    assert lista[0].numer == "1" and tresc.czesc_tekstowa(lista).typ == "text/html"


def test_zalaczony_mail_i_obrazek_inline():
    s = struktura(
        b'(("TEXT" "HTML" ("CHARSET" "utf-8") NIL NIL "7BIT" 100 3 NIL NIL NIL NIL)'
        b'("IMAGE" "PNG" ("NAME" "logo.png") "<logo>" NIL "BASE64" 2000 NIL ("INLINE" ("FILENAME" "logo.png")) NIL NIL)'
        b' "RELATED" ("BOUNDARY" "r") NIL NIL NIL)'
    )
    lista = tresc.czesci(s)
    assert [c.zalacznik for c in lista] == [False, False]


def test_nazwa_rfc2231():
    s = struktura(b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 10 NIL ("ATTACHMENT" ("FILENAME*" "utf-8\'\'umowa%20%C5%BC.pdf")) NIL NIL)')
    assert tresc.czesci(s)[0].nazwa == "umowa ż.pdf"


def test_base64_uciety_w_polowie():
    czesc = tresc.Czesc("1", "text/plain", {"charset": "utf-8"}, "base64", 0, False, None)
    zakodowane = base64.encodebytes("Zażółć gęślą jaźń. ".encode() * 20)
    tekst = tresc.dekoduj_czesc(zakodowane[:101], czesc)
    assert tekst.startswith("Zażółć gęślą jaźń.")


def test_quoted_printable_iso():
    czesc = tresc.Czesc("1", "text/plain", {"charset": "iso-8859-2"}, "quoted-printable", 0, False, None)
    assert tresc.dekoduj_czesc(b"Zam=F3wienie wys=B3ane", czesc) == "Zamówienie wysłane"


def test_html_bez_charset_z_meta():
    czesc = tresc.Czesc("1", "text/html", {}, "8bit", 0, False, None)
    html = '<html><head><meta charset="windows-1250"><style>p{}</style></head><body><p>Paczka</p><p>doręczona <a href="https://x.pl/t">śledź</a></p></body></html>'
    assert tresc.dekoduj_czesc(html.encode("windows-1250"), czesc) == "Paczka\n\ndoręczona śledź (https://x.pl/t)"


def test_nieznany_zestaw_znakow():
    czesc = tresc.Czesc("1", "text/plain", {"charset": "x-nieznany"}, "7bit", 0, False, None)
    assert tresc.dekoduj_czesc(b"abc", czesc) == "abc"


def test_html_na_tekst_listy_i_skrypty():
    html = "<script>alert(1)</script><ul><li>jeden</li><li>dwa</li></ul>&nbsp;&amp;"
    assert tresc.html_na_tekst(html) == "- jeden\n\n- dwa\n\n&"


def test_naglowki_rfc2047():
    surowe = b"From: =?UTF-8?Q?Pocz=C4=85tek?= <a@b.pl>\r\nSubject: =?ISO-8859-2?Q?Przesy=B3ka?=\r\n\r\n"
    n = tresc.naglowki(surowe)
    assert n["od"] == "Początek <a@b.pl>" and n["temat"] == "Przesyłka"


def test_fragment():
    assert tresc.fragment("a\n\n  b " + "c" * 400) == ("a b " + "c" * 296)
