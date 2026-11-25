"""Reguły etykiet: które wolno nadawać i zdejmować (README, „Reguły etykiet”)."""

from __future__ import annotations

DOZWOLONE_SYSTEMOWE = {"\\inbox": "\\Inbox", "\\important": "\\Important", "\\starred": "\\Starred"}
# Etykiety, które uruchamiają import do Paperless. Agent ich nie rusza (ani podetykiet).
ZABRONIONE = ("do-paperless", "w-paperless", "paperless")
PRZEDROSTEK_AGENTA = "agent/"


class Odmowa(Exception):
    """Operacja zabroniona przez reguły bramki."""


def sprawdz_etykiete(nazwa: str, istniejace: list[str]) -> tuple[str, bool]:
    """Zwraca (nazwa kanoniczna, czy trzeba ją utworzyć). Rzuca `Odmowa`, gdy etykieta jest zabroniona."""
    if not isinstance(nazwa, str) or not nazwa.strip() or nazwa != nazwa.strip():
        raise Odmowa(f"niepoprawna nazwa etykiety: {nazwa!r}")
    if any(z in nazwa for z in "\r\n\"") :
        raise Odmowa(f"niedozwolone znaki w nazwie etykiety: {nazwa!r}")
    mala = nazwa.lower()
    if mala == "inbox":
        return "\\Inbox", False
    if nazwa.startswith("\\"):
        if mala in DOZWOLONE_SYSTEMOWE:
            return DOZWOLONE_SYSTEMOWE[mala], False
        raise Odmowa(f"etykieta systemowa {nazwa} jest zabroniona (dozwolone: \\Inbox, \\Important, \\Starred)")
    if mala.startswith(("[gmail]", "[google mail]")):
        raise Odmowa(f"foldery systemowe Gmaila są zabronione: {nazwa}")
    for z in ZABRONIONE:
        if mala == z or mala.startswith(z + "/"):
            raise Odmowa(f"etykieta {nazwa} uruchamia import do Paperless, bramka jej nie rusza")
    for e in istniejace:
        if e.lower() == mala:
            return e, False
    if not mala.startswith(PRZEDROSTEK_AGENTA) or len(nazwa) == len(PRZEDROSTEK_AGENTA):
        raise Odmowa(f"etykieta {nazwa} nie istnieje, a nowe etykiety wolno zakładać tylko z przedrostkiem {PRZEDROSTEK_AGENTA}")
    return nazwa, True
