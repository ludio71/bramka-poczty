"""Polecenie `bramka`: serwer, lista przebiegów, cofnięcie przebiegu.

Konfiguracja ze zmiennych środowiskowych (sekrety tylko w konfiguracji aplikacji TrueNAS):
  GMAIL_ADRES            adres skrzynki, zarazem adres właściciela w podsumowaniach
  GMAIL_HASLO_APLIKACJI  osobne hasło aplikacji Google dla bramki
  BRAMKA_TOKEN           token agenta (nagłówek Authorization: Bearer)
  BRAMKA_DZIENNIK        plik SQLite dziennika (domyślnie /data/dziennik.sqlite)
  BRAMKA_PORT            port HTTP (domyślnie 8000)
"""

from __future__ import annotations

import argparse
import os
import sys


def _wymagana(nazwa: str) -> str:
    wartosc = os.environ.get(nazwa, "")
    if not wartosc:
        sys.exit(f"Brak zmiennej środowiskowej {nazwa}")
    return wartosc


def _bramka():
    from .dziennik import Dziennik
    from .rdzen import Bramka
    from .skrzynka import Gmail

    adres = _wymagana("GMAIL_ADRES")
    gmail = Gmail(adres, _wymagana("GMAIL_HASLO_APLIKACJI"))
    dziennik = Dziennik(os.environ.get("BRAMKA_DZIENNIK", "/data/dziennik.sqlite"))
    return Bramka(gmail, dziennik, adres)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bramka", description="Bramka MCP do Gmaila")
    pod = parser.add_subparsers(dest="polecenie", required=True)
    pod.add_parser("serwer", help="uruchamia serwer MCP")
    pod.add_parser("przebiegi", help="ostatnie przebiegi z dziennika")
    c = pod.add_parser("cofnij", help="odwraca zmiany etykiet i flag z przebiegu")
    c.add_argument("przebieg")
    args = parser.parse_args(argv)

    if args.polecenie == "serwer":
        import uvicorn

        from .serwer import zbuduj_aplikacje

        token = _wymagana("BRAMKA_TOKEN")
        uvicorn.run(zbuduj_aplikacje(_bramka(), token), host="0.0.0.0", port=int(os.environ.get("BRAMKA_PORT", "8000")))
    elif args.polecenie == "przebiegi":
        from .dziennik import Dziennik

        dziennik = Dziennik(os.environ.get("BRAMKA_DZIENNIK", "/data/dziennik.sqlite"))
        for p in dziennik.przebiegi():
            print(f"{p['przebieg']}  {p['od']} – {p['do']}  operacji: {p['operacji']}, zmian: {p['zmian']}, odmów: {p['odmow']}")
    elif args.polecenie == "cofnij":
        wynik = _bramka().cofnij(args.przebieg)
        print(f"Cofnięte operacje: {wynik['cofniete_operacje']} (w dzienniku jako {wynik['przebieg_cofniecia']})")


if __name__ == "__main__":
    main()
