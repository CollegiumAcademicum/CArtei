FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libldap-dev \
    libsasl2-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libffi8 \
    fonts-dejavu-core \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-extra \
    texlive-extra-utils \
    latexmk \
    && rm -rf /var/lib/apt/lists/*

# PyLaTeX adds lastpage.sty from this package.
RUN apt-get update && apt-get install -y --no-install-recommends texlive-latex-extra && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN uv sync --no-group dev

COPY . .

EXPOSE 8000

CMD ["sh", "-c", \
  "uv run python manage.py migrate --settings=cartei.settings && \
   uv run python manage.py collectstatic --noinput --settings=cartei.settings && \
   uv run gunicorn cartei.wsgi:application --config gunicorn.conf.py"]
