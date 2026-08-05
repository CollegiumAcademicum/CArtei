FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libldap-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN uv sync --no-group dev

COPY . .

EXPOSE 8000

CMD ["sh", "-c", \
  "uv run python manage.py migrate --settings=cartei.settings && \
   uv run python manage.py collectstatic --noinput --settings=cartei.settings && \
   uv run gunicorn cartei.wsgi:application --config gunicorn.conf.py"]
