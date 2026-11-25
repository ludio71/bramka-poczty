"""Reguły, dziennik i cofanie na atrapie skrzynki."""

from __future__ import annotations

import pytest
from atrapa import Atrapa

from bramka.dziennik import Dziennik
from bramka.rdzen import Bramka, link
from bramka.reguly import Odmowa

P = "2026-11-26T05-00"
DUZE_ID = 1849325723859623476  # rząd wielkości prawdziwych X-GM-MSGID, powyżej 2^53


@pytest.fixture
def b(tmp_path):
    a = Atrapa()
    for i in (101, 102, 103):
        a.dodaj_mail(i, temat=f"Mail {i}")
    a.dodaj_mail(DUZE_ID, temat="Duży")
    return Bramka(a, Dziennik(str(tmp_path / "d.sqlite")), "ja@example.com")


def odmowy(b):
    return [p for p in b.dziennik.przebiegi() if p["odmow"]]


def test_przebieg_wymagany(b):
    with pytest.raises(Odmowa, match="przebiegu"):
        b.szukaj("", "in:inbox")
    with pytest.raises(Odmowa):
        b.szukaj("zly przebieg ze spacja", "in:inbox")


def test_szukaj_strony_i_id_jako_tekst(b):
    w = b.szukaj(P, "in:inbox", limit=2)
    assert [m["id"] for m in w["maile"]] == [str(DUZE_ID), "103"]
    assert w["wszystkich"] == 4
    w2 = b.szukaj(P, "in:inbox", limit=2, kursor=w["kursor"])
    assert [m["id"] for m in w2["maile"]] == ["102", "101"]
    assert w2["kursor"] is None


def test_archiwizacja_i_duze_id_jako_tekst(b):
    w = b.etykietuj(P, [str(DUZE_ID), "101"], usun=["\\Inbox"])
    assert w["wynik"][str(DUZE_ID)] == {"dodane": [], "zdjete": ["\\Inbox"]}
    assert "\\Inbox" not in b.skrzynka.maile[DUZE_ID]["etykiety"]


@pytest.mark.parametrize("etykieta", ["\\Trash", "\\Spam", "\\Sent", "\\Draft", "[Gmail]/Kosz", "do-paperless", "W-Paperless", "paperless/x"])
def test_zabronione_etykiety(b, etykieta):
    with pytest.raises(Odmowa):
        b.etykietuj(P, ["101"], dodaj=[etykieta])
    with pytest.raises(Odmowa):
        b.etykietuj(P, ["101"], usun=[etykieta])
    assert b.skrzynka.maile[101]["etykiety"] == {"\\Inbox"}
    assert b.dziennik.przebiegi()[0]["odmow"] == 2


def test_nowe_etykiety_tylko_agent(b):
    with pytest.raises(Odmowa, match="agent/"):
        b.etykietuj(P, ["101"], dodaj=["Nowa"])
    b.etykietuj(P, ["101"], dodaj=["agent/przejrzane"])
    assert "agent/przejrzane" in b.skrzynka.etykiety_uzytkownika
    assert "agent/przejrzane" in b.skrzynka.maile[101]["etykiety"]


def test_istniejaca_etykieta_wlasciciela_i_systemowe(b):
    b.etykietuj(P, ["101"], dodaj=["zakupy/zamówienia", "\\starred", "\\Important"])
    assert {"Zakupy/zamówienia", "\\Starred", "\\Important"} <= b.skrzynka.maile[101]["etykiety"]


def test_limit_ids(b):
    with pytest.raises(Odmowa, match="100"):
        b.etykietuj(P, [str(i) for i in range(101)], dodaj=["agent/x"])


def test_nieznany_mail(b):
    w = b.etykietuj(P, ["101", "999"], usun=["\\Inbox"])
    assert w["wynik"]["999"] == "nie znaleziono"


def test_cofniecie_przebiegu(b):
    b.skrzynka.maile[102]["etykiety"].add("Praca")
    b.etykietuj(P, ["101", "102"], dodaj=["agent/przejrzane", "Praca"], usun=["\\Inbox"])
    b.oznacz_przeczytane(P, ["101", "102"])
    b.etykietuj("inny", ["103"], usun=["\\Inbox"])

    b.cofnij(P)
    assert b.skrzynka.maile[101]["etykiety"] == {"\\Inbox"}
    assert b.skrzynka.maile[102]["etykiety"] == {"\\Inbox", "Praca"}  # Praca była wcześniej, zostaje
    assert not b.skrzynka.maile[101]["przeczytany"]
    assert "\\Inbox" not in b.skrzynka.maile[103]["etykiety"]  # inny przebieg nietknięty


def test_cofniecie_kolejnosc(b):
    b.etykietuj(P, ["101"], usun=["\\Inbox"])
    b.etykietuj(P, ["101"], dodaj=["\\Inbox"])
    b.etykietuj(P, ["101"], usun=["\\Inbox"])
    b.cofnij(P)
    assert "\\Inbox" in b.skrzynka.maile[101]["etykiety"]


def test_podsumowanie_z_lista_zarchiwizowanych(b):
    b.etykietuj(P, ["101", "102"], usun=["\\Inbox"])
    b.etykietuj(P, ["102"], dodaj=["\\Inbox"])  # przywrócony, nie trafia na listę
    w = b.wstaw_podsumowanie(P, "Podsumowanie poczty", "## Najważniejsze\n\nNic pilnego.")
    assert w["zarchiwizowanych"] == 1
    tekst = b.skrzynka.wstawione[0].decode()
    assert "Mail 101" in tekst and "Mail 102" not in tekst
    assert link(101) in tekst
    assert "To: ja@example.com" in tekst


def test_limit_podsumowan(b):
    for _ in range(3):
        b.wstaw_podsumowanie(P, "T", "x")
    with pytest.raises(Odmowa, match="3"):
        b.wstaw_podsumowanie(P, "T", "x")
    b.wstaw_podsumowanie("inny", "T", "x")


def test_podsumowanie_za_dlugie(b):
    with pytest.raises(Odmowa):
        b.wstaw_podsumowanie(P, "T", "x" * 200_001)


def test_temat_bez_nowych_linii(b):
    b.wstaw_podsumowanie(P, "T\r\nBcc: obcy@example.com", "x")
    tekst = b.skrzynka.wstawione[0].decode()
    assert "\nBcc:" not in tekst


def test_dziennik_zapisuje_odczyty(b):
    b.szukaj(P, "in:inbox")
    b.czytaj(P, "101")
    p = b.dziennik.przebiegi()[0]
    assert p["przebieg"] == P and p["operacji"] == 2
