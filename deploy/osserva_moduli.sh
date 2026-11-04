#!/bin/sh
# Quando cambiano i moduli (li può installare il worker, sincronizzandosi col portale) il server si aggiorna da solo:
# «hup» manda SIGHUP a gunicorn tramite il pidfile, «esci» termina il processo 1 e il restart riparte col codice nuovo.
modo="${1:-hup}"
impronta() { ls -l --time-style=full-iso addons/installed.json addons/*/__manifest__.py 2>/dev/null | md5sum; }
ultima="$(impronta)"
while sleep 20; do
    adesso="$(impronta)"
    [ "$adesso" = "$ultima" ] && continue
    ultima="$adesso"
    sleep 5          # si lascia finire l'installazione in corso
    ultima="$(impronta)"
    if [ "$modo" = "esci" ]; then kill -TERM 1; else kill -HUP "$(cat "${GUNICORN_PIDFILE:-/tmp/gunicorn.pid}")" 2>/dev/null; fi
done
