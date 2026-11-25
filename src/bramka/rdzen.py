"""Rdzeń bramki: narzędzia z regułami i dziennikiem, niezależne od MCP (testowane na atrapie skrzynki)."""

from __future__ import annotations

import html
import re
from dataclasses import asdict
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from markdown_it import MarkdownIt

from .dziennik import Dziennik
from .reguly import Odmowa, sprawdz_etykiete
from .skrzynka import Skrzynka

MAKS_WYNIKOW = 100
MAKS_IDS = 100
MAKS_ZNAKOW = 30000
MAKS_TRESCI_PODSUMOWANIA = 200_000  # bajtów
MAKS_PODSUMOWAN = 3
MAKS_MAILI_WATKU = 100
INBOX = "\\Inbox"
PRZEBIEG = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

# Markdown podsumowania do HTML. Surowy HTML z treści nie przechodzi (zostaje pokazany jako tekst),
# a markdown-it nie robi linków z niebezpiecznych schematów (np. javascript:).
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def link(id: int) -> str:
    # Format adresu do sprawdzenia na żywo (plan, 1.4).
    return f"https://mail.google.com/mail/u/0/#all/{id:x}"


def _mail(m) -> dict:
    """Identyfikatory jako tekst: X-GM-MSGID przekracza 2^53, a klienci w JavaScripcie tracą wtedy cyfry."""
    d = asdict(m)
    d["id"], d["watek"] = str(m.id), str(m.watek)
    return d


def _ids(ids) -> list[int]:
    if not isinstance(ids, list) or not ids:
        raise Odmowa("ids musi być niepustą listą")
    if len(ids) > MAKS_IDS:
        raise Odmowa(f"najwyżej {MAKS_IDS} maili naraz")
    wynik = []
    for i in ids:
        try:
            wynik.append(int(i))
        except (TypeError, ValueError):
            raise Odmowa(f"niepoprawne id: {i!r}") from None
    return list(dict.fromkeys(wynik))


