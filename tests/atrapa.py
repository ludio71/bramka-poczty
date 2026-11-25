"""Atrapa skrzynki w pamięci z tym samym interfejsem co `Gmail`."""

from __future__ import annotations

from email import message_from_bytes

from bramka.skrzynka import Mail, Tresc


class Atrapa:
    def __init__(self):
        self.maile: dict[int, dict] = {}
        self.etykiety_uzytkownika = ["Zakupy/zamówienia", "do-paperless", "w-paperless", "paperless", "Praca"]
        self.wstawione: list[bytes] = []

    def dodaj_mail(self, id: int, etykiety=("\\Inbox",), przeczytany=False, od="nadawca@example.com", temat="Temat", tekst="Treść"):
        self.maile[id] = {"etykiety": set(etykiety), "przeczytany": przeczytany, "od": od, "temat": temat, "tekst": tekst, "watek": id}

    def szukaj(self, zapytanie, limit, kursor):
        ids = sorted(self.maile, reverse=True)
        if "in:inbox" in zapytanie:
            ids = [i for i in ids if "\\Inbox" in self.maile[i]["etykiety"]]
        wszystkich = len(ids)
        if kursor is not None:
            ids = [i for i in ids if i < kursor]
        strona = ids[:limit]
        return strona, (strona[-1] if len(ids) > limit else None), wszystkich

    def metadane(self, ids):
        return {
            i: Mail(id=i, watek=self.maile[i]["watek"], data="2026-11-25T06:00:00+00:00", od=self.maile[i]["od"], do="ja@example.com",
                    dw="", temat=self.maile[i]["temat"], etykiety=sorted(self.maile[i]["etykiety"]),
                    przeczytany=self.maile[i]["przeczytany"], rozmiar=100, fragment=self.maile[i]["tekst"][:300])
            for i in ids if i in self.maile
        }

    def tresc(self, id):
        if id not in self.maile:
            return None
        m = self.maile[id]
        return Tresc(naglowki={"od": m["od"], "temat": m["temat"]}, tekst=m["tekst"], zalaczniki=[])

    def watek(self, id):
        if id not in self.maile:
            return []
        return sorted(i for i, m in self.maile.items() if m["watek"] == self.maile[id]["watek"])

    def etykiety(self):
        return ["INBOX", "[Gmail]/Wszystkie", "[Gmail]/Kosz", *self.etykiety_uzytkownika]

    def utworz_etykiete(self, nazwa):
        self.etykiety_uzytkownika.append(nazwa)

    def etykiety_maili(self, ids):
        return {i: set(self.maile[i]["etykiety"]) for i in ids if i in self.maile}

    def dodaj_etykiety(self, ids, etykiety):
        for i in ids:
            self.maile[i]["etykiety"] |= set(etykiety)

    def zdejmij_etykiety(self, ids, etykiety):
        for i in ids:
            self.maile[i]["etykiety"] -= set(etykiety)

    def przeczytane(self, ids):
        return {i: self.maile[i]["przeczytany"] for i in ids if i in self.maile}

    def ustaw_przeczytane(self, ids, przeczytane):
        for i in ids:
            self.maile[i]["przeczytany"] = przeczytane

    def wstaw(self, wiadomosc, message_id):
        self.wstawione.append(wiadomosc)
        id = max(self.maile, default=0) + 1
        m = message_from_bytes(wiadomosc)
        self.dodaj_mail(id, etykiety=("\\Inbox",), od=m["From"], temat=m["Subject"], tekst=m.get_payload(decode=True).decode())
        return id
