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

# Dependencies resolved from pyproject.toml (uv.lock is not committed), without
# the project itself: this layer is reused until pyproject.toml changes.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# The app runs from /app (manage.py, gunicorn), so the project itself is not
# installed: a RUN here would pull every cached layer below it (~1 GB) into
# the builder just to install one local package.
COPY . .

# Commit this image was built from (CI passes the git SHA); see /version/.
ARG GIT_SHA=dev
ENV CARTEI_VERSION=$GIT_SHA

# The environment is complete at build time: keep `uv run` (CMD and ops
# commands via podman exec) from re-syncing it, which would pull the dev group.
ENV UV_NO_SYNC=1

EXPOSE 8000

CMD ["sh", "-c", \
  "uv run python manage.py migrate --settings=cartei.settings && \
   uv run python manage.py collectstatic --noinput --settings=cartei.settings && \
   uv run gunicorn cartei.wsgi:application --config gunicorn.conf.py"]
