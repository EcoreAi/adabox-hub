FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pg_dump per i backup prima di installare o aggiornare moduli; Pango e font per i PDF (WeasyPrint)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/
RUN chmod +x deploy/entrypoint.sh

EXPOSE 8000

CMD ["sh", "deploy/entrypoint.sh"]
