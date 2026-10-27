"""File iCalendar (RFC 5545) di un evento, per gli inviti e il download."""
from datetime import timedelta
from datetime import timezone as tz

from django.conf import settings
from django.utils import timezone


def _testo(valore):
    return (valore or "").replace("\\", "\\\\").replace(";", "\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _piega(riga):
    """Righe di massimo 75 ottetti, le successive iniziano con uno spazio."""
    dati, parti = riga.encode("utf-8"), []
    while len(dati) > 75:
        taglio = 75 if not parti else 74
        while (dati[taglio] & 0xC0) == 0x80:      # non spezzare un carattere UTF-8
            taglio -= 1
        parti.append(dati[:taglio])
        dati = dati[taglio:]
    parti.append(dati)
    return "\r\n ".join(p.decode("utf-8") for p in parti)


def _utc(dt):
    return dt.astimezone(tz.utc).strftime("%Y%m%dT%H%M%SZ")


def ics(evento, metodo="PUBLISH"):
    righe = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{settings.THEME.get('brand', 'adabox-hub')}//IT",
             f"METHOD:{metodo}", "BEGIN:VEVENT", f"UID:{evento.uid}@{settings.SITO_URL.split('//')[-1]}",
             f"DTSTAMP:{_utc(timezone.now())}"]
    if evento.tutto_il_giorno:
        inizio = timezone.localtime(evento.inizio).date()
        fine = timezone.localtime(evento.fine).date() + timedelta(days=1)
        righe += [f"DTSTART;VALUE=DATE:{inizio:%Y%m%d}", f"DTEND;VALUE=DATE:{fine:%Y%m%d}"]
    else:
        righe += [f"DTSTART:{_utc(evento.inizio)}", f"DTEND:{_utc(evento.fine)}"]
    righe += [f"SUMMARY:{_testo(evento.titolo)}"]
    if evento.luogo:
        righe.append(f"LOCATION:{_testo(evento.luogo)}")
    if evento.descrizione:
        righe.append(f"DESCRIPTION:{_testo(evento.descrizione)}")
    if evento.organizzatore and evento.organizzatore.email:
        nome = evento.organizzatore.get_full_name() or evento.organizzatore.username
        righe.append(f"ORGANIZER;CN={_testo(nome)}:mailto:{evento.organizzatore.email}")
    for u in evento.partecipanti.exclude(email=""):
        righe.append(f"ATTENDEE;CN={_testo(u.get_full_name() or u.username)};RSVP=TRUE:mailto:{u.email}")
    righe += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_piega(r) for r in righe) + "\r\n"
