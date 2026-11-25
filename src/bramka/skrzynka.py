"""Dostęp do Gmaila przez IMAP. Tylko te operacje, na które bramka pozwala: bez usuwania, kosza i wysyłki.

Identyfikator maila to X-GM-MSGID. Wszystkie operacje idą w folderze z flagą \\All („Wszystkie”),
a zmiany są robione wyłącznie etykietami (X-GM-LABELS) i flagą \\Seen.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from imapclient import IMAPClient
from imapclient.imapclient import ALL, SEEN
from imapclient.exceptions import IMAPClientAbortError
from imapclient.imap_utf7 import decode as utf7_decode

from . import tresc

POLA_NAGLOWKA = b"BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)]"
FRAGMENT_BAJTOW = 16384  # tyle początku części tekstowej pobieramy na fragment w wynikach wyszukiwania
TRESC_BAJTOW = 1024 * 1024  # górna granica pobierania części tekstowej przy czytaniu


@dataclass
class Mail:
    id: int
    watek: int
    data: str
    od: str
    do: str
    dw: str
    temat: str
    etykiety: list[str]
    przeczytany: bool
    rozmiar: int
    zalaczniki: list[dict] = field(default_factory=list)
    fragment: str = ""


@dataclass
class Tresc:
    naglowki: dict[str, str]
    tekst: str
    zalaczniki: list[dict]


class Skrzynka(Protocol):
    """Interfejs, którego używa bramka. Gmail przez IMAP albo atrapa w testach."""

    def szukaj(self, zapytanie: str, limit: int, kursor: int | None) -> tuple[list[int], int | None, int]:
        """Zwraca (id od najnowszych, kursor następnej strony albo None, liczba wszystkich wyników)."""
        ...

    def metadane(self, ids: list[int]) -> dict[int, Mail]: ...
    def tresc(self, id: int) -> Tresc | None: ...
    def watek(self, id: int) -> list[int]: ...
    def etykiety(self) -> list[str]: ...
    def utworz_etykiete(self, nazwa: str) -> None: ...
    def etykiety_maili(self, ids: list[int]) -> dict[int, set[str]]: ...
    def dodaj_etykiety(self, ids: list[int], etykiety: list[str]) -> None: ...
    def zdejmij_etykiety(self, ids: list[int], etykiety: list[str]) -> None: ...
    def przeczytane(self, ids: list[int]) -> dict[int, bool]: ...
    def ustaw_przeczytane(self, ids: list[int], przeczytane: bool) -> None: ...
    def wstaw(self, wiadomosc: bytes, message_id: str) -> int | None: ...


def _tekst(wartosc) -> str:
    if isinstance(wartosc, bytes):
        return utf7_decode(wartosc)
    return str(wartosc)


class Gmail:
    """Jedno połączenie IMAP, odnawiane po zerwaniu. Wywołania są szeregowane blokadą."""

    def __init__(self, adres: str, haslo: str, host: str = "imap.gmail.com"):
        self._adres = adres
        self._haslo = haslo
        self._host = host
        self._blokada = threading.RLock()
        self._klient: IMAPClient | None = None
        self._uid: dict[int, int] = {}  # X-GM-MSGID -> UID w folderze „Wszystkie”

    # --- połączenie ---

    def _polacz(self) -> IMAPClient:
        klient = IMAPClient(self._host, ssl=True, timeout=120)
        klient.login(self._adres, self._haslo)
        wszystkie = klient.find_special_folder(ALL)
        if not wszystkie:
            klient.logout()
            raise RuntimeError("Nie znaleziono folderu z flagą \\All")
        klient.select_folder(wszystkie)
        self._uid.clear()
        return klient

    def _wykonaj(self, dzialanie, powtorz: bool = True):
        with self._blokada:
            for proba in (1, 2):
                if self._klient is None:
                    self._klient = self._polacz()
                try:
                    return dzialanie(self._klient)
                except (IMAPClientAbortError, OSError):
                    self._klient = None
                    if not powtorz or proba == 2:
                        raise

    def zamknij(self) -> None:
        with self._blokada:
            if self._klient is not None:
                try:
                    self._klient.logout()
                except Exception:
                    pass
                self._klient = None

    # --- identyfikatory ---

    def _uidy(self, k: IMAPClient, ids: list[int]) -> dict[int, int]:
        """X-GM-MSGID -> UID. Nieznalezione id nie trafiają do wyniku."""
        wynik = {}
        for id in ids:
            if id not in self._uid:
                znalezione = k.search(["X-GM-MSGID", id])
                if not znalezione:
                    continue
                self._uid[id] = znalezione[0]
            wynik[id] = self._uid[id]
        return wynik

    def _zapamietaj(self, k: IMAPClient, uidy: list[int]) -> dict[int, int]:
        """UID -> X-GM-MSGID, przy okazji uzupełnia pamięć podręczną."""
        if not uidy:
            return {}
        odp = k.fetch(uidy, [b"X-GM-MSGID"])
        wynik = {}
        for uid, dane in odp.items():
            msgid = dane[b"X-GM-MSGID"]
            self._uid[msgid] = uid
            wynik[uid] = msgid
        return wynik

    # --- odczyt ---

    def szukaj(self, zapytanie, limit, kursor):
        def f(k: IMAPClient):
            uidy = sorted(k.gmail_search(zapytanie), reverse=True)
            wszystkich = len(uidy)
            if kursor is not None:
                uidy = [u for u in uidy if u < kursor]
            strona = uidy[:limit]
            nastepny = strona[-1] if len(uidy) > limit else None
            msgidy = self._zapamietaj(k, strona)
            return [msgidy[u] for u in strona if u in msgidy], nastepny, wszystkich

        return self._wykonaj(f)

    def metadane(self, ids):
        def f(k: IMAPClient):
            uidy = self._uidy(k, ids)
            if not uidy:
                return {}
            odp = k.fetch(
                list(uidy.values()),
                [b"X-GM-MSGID", b"X-GM-THRID", b"X-GM-LABELS", b"FLAGS", b"RFC822.SIZE",
                 b"INTERNALDATE", b"BODYSTRUCTURE", POLA_NAGLOWKA],
            )
            maile: dict[int, Mail] = {}
            do_fragmentu: dict[str, list[tuple[int, tresc.Czesc]]] = {}
            for uid, d in odp.items():
                msgid = d[b"X-GM-MSGID"]
                nagl = tresc.naglowki(_wartosc_body(d))
                lista = tresc.czesci(d[b"BODYSTRUCTURE"])
                data = d.get(b"INTERNALDATE")
                maile[msgid] = Mail(
                    id=msgid,
                    watek=d[b"X-GM-THRID"],
                    data=data.isoformat() if isinstance(data, datetime) else nagl["data"],
                    od=nagl["od"], do=nagl["do"], dw=nagl["dw"], temat=nagl["temat"],
                    etykiety=[_tekst(e) for e in d.get(b"X-GM-LABELS", ())],
                    przeczytany=SEEN in d.get(b"FLAGS", ()),
                    rozmiar=d.get(b"RFC822.SIZE", 0),
                    zalaczniki=tresc.zalaczniki(lista),
                )
                c = tresc.czesc_tekstowa(lista)
                if c:
                    do_fragmentu.setdefault(c.numer, []).append((uid, c))
            # Fragment: początek części tekstowej, jedno pobranie na każdy numer części.
            for numer, pozycje in do_fragmentu.items():
                klucz = f"BODY.PEEK[{numer}]<0.{FRAGMENT_BAJTOW}>".encode()
                odp2 = k.fetch([u for u, _ in pozycje], [klucz, b"X-GM-MSGID"])
                for uid, c in pozycje:
                    d = odp2.get(uid)
                    if d:
                        maile[d[b"X-GM-MSGID"]].fragment = tresc.fragment(tresc.dekoduj_czesc(_wartosc_body(d), c))
            return {id: maile[id] for id in ids if id in maile}

        return self._wykonaj(f)

    def tresc(self, id):
        def f(k: IMAPClient):
            uid = self._uidy(k, [id]).get(id)
            if uid is None:
                return None
            d = k.fetch([uid], [b"BODYSTRUCTURE", POLA_NAGLOWKA])[uid]
            nagl = tresc.naglowki(_wartosc_body(d))
            lista = tresc.czesci(d[b"BODYSTRUCTURE"])
            c = tresc.czesc_tekstowa(lista)
            tekst = ""
            if c:
                klucz = f"BODY.PEEK[{c.numer}]<0.{TRESC_BAJTOW}>".encode()
                d2 = k.fetch([uid], [klucz])[uid]
                tekst = tresc.dekoduj_czesc(_wartosc_body(d2), c)
                if c.typ == "text/plain":
                    tekst = tresc.uporzadkuj_biale_znaki(tekst)
            return Tresc(naglowki=nagl, tekst=tekst, zalaczniki=tresc.zalaczniki(lista))

        return self._wykonaj(f)

    def watek(self, id):
        def f(k: IMAPClient):
            uid = self._uidy(k, [id]).get(id)
            if uid is None:
                return []
            thrid = k.fetch([uid], [b"X-GM-THRID"])[uid][b"X-GM-THRID"]
            uidy = sorted(k.search(["X-GM-THRID", thrid]))
            msgidy = self._zapamietaj(k, uidy)
            return [msgidy[u] for u in uidy if u in msgidy]

        return self._wykonaj(f)

    def etykiety(self):
        def f(k: IMAPClient):
            return [nazwa for flagi, _, nazwa in k.list_folders() if b"\\Noselect" not in flagi]

        return self._wykonaj(f)

    def etykiety_maili(self, ids):
        def f(k: IMAPClient):
            uidy = self._uidy(k, ids)
            if not uidy:
                return {}
            odp = k.fetch(list(uidy.values()), [b"X-GM-LABELS", b"X-GM-MSGID"])
            return {d[b"X-GM-MSGID"]: {_tekst(e) for e in d.get(b"X-GM-LABELS", ())} for d in odp.values()}

        return self._wykonaj(f)

    def przeczytane(self, ids):
        def f(k: IMAPClient):
            uidy = self._uidy(k, ids)
            if not uidy:
                return {}
            odp = k.fetch(list(uidy.values()), [b"FLAGS", b"X-GM-MSGID"])
            return {d[b"X-GM-MSGID"]: SEEN in d.get(b"FLAGS", ()) for d in odp.values()}

        return self._wykonaj(f)

    # --- zmiany (tylko odwracalne) ---

    def utworz_etykiete(self, nazwa):
        self._wykonaj(lambda k: k.create_folder(nazwa))

    def dodaj_etykiety(self, ids, etykiety):
        self._wykonaj(lambda k: k.add_gmail_labels(list(self._uidy(k, ids).values()), etykiety, silent=True))

    def zdejmij_etykiety(self, ids, etykiety):
        self._wykonaj(lambda k: k.remove_gmail_labels(list(self._uidy(k, ids).values()), etykiety, silent=True))

    def ustaw_przeczytane(self, ids, przeczytane):
        def f(k: IMAPClient):
            uidy = list(self._uidy(k, ids).values())
            if przeczytane:
                k.add_flags(uidy, [SEEN], silent=True)
            else:
                k.remove_flags(uidy, [SEEN], silent=True)

        self._wykonaj(f)

    def wstaw(self, wiadomosc, message_id):
        """APPEND do Odebranych. Bez ponawiania, żeby nie wstawić dwa razy."""
        self._wykonaj(lambda k: k.append("INBOX", wiadomosc, flags=(), msg_time=datetime.now(timezone.utc)), powtorz=False)

        def f(k: IMAPClient):
            uidy = k.gmail_search(f"rfc822msgid:{message_id.strip('<>')}")
            msgidy = self._zapamietaj(k, uidy)
            return next(iter(msgidy.values()), None)

        return self._wykonaj(f)


def _wartosc_body(dane: dict) -> bytes:
    """Wartość pierwszego klucza BODY[...] z odpowiedzi FETCH (klucz zwracany przez serwer bywa inny niż żądany)."""
    for klucz, wartosc in dane.items():
        if isinstance(klucz, bytes) and klucz.startswith(b"BODY["):
            return wartosc or b""
    return b""
