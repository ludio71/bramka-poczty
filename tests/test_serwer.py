"""Serwer MCP: lista narzędzi i token."""

from __future__ import annotations

import anyio
import pytest
from atrapa import Atrapa

from bramka.dziennik import Dziennik
from bramka.rdzen import Bramka
from bramka.serwer import WymagajTokenu, zbuduj_mcp


def test_narzedzia(tmp_path):
    mcp = zbuduj_mcp(Bramka(Atrapa(), Dziennik(str(tmp_path / "d.sqlite")), "ja@example.com"))
    nazwy = {t.name for t in anyio.run(mcp.list_tools)}
    assert nazwy == {"szukaj", "czytaj", "watek", "etykiety", "etykietuj", "oznacz_przeczytane", "wstaw_podsumowanie"}


async def _zadanie(app, naglowki):
    wyslane = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(komunikat):
        wyslane.append(komunikat)

    await app({"type": "http", "method": "POST", "path": "/mcp", "headers": naglowki}, receive, send)
    return wyslane


@pytest.mark.parametrize("naglowki", [[], [(b"authorization", b"Bearer zly")], [(b"authorization", b"tajny")]])
def test_bez_tokenu_401(naglowki):
    wywolana = []

    async def aplikacja(scope, receive, send):
        wywolana.append(scope)

    wyslane = anyio.run(_zadanie, WymagajTokenu(aplikacja, "tajny"), naglowki)
    assert wyslane[0]["status"] == 401 and not wywolana


def test_z_tokenem_przechodzi():
    wywolana = []

    async def aplikacja(scope, receive, send):
        wywolana.append(scope)

    anyio.run(_zadanie, WymagajTokenu(aplikacja, "tajny"), [(b"authorization", b"Bearer tajny")])
    assert wywolana
