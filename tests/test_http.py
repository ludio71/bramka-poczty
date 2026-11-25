"""Cała droga przez HTTP: klient MCP z SDK, token, nagłówek X-Przebieg, bramka na atrapie skrzynki."""

from __future__ import annotations

import json
import socket
import threading
import time

import anyio
import httpx2
import pytest
import uvicorn
from atrapa import Atrapa
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from bramka.dziennik import Dziennik
from bramka.rdzen import Bramka
from bramka.serwer import zbuduj_aplikacje

TOKEN = "testowy-token"


@pytest.fixture
def serwer(tmp_path):
    atrapa = Atrapa()
    atrapa.dodaj_mail(1849325723859623476, temat="Duży")
    atrapa.dodaj_mail(101, temat="Mały")
    bramka = Bramka(atrapa, Dziennik(str(tmp_path / "d.sqlite")), "ja@example.com")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(zbuduj_aplikacje(bramka, TOKEN), host="127.0.0.1", port=port, log_level="warning"))
    watek = threading.Thread(target=srv.run, daemon=True)
    watek.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", bramka
    srv.should_exit = True
    watek.join(5)


async def _sesja(url, naglowki, dzialanie):
    async with httpx2.AsyncClient(headers=naglowki) as http:
        async with streamable_http_client(url, http_client=http) as (odczyt, zapis, *_):
            async with ClientSession(odczyt, zapis) as sesja:
                await sesja.initialize()
                return await dzialanie(sesja)


def _json(wynik):
    return json.loads(wynik.content[0].text)


def test_przebieg_przez_http(serwer):
    url, bramka = serwer
    naglowki = {"Authorization": f"Bearer {TOKEN}", "X-Przebieg": "test-1"}

    async def dzialanie(sesja):
        znalezione = _json(await sesja.call_tool("szukaj", {"zapytanie": "in:inbox"}))
        duze = znalezione["maile"][0]["id"]
        archiwizacja = _json(await sesja.call_tool("etykietuj", {"ids": [duze], "usun": ["\\Inbox"]}))
        kosz = await sesja.call_tool("etykietuj", {"ids": [duze], "dodaj": ["\\Trash"]})
        return duze, archiwizacja, kosz

    duze, archiwizacja, kosz = anyio.run(_sesja, url, naglowki, dzialanie)
    assert duze == "1849325723859623476"
    assert archiwizacja["wynik"][duze]["zdjete"] == ["\\Inbox"]
    assert kosz.is_error and "Odmowa" in kosz.content[0].text
    assert bramka.zarchiwizowane("test-1") == [1849325723859623476]


def test_bez_naglowka_przebiegu(serwer):
    url, _ = serwer

    async def dzialanie(sesja):
        return await sesja.call_tool("etykiety", {})

    wynik = anyio.run(_sesja, url, {"Authorization": f"Bearer {TOKEN}"}, dzialanie)
    assert wynik.is_error and "X-Przebieg" in wynik.content[0].text


def test_bez_tokenu(serwer):
    url, _ = serwer
    with pytest.raises(Exception):
        anyio.run(_sesja, url, {"X-Przebieg": "x"}, lambda s: s.call_tool("etykiety", {}))
