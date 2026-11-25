"""Serwer MCP bramki (Streamable HTTP na /mcp) z uwierzytelnianiem tokenem."""

from __future__ import annotations

import hmac
import json
from functools import partial

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from .rdzen import Bramka
from .reguly import Odmowa

INSTRUKCJE = """Bramka do skrzynki Gmail właściciela. Wolno: szukać, czytać, nadawać i zdejmować etykiety
(archiwizacja to zdjęcie etykiety \\Inbox), oznaczać jako przeczytane i wstawić podsumowanie do Odebranych.
Nie da się niczego usunąć, przenieść do kosza ani wysłać. Każda operacja trafia do dziennika.
Identyfikatory maili to tekst (X-GM-MSGID)."""


def _przebieg(ctx: Context) -> str:
    naglowki = ctx.headers or {}
    return naglowki.get("x-przebieg", "")


async def _wywolaj(funkcja, *args, **kwargs):
    try:
        return await anyio.to_thread.run_sync(partial(funkcja, *args, **kwargs))
    except Odmowa as e:
        raise ToolError(f"Odmowa bramki: {e}") from None


def zbuduj_mcp(bramka: Bramka) -> MCPServer:
    mcp = MCPServer("bramka-poczty", instructions=INSTRUKCJE)

    @mcp.tool()
    async def szukaj(zapytanie: str, ctx: Context, limit: int = 50, kursor: str | None = None) -> dict:
        """Szuka maili składnią wyszukiwarki Gmaila (np. `in:inbox newer_than:2d`, `from:linkedin.com`, `-label:agent/przejrzane`).

        Zwraca maile od najnowszych (najwyżej `limit`, maks. 100): id, wątek, data, nadawca, adresaci, temat,
        fragment treści (do 300 znaków), etykiety, czy przeczytany, rozmiar, lista załączników.
        `kursor` z wyniku podaj w następnym wywołaniu, żeby dostać kolejną stronę. Kosz i spam nie są przeszukiwane.
        """
        return await _wywolaj(bramka.szukaj, _przebieg(ctx), zapytanie, limit, kursor)

    @mcp.tool()
    async def czytaj(id: str, ctx: Context, max_znakow: int = 8000) -> dict:
        """Treść maila jako tekst (HTML zamieniony na tekst), przycięta do `max_znakow` (maks. 30000).

        Zwraca też nagłówki, listę załączników i link do maila. Załączników bramka nie pobiera.
        Mail nie zostaje oznaczony jako przeczytany.
        """
        return await _wywolaj(bramka.czytaj, _przebieg(ctx), id, max_znakow)

    @mcp.tool()
    async def watek(id: str, ctx: Context) -> dict:
        """Metadane wszystkich maili z wątku danego maila (jak w `szukaj`). Wolne, używaj tylko w razie potrzeby."""
        return await _wywolaj(bramka.watek, _przebieg(ctx), id)

    @mcp.tool()
    async def etykiety(ctx: Context) -> dict:
        """Lista etykiet użytkownika i dozwolonych etykiet systemowych."""
        return await _wywolaj(bramka.etykiety, _przebieg(ctx))

    @mcp.tool()
    async def etykietuj(ids: list[str], ctx: Context, dodaj: list[str] | None = None, usun: list[str] | None = None) -> dict:
        """Nadaje (`dodaj`) i zdejmuje (`usun`) etykiety najwyżej 100 mailom naraz.

        Archiwizacja: `usun: ["\\\\Inbox"]`. Dozwolone etykiety systemowe: \\Inbox, \\Important, \\Starred.
        Nowe etykiety wolno zakładać tylko z przedrostkiem `agent/`. Etykiet Paperless (`do-paperless`,
        `w-paperless`, `paperless`) bramka nie rusza. Zwraca, co faktycznie zmieniono przy każdym mailu.
        """
        return await _wywolaj(bramka.etykietuj, _przebieg(ctx), ids, dodaj, usun)

    @mcp.tool()
    async def oznacz_przeczytane(ids: list[str], ctx: Context, przeczytane: bool = True) -> dict:
        """Oznacza najwyżej 100 maili jako przeczytane (albo nieprzeczytane, gdy `przeczytane` = false)."""
        return await _wywolaj(bramka.oznacz_przeczytane, _przebieg(ctx), ids, przeczytane)

    @mcp.tool()
    async def wstaw_podsumowanie(temat: str, tresc: str, ctx: Context) -> dict:
        """Wstawia do Odebranych jedno podsumowanie dla właściciela (bez wysyłania). Najwyżej 3 na przebieg.

        `tresc` w Markdown, maks. 200 kB. Pod treścią bramka sama dopisze listę maili zarchiwizowanych
        w tym przebiegu (nadawca, temat, link), więc nie musisz jej powtarzać. Wstawiaj na końcu przebiegu.
        """
        return await _wywolaj(bramka.wstaw_podsumowanie, _przebieg(ctx), temat, tresc)

    return mcp


class WymagajTokenu:
    """Middleware ASGI: każde żądanie HTTP musi mieć nagłówek `Authorization: Bearer <token>`."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError("pusty token")
        self.app = app
        self._oczekiwany = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            podany = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(podany, self._oczekiwany):
                tresc = json.dumps({"error": "unauthorized"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(tresc)).encode())]})
                await send({"type": "http.response.body", "body": tresc})
                return
        await self.app(scope, receive, send)


def zbuduj_aplikacje(bramka: Bramka, token: str):
    """Aplikacja ASGI. Ochrona przed DNS rebinding SDK jest wyłączona (host 0.0.0.0), bo chroni token."""
    app = zbuduj_mcp(bramka).streamable_http_app(host="0.0.0.0")
    return WymagajTokenu(app, token)
