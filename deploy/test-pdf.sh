#!/bin/sh
# Esegue nell'immagine Docker (che ha Pango e i font) i test che generano PDF veri.
#   deploy/test-pdf.sh            -> pytest -m pdf
#   deploy/test-pdf.sh <argomenti> -> pytest <argomenti>
set -e
cd "$(dirname "$0")/.."
if [ "$#" -eq 0 ]; then set -- -m pdf; fi
docker run --rm -v "$PWD":/app -w /app -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 adabox_hub:latest \
  sh -c 'pip install -q --root-user-action=ignore -r requirements-dev.txt && python -m pytest -p no:cacheprovider "$@"' -- "$@"
