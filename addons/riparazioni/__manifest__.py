{
    "name": "Riparazioni",
    "summary": "Garanzie dalla consegna (anche per numero di serie) e ordini di riparazione con preventivo, ricambi dal magazzino, manodopera, riconsegna e fattura",
    "version": "1.0.0",
    "author": "ICHNOBYTE S.R.L.",
    "category": "Assistenza",
    "depends": ["magazzino", "fatturazione"],
    "min_core": "1.0",
    "application": True,
    "icon": "riparazioni/icon.svg",
    "menu": [
        {"label": "Riparazioni", "url_name": "riparazioni:riparazioni_lista", "permission": "riparazioni.view_riparazione"},
        {"label": "Verifica garanzia", "url_name": "riparazioni:verifica", "permission": "riparazioni.view_riparazione"},
        {"label": "Garanzie dei prodotti", "url_name": "riparazioni:garanzie_lista", "permission": "riparazioni.change_garanziaprodotto"},
    ],
    "groups": {
        "Riparazioni / Tecnico": ["riparazioni.view_riparazione", "riparazioni.add_riparazione", "riparazioni.change_riparazione",
                                  "riparazioni.view_rigaricambio", "riparazioni.add_rigaricambio", "riparazioni.change_rigaricambio",
                                  "riparazioni.delete_rigaricambio", "riparazioni.view_garanziaprodotto"],
        "Riparazioni / Responsabile": ["riparazioni.*"],
    },
    "sequences": [{"codice": "riparazioni.riparazione", "formato": "RIP/{anno}/{numero:04d}", "azzera": "anno"}],
}
