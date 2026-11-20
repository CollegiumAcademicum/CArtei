FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# python-ldap compiles against libldap/libsasl. The Briefkastenliste renders
# with Typst (a Python wheel, fonts vendored in app/document_generation/fonts),
# so no TeX Live or other system packages are needed (#148).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libldap-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

# Dependencies resolved from pyproject.toml (uv.lock is not committed), without
# the project itself: this layer is reused until pyproject.toml changes.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# The app runs from /app (manage.py, gunicorn), so the project itself is not
# installed. --link builds this layer on its own: a plain COPY (or any RUN)
# here makes BuildKit download and unpack every cached layer below it
# on each build just to add the app code.
COPY --link . .

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
