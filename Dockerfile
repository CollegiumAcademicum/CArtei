# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /code

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       libc6-dev \
       libldap2-dev \
       libsasl2-dev \
       libssl-dev \
       ldap-utils \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /code/
COPY .env /code/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY src/cartei /code/

# Copy CA certificate and update CA certificates
COPY ca.cert /usr/local/share/ca-certificates/ca.crt
RUN update-ca-certificates

# Create ldap directory and configure LDAP to use the CA certificate
RUN mkdir -p /etc/ldap
RUN echo "TLS_CACERT /usr/local/share/ca-certificates/ca.crt" >> /etc/ldap/ldap.conf

# Run the application
# First run migrations and then start the application using Gunicorn
RUN python manage.py makemigrations app
RUN python manage.py migrate
RUN python manage.py create_tiles

CMD ["sh", "-c", "python manage.py makemigrations && python manage.py migrate && gunicorn --bind 0.0.0.0:8000 cartei.wsgi:application"]
