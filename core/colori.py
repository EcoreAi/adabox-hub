"""I colori che un record può scegliere (fasi, etichette): un elenco chiuso, che nel CSS diventa la classe ui-tinta-<nome>.

Rosso e arancione restano fuori: sono l'urgenza e non devono voler dire anche «questa fase».
L'ordine è provato per chi distingue male i colori: i primi cinque, vicini, restano separati (basta per le fasi della
pipeline, col verde per l'ultima). Il nome accompagna sempre il colore, che da solo non dice mai nulla."""
import re

COLORI = [("indaco", "Indaco"), ("rosa", "Rosa"), ("azzurro", "Azzurro"), ("viola", "Viola"), ("verde", "Verde"),
          ("turchese", "Turchese"), ("grigio", "Grigio")]
TINTE_PERSONE = [c for c, _ in COLORI if c != "grigio"]
COLORI_COLONNE = ["indaco", "rosa", "azzurro", "viola"]     # per le fasi senza un colore proprio; il verde resta a chi ha finito
ESADECIMALE = re.compile(r"#[0-9a-fA-F]{6}")


def sicuro(colore, ripiego="grigio"):
    """I colori di tag e categorie sono testo libero e finiscono in uno stile: passano solo se sono davvero colori."""
    return colore if colore and ESADECIMALE.fullmatch(colore) else ripiego


def tinta_persona(pk):
    """Sempre lo stesso colore per la stessa persona, in ogni pagina."""
    return TINTE_PERSONE[(pk or 0) % len(TINTE_PERSONE)]


def iniziali(utente):
    parole = (utente.get_full_name() or utente.get_username()).split()
    return "".join(p[0] for p in parole[:2]).upper() or "?"
