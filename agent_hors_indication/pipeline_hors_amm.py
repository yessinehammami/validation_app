"""Pipeline hors AMM : requêtes (LLM) -> collecte (code) -> extraction (LLM) -> validation (code).

Le modèle ne produit jamais de lien : il cite des identifiants de sources (S1, S2...) et le code
reconstruit les liens à partir des sources réellement récupérées.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from agent_hors_indication.sources_hors_amm import (
    clinicaltrials_search, lien_valide, pubmed_search, web_institutionnel, web_officiel_gratuit,
)

MAX_SOURCES = 40

PROMPT_REQUETES = """Tu prépares des recherches documentaires sur l'usage HORS AMM de médicaments.
À partir de la question de l'utilisateur, réponds UNIQUEMENT par un objet JSON :
{
  "type": "indication" | "produit",
  "indication_en": "pathologie en anglais ou null",
  "medicament_en": "DCI en anglais ou null",
  "pubmed": ["2 à 4 requêtes PubMed en anglais, syntaxe PubMed, avec des termes comme off-label, unlicensed, \
repurposing, systematic review, randomized"],
  "web": ["2 à 3 requêtes en français ou anglais visant HAS, ANSM, EMA, FDA, sociétés savantes, RTU, CPC"]
}"""

PROMPT_EXTRACTION = """Tu extrais des faits à partir de SOURCES numérotées (S1, S2...). Tu n'as le droit d'utiliser \
QUE le texte de ces sources, jamais tes connaissances générales.

Objectif : lister les utilisations hors AMM (off-label / non autorisées) de médicaments, selon la question.
Réponds UNIQUEMENT par un objet JSON : {"resultats": [ ... ]}, chaque élément :
{
  "medicament": "DCI",
  "indication": "indication concernée",
  "statut": "hors_amm_explicite" | "usage_etudie" | "amm",
  "type_etude": "recommandation | méta-analyse | essai randomisé | essai clinique | cohorte | série/cas clinique | revue | autre",
  "resume": "1 à 2 phrases fidèles à la source",
  "citation": "extrait COPIÉ MOT POUR MOT du texte de la source (max 200 caractères)",
  "sources": ["S3"]
}
Règles :
- "hors_amm_explicite" : la source dit explicitement que l'usage est off-label / hors AMM / non autorisé / repositionné.
- "usage_etudie" : la source étudie ce médicament dans cette indication sans dire explicitement qu'il est hors AMM.
- "amm" : la source indique que l'indication est autorisée. 
- Une entrée par couple (médicament, indication, source). N'invente rien. Ignore les sources hors sujet.
- La citation doit exister telle quelle dans la source, sinon l'entrée sera rejetée.
- Si rien d'exploitable : {"resultats": []}."""


def _json(client, modele, system, user):
    rep = client.chat.completions.create(
        model=modele,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
    )
    return json.loads(rep.choices[0].message.content or "{}")


def generer_requetes(client, modele, question):
    return _json(client, modele, PROMPT_REQUETES, question)


def collecter(requetes, tavily_key=None):
    """Lance les recherches en parallèle. Retourne (registre {id: source}, journal [(outil, requête)])."""
    taches = []
    for q in requetes.get("pubmed", [])[:4]:
        taches.append(("PubMed", q, lambda q=q: pubmed_search(q, max_results=8)))
    cond, med = requetes.get("indication_en"), requetes.get("medicament_en")
    if cond or med:
        taches.append(("ClinicalTrials.gov", f"{cond or ''} | {med or ''}",
                       lambda: clinicaltrials_search(cond, med, max_results=8)))
    for q in requetes.get("web", [])[:3]:
        if tavily_key:
            taches.append(("Web officiel", q, lambda q=q: web_institutionnel(q, tavily_key, max_results=5)))
        else:
            taches.append(("Web officiel", q, lambda q=q: web_officiel_gratuit(q)))

    def lancer(t):
        try:
            return t, t[2](), None
        except Exception as e:  # une source en échec ne doit pas bloquer les autres
            return t, [], str(e)

    with ThreadPoolExecutor(max_workers=6) as ex:
        sorties = list(ex.map(lancer, taches))

    registre, vus, journal = {}, set(), []
    for (outil, q, _), items, erreur in sorties:
        journal.append((outil, q, len(items), erreur))
        for it in items:
            url = it.get("url")
            if not url or url in vus or len(registre) >= MAX_SOURCES:
                continue
            vus.add(url)
            sid = f"S{len(registre) + 1}"
            if outil == "PubMed":
                texte = f"{it['titre']}. Types: {', '.join(it['types'])}. {it['resume']}"
                label = f"PMID {it['pmid']}"
            elif outil == "ClinicalTrials.gov":
                texte = f"{it['titre']}. Conditions: {', '.join(it['conditions'])}. {it['resume']}"
                label = it["nct"]
            else:
                texte = f"{it['titre']}. {it['resume']}"
                label = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            registre[sid] = {"id": sid, "outil": outil, "label": label, "titre": it["titre"], "url": url, "texte": texte}
    return registre, journal


def extraire(client, modele, question, registre):
    if not registre:
        return []
    corpus = "\n\n".join(f"[{s['id']}] ({s['outil']}) {s['texte']}" for s in registre.values())
    data = _json(client, modele, PROMPT_EXTRACTION, f"QUESTION : {question}\n\nSOURCES :\n{corpus}")
    return data.get("resultats", [])


def _norm(t):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t.lower())).strip()


def valider(resultats, registre, verifier_liens=True):
    """Garde les résultats dont les sources existent, la citation est exacte et le statut n'est pas AMM."""
    liens = {}
    if verifier_liens:
        # PubMed et ClinicalTrials : liens construits à partir des identifiants renvoyés par l'API
        urls = {s["url"] for s in registre.values() if s["outil"] == "Web officiel"}
        with ThreadPoolExecutor(max_workers=8) as ex:
            liens = dict(zip(urls, ex.map(lien_valide, urls)))

    gardes, rejetes = [], 0
    for r in resultats:
        ids = [i for i in r.get("sources", []) if i in registre]
        statut = r.get("statut")
        citation = _norm(r.get("citation", ""))
        if not ids or statut not in ("hors_amm_explicite", "usage_etudie") or len(citation) < 15:
            rejetes += 1
            continue
        ids_ok = [i for i in ids if citation in _norm(registre[i]["texte"])]
        if not ids_ok:
            rejetes += 1
            continue
        if verifier_liens:
            ids_ok = [i for i in ids_ok if registre[i]["outil"] != "Web officiel" or liens.get(registre[i]["url"], False)]
            if not ids_ok:
                rejetes += 1
                continue
        gardes.append({**r, "liens": [registre[i] for i in ids_ok]})

    ordre = {"hors_amm_explicite": 0, "usage_etudie": 1}
    gardes.sort(key=lambda r: (ordre[r["statut"]], r.get("medicament", "").lower()))
    return gardes, rejetes
