/* Impostazioni: una sezione alla volta (scelta dall'indice o dall'#ancora), ricerca tra sezioni e singole
   impostazioni, avviso se si lasciano modifiche non salvate. Senza questo script la pagina mostra tutto in colonna. */
(function () {
  const radice = document.querySelector("[data-imp]");
  if (!radice) return;
  const sezioni = Array.from(radice.querySelectorAll(".imp-sezione"));
  if (!sezioni.length) return;
  const voci = Array.from(radice.querySelectorAll("#imp-voci a[data-sezione]"));
  const cerca = document.getElementById("imp-cerca");
  const risultati = document.getElementById("imp-risultati");
  const elenco = document.getElementById("imp-voci");
  const telefono = window.matchMedia("(max-width: 767px)");
  const modificate = new Set();
  let aperta = null;

  radice.classList.add("is-js");

  const normalizza = (t) => (t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim();

  // indice per la ricerca: titolo della sezione e, per ogni campo, etichetta e testo d'aiuto
  const indice = sezioni.map((s) => ({
    sezione: s,
    titolo: s.dataset.titolo,
    testo: normalizza(s.dataset.titolo + " " + s.dataset.gruppo + " " + (s.querySelector(".ui-card-sub")?.textContent || "")),
    campi: Array.from(s.querySelectorAll(".ui-form-group, .df-scelta")).map((g) => {
      const etichetta = (g.querySelector(".ui-label, .ui-checkbox-row") || g).textContent.replace(/\s*\*\s*$/, "").trim();
      return { gruppo: g, etichetta, testo: normalizza(g.textContent) };
    }),
  }));

  function trova(id) { return sezioni.find((s) => s.id === id); }

  function mostra(id, opzioni = {}) {
    const sezione = trova(id) || sezioni[0];
    if (aperta && aperta !== sezione && modificate.has(aperta.id) && !opzioni.forza) {
      if (!window.confirm(`Ci sono modifiche non salvate in «${aperta.dataset.titolo}». Le lasci?`)) {
        history.replaceState(null, "", "#" + aperta.id);
        return false;
      }
      modificate.delete(aperta.id);
      aperta.querySelector("form")?.reset();
    }
    aperta = sezione;
    sezioni.forEach((s) => s.classList.toggle("is-aperta", s === sezione));
    voci.forEach((v) => {
      const attiva = v.dataset.sezione === sezione.id;
      v.classList.toggle("is-active", attiva);
      if (attiva) v.setAttribute("aria-current", "true"); else v.removeAttribute("aria-current");
    });
    if (!opzioni.iniziale) radice.classList.add("mostra-sezione");
    if (location.hash !== "#" + sezione.id) history.replaceState(null, "", "#" + sezione.id);
    if (!opzioni.iniziale) {
      const alto = radice.getBoundingClientRect().top + window.scrollY - 80;
      if (window.scrollY > alto || telefono.matches) window.scrollTo({ top: Math.max(alto, 0) });
    }
    return true;
  }

  function evidenzia(gruppo) {
    gruppo.scrollIntoView({ block: "center", behavior: "smooth" });
    gruppo.classList.remove("imp-trovato");
    void gruppo.offsetWidth;                                    // riavvia l'animazione
    gruppo.classList.add("imp-trovato");
    gruppo.querySelector("input:not([type=hidden]), select, textarea")?.focus({ preventScroll: true });
  }

  // ---------- ricerca ----------
  function filtra() {
    const q = normalizza(cerca.value);
    if (!q) {
      risultati.hidden = true;
      risultati.innerHTML = "";
      elenco.querySelectorAll("a, .imp-gruppo").forEach((el) => { el.hidden = false; });
      return;
    }
    const parole = q.split(" ");
    const tutte = (t) => parole.every((p) => t.includes(p));
    const sezioniOk = new Set();
    const trovati = [];
    indice.forEach((voce) => {
      if (tutte(voce.testo)) sezioniOk.add(voce.sezione.id);
      voce.campi.forEach((c) => {
        if (tutte(c.testo)) { sezioniOk.add(voce.sezione.id); trovati.push({ voce, campo: c }); }
      });
    });
    elenco.querySelectorAll("a").forEach((a) => {
      a.hidden = a.dataset.sezione ? !sezioniOk.has(a.dataset.sezione) : !tutte(normalizza(a.textContent));
    });
    elenco.querySelectorAll(".imp-gruppo").forEach((g) => { g.hidden = !g.querySelector("a:not([hidden])"); });

    risultati.innerHTML = "";
    if (trovati.length) {
      const titolo = document.createElement("div");
      titolo.className = "imp-gruppo-titolo";
      titolo.textContent = trovati.length === 1 ? "1 impostazione" : `${trovati.length} impostazioni`;
      risultati.append(titolo);
      trovati.slice(0, 30).forEach(({ voce, campo }) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "imp-risultato";
        const dove = document.createElement("span");
        dove.className = "imp-risultato-dove";
        dove.textContent = voce.titolo;
        const nome = document.createElement("span");
        nome.textContent = campo.etichetta;
        b.append(dove, nome);
        b.addEventListener("click", () => { if (mostra(voce.sezione.id)) evidenzia(campo.gruppo); });
        risultati.append(b);
      });
    } else if (!sezioniOk.size && !elenco.querySelector("a:not([hidden])")) {
      const vuoto = document.createElement("p");
      vuoto.className = "imp-vuoto";
      vuoto.textContent = "Nessuna impostazione trovata.";
      risultati.append(vuoto);
    }
    risultati.hidden = !risultati.childElementCount;
  }

  cerca.addEventListener("input", filtra);
  cerca.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { cerca.value = ""; filtra(); }
    if (e.key === "Enter") {
      e.preventDefault();
      (risultati.querySelector(".imp-risultato") || elenco.querySelector("a[data-sezione]:not([hidden])"))?.click();
    }
  });
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    e.preventDefault();
    cerca.focus();
    cerca.select();
  });

  // ---------- navigazione ----------
  voci.forEach((v) => v.addEventListener("click", (e) => {
    e.preventDefault();
    mostra(v.dataset.sezione);
  }));
  window.addEventListener("hashchange", () => mostra(location.hash.slice(1)));
  radice.querySelector("[data-imp-indietro]")?.addEventListener("click", () => {
    radice.classList.remove("mostra-sezione");
    window.scrollTo({ top: 0 });
  });

  // ---------- modifiche non salvate ----------
  sezioni.forEach((s) => {
    const form = s.querySelector("form");
    if (!form) return;
    const segna = () => modificate.add(s.id);
    form.addEventListener("input", segna);
    form.addEventListener("change", segna);
    form.addEventListener("submit", () => modificate.delete(s.id));
  });
  window.addEventListener("beforeunload", (e) => {
    if (modificate.size) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---------- apertura ----------
  // dopo un errore di validazione si riapre la sezione inviata; altrimenti l'#ancora o la prima
  const iniziale = radice.dataset.aperta || location.hash.slice(1);
  mostra(iniziale, { iniziale: true, forza: true });
  if (iniziale && trova(iniziale)) radice.classList.add("mostra-sezione");
  const errore = aperta.querySelector(".has-error");
  if (errore) evidenzia(errore);
})();
