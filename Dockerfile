FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    BRAMKA_DZIENNIK=/data/dziennik.sqlite \
    BRAMKA_PORT=8000

# Użytkownik apps z TrueNAS (568), właściciel datasetu z dziennikiem.
USER 568:568
EXPOSE 8000
CMD ["bramka", "serwer"]
