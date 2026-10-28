"""Validazione della fattura elettronica con lo schema ufficiale FatturaPA 1.2.2 (copia locale, senza rete)."""
from functools import lru_cache
from pathlib import Path

from lxml import etree

SCHEMI = Path(__file__).parent / "schemi"
SCHEMA = SCHEMI / "Schema_del_file_xml_FatturaPA_v1.2.2.xsd"


def _parser():
    # niente rete né entità esterne: l'import di xmldsig punta al file accanto
    return etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False, huge_tree=False)


@lru_cache(maxsize=1)
def schema():
    parser = etree.XMLParser(no_network=True, load_dtd=True)          # lo schema xmldsig ha un DTD interno
    return etree.XMLSchema(etree.parse(str(SCHEMA), parser))


def errori(contenuto):
    """Lista di messaggi (vuota se l'XML è valido). `contenuto`: bytes dell'XML."""
    try:
        documento = etree.fromstring(contenuto, _parser())
    except etree.XMLSyntaxError as e:
        return [f"XML non leggibile: {e}"]
    s = schema()
    if s.validate(documento):
        return []
    return [f"riga {e.line}: {_pulisci(e.message)}" for e in s.error_log][:50]


def _pulisci(messaggio):
    return messaggio.replace("{http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2}", "")
