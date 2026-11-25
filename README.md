# bramka-poczty

Serwer MCP między agentem AI a skrzynką Gmail. Agent może przez niego szukać i czytać maile, nadawać i zdejmować etykiety (archiwizacja to zdjęcie etykiety `\Inbox`), oznaczać maile jako przeczytane i wstawić do Odebranych podsumowanie dla właściciela. **Nie może niczego usunąć, przenieść do kosza ani wysłać**, bo bramka nie ma tych operacji w kodzie. Każda operacja trafia do dziennika, a właściciel może cofnąć cały przebieg agenta.

Zasada: działania odwracalne przechodzą, nieodwracalne nie istnieją.

## Jak to działa

- Dostęp do Gmaila przez IMAP z [hasłem aplikacji](https://support.google.com/accounts/answer/185833), bez Google Cloud i Gmail API. Bramka korzysta z rozszerzeń IMAP Gmaila: wyszukiwania składnią Gmaila (`X-GM-RAW`), etykiet (`X-GM-LABELS`) i stałych identyfikatorów (`X-GM-MSGID`). Wszystko dzieje się w folderze „Wszystkie” (flaga `\All`).
- Brak SMTP, `\Deleted` i `EXPUNGE`. Podsumowanie trafia do Odebranych przez IMAP `APPEND`, więc nic nie jest wysyłane.
- Treść jest pobierana przez `BODY.PEEK`, więc czytanie nie oznacza maila jako przeczytanego. Bramka pobiera tylko części tekstowe wskazane przez `BODYSTRUCTURE`, nigdy załączniki. HTML zamienia na tekst.
- Serwer MCP: [Python SDK](https://github.com/modelcontextprotocol/python-sdk) `mcp`, transport Streamable HTTP na `/mcp`.

## Narzędzia MCP

Identyfikatory maili są tekstem: `X-GM-MSGID` przekracza 2⁵³, a klienci w JavaScripcie tracą wtedy cyfry.

| Narzędzie | Co robi |
|---|---|
| `szukaj(zapytanie, limit=50, kursor)` | wyszukiwanie składnią Gmaila. Zwraca metadane, fragment treści (300 znaków), etykiety i listę załączników, najwyżej 100 na stronę |
| `czytaj(id, max_znakow=8000)` | treść jako tekst, najwyżej 30 000 znaków |
| `watek(id)` | metadane maili z wątku |
| `etykiety()` | etykiety użytkownika i dozwolone systemowe |
| `etykietuj(ids, dodaj, usun)` | najwyżej 100 maili naraz |
| `oznacz_przeczytane(ids, przeczytane)` | flaga `\Seen` |
| `wstaw_podsumowanie(temat, tresc)` | wstawia do Odebranych maila od właściciela do właściciela, najwyżej 3 na przebieg. Treść w Markdownie bramka wstawia jako HTML i jako zwykły tekst; surowy HTML z treści zostaje pokazany jako tekst. Pod treścią bramka sama dopisuje listę maili zarchiwizowanych w tym przebiegu, z linkami |

## Reguły etykiet

- Etykiety systemowe: dozwolone tylko `\Inbox`, `\Important` i `\Starred`. `\Trash`, `\Spam`, `\Sent`, `\Draft`, inne systemowe i foldery `[Gmail]/…` są zabronione.
- `do-paperless`, `w-paperless` i `paperless` (z podetykietami) są zabronione, bo uruchamiają import do Paperless-ngx.
- Nowe etykiety wolno zakładać tylko z przedrostkiem `agent/`. Istniejące etykiety można nadawać i zdejmować.
- Zabronioną operację bramka odrzuca w całości i zapisuje w dzienniku z powodem.

## Przebieg, dziennik, cofanie

- Każde żądanie musi mieć nagłówek `X-Przebieg` z identyfikatorem uruchomienia agenta (np. `2026-11-26T05-00`), nadawanym przez skrypt startujący agenta. Bez niego bramka odmawia.
- Dziennik to plik SQLite: czas, przebieg, narzędzie, id maila, parametry, wynik (`ok`, `odmowa`, `blad`). Przy zmianach zapisuje tylko to, co faktycznie się zmieniło.
- `bramka cofnij <przebieg>` odwraca etykiety i flagi przebiegu, od ostatniej zmiany. Wstawionych podsumowań nie usuwa. `bramka przebiegi` pokazuje ostatnie przebiegi.

## Konfiguracja

| Zmienna | Znaczenie |
|---|---|
| `GMAIL_ADRES` | adres skrzynki, zarazem nadawca i adresat podsumowań |
| `GMAIL_HASLO_APLIKACJI` | hasło aplikacji Google, najlepiej osobne dla bramki |
| `BRAMKA_TOKEN` | token agenta, nagłówek `Authorization: Bearer <token>` |
| `BRAMKA_DZIENNIK` | plik dziennika, domyślnie `/data/dziennik.sqlite` |
| `BRAMKA_PORT` | port HTTP, domyślnie `8000` |

Między agentem a bramką powinien być HTTPS (np. reverse proxy), bo przez to połączenie idą token i treść maili.

## Uruchomienie

```
docker run -d -p 8000:8000 -v /sciezka/na/dziennik:/data \
  -e GMAIL_ADRES=... -e GMAIL_HASLO_APLIKACJI=... -e BRAMKA_TOKEN=... \
  ghcr.io/ludio71/bramka-poczty:<wersja>
```

Kontener działa jako użytkownik `568:568`, który musi mieć prawo zapisu w `/data`.

Obraz buduje GitHub Actions po każdej zmianie w `main` (tag `main` i `sha-…`) i po tagu `v*` (tag z numerem wersji oraz `latest`). `latest` wskazuje więc ostatnią wydaną wersję, a nie każdą zmianę w `main`.

## Rozwój

```
uv run pytest
```

Testy nie łączą się z Gmailem:
- reguły, dziennik i cofanie sprawdzają na atrapie skrzynki w pamięci;
- strukturę MIME na odpowiedziach w formacie IMAP;
- całą drogę przez HTTP z klientem MCP z SDK.

Na prawdziwej skrzynce nie sprawdzono jeszcze:
- zdejmowania etykiet przez `-X-GM-LABELS`, także etykiet systemowych w cudzysłowie;
- odnajdywania wstawionego podsumowania;
- formatu linku do maila.
