FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# pg_dump per i backup prima di installare o aggiornare moduli; Pango e font per i PDF (WeasyPrint)
# DOCUMENTI=si (default): Tesseract con l'italiano, GLib per OpenCV e requirements-documenti.txt, per i moduli che
# leggono e scansionano documenti (circa 500 MB in più). Con --build-arg DOCUMENTI=no l'immagine resta leggera e
# quei moduli non si installano (core.registry.dipendenze).
ARG DOCUMENTI=si
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && if [ "$DOCUMENTI" = si ]; then apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-ita libglib2.0-0t64; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-documenti.txt /app/
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$DOCUMENTI" = si ]; then pip install --no-cache-dir -r requirements-documenti.txt; fi

COPY . /app/
RUN chmod +x deploy/entrypoint.sh

EXPOSE 8000

CMD ["sh", "deploy/entrypoint.sh"]
