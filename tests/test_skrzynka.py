"""Klasa Gmail na udawanym kliencie IMAP: nieaktualne UID w pamięci podręcznej."""

from __future__ import annotations

from bramka.skrzynka import Gmail


class Klient:
    """Folder „Wszystkie”: {uid: (msgid, thrid, etykiety)}. Tylko to, czego używają testowane metody."""

    def __init__(self):
        self.maile: dict[int, tuple[int, int, tuple]] = {}

    def search(self, kryteria):
        pole, wartosc = kryteria
        indeks = {"X-GM-MSGID": 0, "X-GM-THRID": 1}[pole]
        return [uid for uid, m in self.maile.items() if m[indeks] == wartosc]

    def fetch(self, uidy, pola):
        return {
            uid: {b"X-GM-MSGID": self.maile[uid][0], b"X-GM-THRID": self.maile[uid][1],
                  b"X-GM-LABELS": self.maile[uid][2]}
            for uid in uidy if uid in self.maile
        }


def gmail(klient):
    g = Gmail("ja@example.com", "x")
    g._klient = klient
    return g


def test_watek_maila_z_kosza():
    k = Klient()
    k.maile = {10: (1001, 77, (b"\\Inbox",)), 11: (1002, 77, ())}
    g = gmail(k)
    assert g.watek(1001) == [1001, 1002]
    del k.maile[10]  # mail przeniesiony do Kosza znika z „Wszystkich”, UID zostaje w pamięci podręcznej
    assert g.watek(1001) == []
    assert g.etykiety_maili([1001, 1002]) == {1002: set()}


def test_mail_przywrocony_z_nowym_uid():
    k = Klient()
    k.maile = {10: (1001, 77, (b"\\Inbox",))}
    g = gmail(k)
    assert g.etykiety_maili([1001]) == {1001: {"\\Inbox"}}
    k.maile = {25: (1001, 77, (b"agent/x",))}  # przywrócony z Kosza: ten sam X-GM-MSGID, nowy UID
    assert g.etykiety_maili([1001]) == {1001: {"agent/x"}}
    assert g.watek(1001) == [1001]