class Bramka:
    def __init__(self, skrzynka: Skrzynka, dziennik: Dziennik, adres: str):
        self.skrzynka = skrzynka
        self.dziennik = dziennik
        self.adres = adres

    def _wykonaj(self, przebieg: str, narzedzie: str, parametry: dict, dzialanie, mail_id: int | None = None):
        """Sprawdza przebieg, wykonuje działanie i zapisuje odmowę albo błąd do dziennika."""
        if not isinstance(przebieg, str) or not PRZEBIEG.match(przebieg):
            raise Odmowa("brak albo niepoprawny identyfikator przebiegu (nagłówek X-Przebieg)")
        try:
            return dzialanie()
        except Odmowa as e:
            self.dziennik.zapisz(przebieg, narzedzie, parametry, "odmowa", mail_id, str(e))
            raise
        except Exception as e:
            self.dziennik.zapisz(przebieg, narzedzie, parametry, "blad", mail_id, f"{type(e).__name__}: {e}")
            raise

    # --- odczyt ---

    def szukaj(self, przebieg: str, zapytanie: str, limit: int = 50, kursor: str | None = None) -> dict:
        parametry = {"zapytanie": zapytanie, "limit": limit, "kursor": kursor}

        def f():
            if not isinstance(zapytanie, str) or not zapytanie.strip():
                raise Odmowa("puste zapytanie")
            n = max(1, min(int(limit), MAKS_WYNIKOW))
            try:
                k = int(kursor) if kursor else None
            except ValueError:
                raise Odmowa("niepoprawny kursor") from None
            ids, nastepny, wszystkich = self.skrzynka.szukaj(zapytanie, n, k)
            meta = self.skrzynka.metadane(ids)
            self.dziennik.zapisz(przebieg, "szukaj", {**parametry, "znalezione": len(ids), "wszystkich": wszystkich})
            return {
                "maile": [_mail(meta[i]) for i in ids if i in meta],
                "wszystkich": wszystkich,
                "kursor": str(nastepny) if nastepny is not None else None,
            }

        return self._wykonaj(przebieg, "szukaj", parametry, f)

    def czytaj(self, przebieg: str, id: int, max_znakow: int = 8000) -> dict:
        def f():
            t = self.skrzynka.tresc(int(id))
            if t is None:
                raise Odmowa(f"nie znaleziono maila {id}")
            n = max(1, min(int(max_znakow), MAKS_ZNAKOW))
            self.dziennik.zapisz(przebieg, "czytaj", {"max_znakow": n}, mail_id=int(id))
            return {
                "id": str(int(id)),
                **t.naglowki,
                "tekst": t.tekst[:n],
                "przyciety": len(t.tekst) > n,
                "dlugosc": len(t.tekst),
                "zalaczniki": t.zalaczniki,
                "link": link(int(id)),
            }

        return self._wykonaj(przebieg, "czytaj", {"max_znakow": max_znakow}, f, mail_id=_bez_bledu_int(id))

    def watek(self, przebieg: str, id: int) -> dict:
        def f():
            ids = self.skrzynka.watek(int(id))
            if not ids:
                raise Odmowa(f"nie znaleziono maila {id}")
            ids = ids[-MAKS_MAILI_WATKU:]
            meta = self.skrzynka.metadane(ids)
            self.dziennik.zapisz(przebieg, "watek", {"maili": len(ids)}, mail_id=int(id))
            return {"maile": [_mail(meta[i]) for i in ids if i in meta]}

        return self._wykonaj(przebieg, "watek", {}, f, mail_id=_bez_bledu_int(id))

    def etykiety(self, przebieg: str) -> dict:
        def f():
            lista = self.skrzynka.etykiety()
            self.dziennik.zapisz(przebieg, "etykiety", {"liczba": len(lista)})
            uzytkownika = [e for e in lista if not e.upper().startswith(("[GMAIL]", "[GOOGLE MAIL]")) and e.upper() != "INBOX"]
            return {"etykiety": sorted(uzytkownika), "systemowe_dozwolone": ["\\Inbox", "\\Important", "\\Starred"]}

        return self._wykonaj(przebieg, "etykiety", {}, f)

    # --- zmiany ---

    def etykietuj(self, przebieg: str, ids: list, dodaj: list | None = None, usun: list | None = None) -> dict:
        dodaj, usun = list(dodaj or []), list(usun or [])
        parametry = {"ids": ids, "dodaj": dodaj, "usun": usun}

        def f():
            lista = _ids(ids)
            if not dodaj and not usun:
                raise Odmowa("nic do zrobienia: puste dodaj i usun")
            istniejace = self.skrzynka.etykiety()
            nowe = []
            kanon_dodaj, kanon_usun = [], []
            for nazwa in dodaj:
                k, trzeba_utworzyc = sprawdz_etykiete(nazwa, istniejace)
                kanon_dodaj.append(k)
                if trzeba_utworzyc:
                    nowe.append(k)
            for nazwa in usun:
                k, trzeba_utworzyc = sprawdz_etykiete(nazwa, istniejace)
                if not trzeba_utworzyc:
                    kanon_usun.append(k)
            if set(kanon_dodaj) & set(kanon_usun):
                raise Odmowa("ta sama etykieta w dodaj i usun")

            for k in dict.fromkeys(nowe):
                self.skrzynka.utworz_etykiete(k)
                self.dziennik.zapisz(przebieg, "utworz_etykiete", {"nazwa": k})

            przed = self.skrzynka.etykiety_maili(lista)
            znalezione = [i for i in lista if i in przed]
            if kanon_dodaj and znalezione:
                self.skrzynka.dodaj_etykiety(znalezione, kanon_dodaj)
            if kanon_usun and znalezione:
                self.skrzynka.zdejmij_etykiety(znalezione, kanon_usun)

            wynik = {}
            for i in lista:
                if i not in przed:
                    wynik[str(i)] = "nie znaleziono"
                    self.dziennik.zapisz(przebieg, "etykietuj", {"dodaj": kanon_dodaj, "usun": kanon_usun}, "blad", i, "nie znaleziono")
                    continue
                zmiana = {
                    "dodane": [e for e in kanon_dodaj if e not in przed[i]],
                    "zdjete": [e for e in kanon_usun if e in przed[i]],
                }
                wynik[str(i)] = zmiana
                self.dziennik.zapisz(przebieg, "etykietuj", zmiana, mail_id=i)
            return {"wynik": wynik}

        return self._wykonaj(przebieg, "etykietuj", parametry, f)

    def oznacz_przeczytane(self, przebieg: str, ids: list, przeczytane: bool = True) -> dict:
        parametry = {"ids": ids, "przeczytane": przeczytane}

        def f():
            lista = _ids(ids)
            nowe = bool(przeczytane)
            przed = self.skrzynka.przeczytane(lista)
            znalezione = [i for i in lista if i in przed]
            if znalezione:
                self.skrzynka.ustaw_przeczytane(znalezione, nowe)
            wynik = {}
            for i in lista:
                if i not in przed:
                    wynik[str(i)] = "nie znaleziono"
                    self.dziennik.zapisz(przebieg, "oznacz_przeczytane", {"przeczytane": nowe}, "blad", i, "nie znaleziono")
                    continue
                wynik[str(i)] = "zmienione" if przed[i] != nowe else "bez zmian"
                if przed[i] != nowe:
                    self.dziennik.zapisz(przebieg, "oznacz_przeczytane", {"bylo": przed[i], "jest": nowe}, mail_id=i)
            return {"wynik": wynik}

        return self._wykonaj(przebieg, "oznacz_przeczytane", parametry, f)

    def zarchiwizowane(self, przebieg: str) -> list[int]:
        """Maile, którym ten przebieg zdjął etykietę Inbox i jej nie przywrócił, w kolejności archiwizacji."""
        stan: dict[int, bool] = {}
        for op in self.dziennik.operacje(przebieg, ("etykietuj",)):
            i, p = op["mail_id"], op["parametry"]
            if INBOX in p.get("zdjete", []):
                stan[i] = True
            if INBOX in p.get("dodane", []):
                stan.pop(i, None)
        return [i for i, z in stan.items() if z]

    def wstaw_podsumowanie(self, przebieg: str, temat: str, tresc: str) -> dict:
        parametry = {"temat": temat, "dlugosc": len(tresc) if isinstance(tresc, str) else None}

        def f():
            if not isinstance(temat, str) or not temat.strip():
                raise Odmowa("pusty temat")
            if not isinstance(tresc, str) or not tresc.strip():
                raise Odmowa("pusta treść")
            if len(tresc.encode("utf-8")) > MAKS_TRESCI_PODSUMOWANIA:
                raise Odmowa(f"treść dłuższa niż {MAKS_TRESCI_PODSUMOWANIA} bajtów")
            if self.dziennik.licz(przebieg, "wstaw_podsumowanie") >= MAKS_PODSUMOWAN:
                raise Odmowa(f"najwyżej {MAKS_PODSUMOWAN} podsumowania na przebieg")

            ids = self.zarchiwizowane(przebieg)
            meta = {}
            for i in range(0, len(ids), MAKS_IDS):
                meta.update(self.skrzynka.metadane(ids[i:i + MAKS_IDS]))
            naglowek = f"Zarchiwizowane w tym przebiegu ({len(ids)}):"
            linie = [naglowek, ""]
            # Nadawcy i tematy pochodzą z cudzych maili: do HTML idą zescapowane, nie przez markdown,
            # żeby nie dało się nimi wstawić linku ani formatowania.
            pozycje = []
            for i in ids:
                m = meta.get(i)
                opis = f"{m.od} | {m.temat}" if m else "(nie znaleziono)"
                linie.append(f"- {opis}\n  {link(i)}")
                pozycje.append(f'<li>{html.escape(opis)}<br><a href="{link(i)}">{link(i)}</a></li>')
            linie += ["", f"Przebieg: {przebieg}"]
            strona = (
                '<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head><body>\n'
                + _MARKDOWN.render(tresc)
                + f"<hr>\n<p>{html.escape(naglowek)}</p>\n<ul>\n" + "\n".join(pozycje) + "\n</ul>\n"
                + f"<p>Przebieg: {html.escape(przebieg)}</p>\n</body></html>\n"
            )

            wiadomosc = EmailMessage()
            wiadomosc["From"] = f"Bramka poczty <{self.adres}>"
            wiadomosc["To"] = self.adres
            wiadomosc["Subject"] = " ".join(temat.split())[:200]
            wiadomosc["Date"] = format_datetime(datetime.now(timezone.utc))
            message_id = make_msgid(domain="bramka-poczty.local")
            wiadomosc["Message-ID"] = message_id
            # Dwie wersje (multipart/alternative): Gmail pokazuje HTML, zwykły tekst zostaje dla innych klientów.
            wiadomosc.set_content(tresc.rstrip() + "\n\n---\n" + "\n".join(linie) + "\n")
            wiadomosc.add_alternative(strona, subtype="html")
            id = self.skrzynka.wstaw(wiadomosc.as_bytes(), message_id)
            self.dziennik.zapisz(przebieg, "wstaw_podsumowanie", {**parametry, "zarchiwizowanych": len(ids)}, mail_id=id)
            return {"id": str(id) if id is not None else None, "zarchiwizowanych": len(ids)}

        return self._wykonaj(przebieg, "wstaw_podsumowanie", parametry, f)

    # --- dla właściciela (CLI), nie dla agenta ---

    def cofnij(self, przebieg: str) -> dict:
        """Odwraca zmiany etykiet i flag przebiegu, od ostatniej. Wstawionych podsumowań nie usuwa."""
        cel = f"cofniecie:{przebieg}"[:64]
        ops = self.dziennik.operacje(przebieg, ("etykietuj", "oznacz_przeczytane"))
        for op in reversed(ops):
            i, p = op["mail_id"], op["parametry"]
            if op["narzedzie"] == "etykietuj":
                if p.get("dodane"):
                    self.skrzynka.zdejmij_etykiety([i], p["dodane"])
                if p.get("zdjete"):
                    self.skrzynka.dodaj_etykiety([i], p["zdjete"])
                self.dziennik.zapisz(cel, "etykietuj", {"dodane": p.get("zdjete", []), "zdjete": p.get("dodane", [])}, mail_id=i)
            else:
                self.skrzynka.ustaw_przeczytane([i], p["bylo"])
                self.dziennik.zapisz(cel, "oznacz_przeczytane", {"bylo": p["jest"], "jest": p["bylo"]}, mail_id=i)
        return {"cofniete_operacje": len(ops), "przebieg_cofniecia": cel}


def _bez_bledu_int(wartosc) -> int | None:
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return None
