"""Étape 2 : interroger PubMed (API gratuite NCBI E-utilities, sans clé)."""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 20


def pubmed_search(query, max_results=8):
    """Retourne une liste de dicts : pmid, titre, resume, url."""
    # Appel 1 (esearch) : la requête -> une liste d'identifiants (PMID)
    r = requests.get(
        f"{BASE}/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json", "sort": "relevance"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    pmids = r.json()["esearchresult"]["idlist"]
    if not pmids:
        return []

    # Appel 2 (efetch) : les PMID -> le contenu des articles (XML)
    r = requests.get(
        f"{BASE}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()

    articles = []
    racine = ET.fromstring(r.content)
    # PubMed renvoie deux formats : articles de revue (PubmedArticle) et chapitres de livres (PubmedBookArticle)
    for art in racine.findall("PubmedArticle") + racine.findall("PubmedBookArticle"):
        pmid = art.findtext(".//PMID")
        titre_el = art.find(".//ArticleTitle")
        if titre_el is None:
            titre_el = art.find(".//BookTitle")
        titre = "".join(titre_el.itertext()) if titre_el is not None else ""
        # un résumé peut avoir plusieurs paragraphes (Background, Methods, Results...)
        resume = " ".join("".join(p.itertext()) for p in art.findall(".//AbstractText"))
        articles.append({
            "pmid": pmid,
            "source": "PubMed",
            "titre": titre,
            "resume": resume,
            # le lien est construit par NOUS à partir du PMID : il ne peut pas être inventé
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return articles


def europepmc_search(query, max_results=5):
    """Europe PMC (gratuit) : même format que pubmed_search. Syntaxe : mots, AND, OR, guillemets."""
    r = requests.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": max_results, "resultType": "core"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    articles = []
    for x in r.json()["resultList"]["result"]:
        origine, ident = x.get("source"), x.get("id")
        if not ident:
            continue
        # les notices MED sont les mêmes que PubMed : on garde le lien PubMed et le pmid pour dédoublonner
        url = (f"https://pubmed.ncbi.nlm.nih.gov/{ident}/" if origine == "MED"
               else f"https://europepmc.org/article/{origine}/{ident}")
        resume = re.sub(r"<[^>]+>", "", x.get("abstractText", ""))
        articles.append({"pmid": ident if origine == "MED" else None, "source": "Europe PMC",
                         "titre": re.sub(r"<[^>]+>", "", x.get("title", "")), "resume": resume, "url": url})
    return articles


def clinicaltrials_search(medicament=None, pathologie=None, max_results=5):
    """ClinicalTrials.gov (API v2, gratuite) : essais cliniques pour un médicament et/ou une pathologie."""
    params = {"pageSize": max_results, "format": "json"}
    if medicament:
        params["query.intr"] = medicament
    if pathologie:
        params["query.cond"] = pathologie
    if not medicament and not pathologie:
        return []
    r = requests.get("https://clinicaltrials.gov/api/v2/studies", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    essais = []
    for e in r.json().get("studies", []):
        p = e["protocolSection"]
        nct = p["identificationModule"]["nctId"]
        desc = p.get("descriptionModule", {}).get("briefSummary", "")
        conds = ", ".join(p.get("conditionsModule", {}).get("conditions", []))
        statut = p.get("statusModule", {}).get("overallStatus", "")
        essais.append({
            "pmid": None, "source": "ClinicalTrials.gov",
            "titre": p["identificationModule"].get("briefTitle", ""),
            "resume": f"Essai {nct} (statut : {statut}). Conditions : {conds}. {desc}",
            "url": f"https://clinicaltrials.gov/study/{nct}",
        })
    return essais


DOMAINES_OFFICIELS = ["ansm.sante.fr", "has-sante.fr", "ema.europa.eu", "fda.gov"]

FILTRE_PUBMED = '("off-label"[tiab] OR unlicensed[tiab] OR repurposing[tiab] OR "off label"[tiab])'
FILTRE_EUROPEPMC = '("off-label" OR unlicensed OR repurposing OR "off label")'


def collecter(plan, n=5):
    """Interroge toutes les sources en parallèle. Retourne (articles dédoublonnés, journal)."""
    med, patho = plan.get("medicament_en"), plan.get("pathologie_en")
    termes = " ".join(t for t in (med, patho) if t)
    taches = []
    for q in plan.get("requetes", []):
        taches.append(("PubMed", f"({q}) AND {FILTRE_PUBMED}", lambda q=q: pubmed_search(f"({q}) AND {FILTRE_PUBMED}", n)))
    if termes:
        epmc = " AND ".join(f"({t})" for t in (med, patho) if t) + f" AND {FILTRE_EUROPEPMC}"
        taches.append(("Europe PMC", epmc, lambda: europepmc_search(epmc, n)))
        taches.append(("ClinicalTrials.gov", f"médicament={med} · pathologie={patho}", lambda: clinicaltrials_search(med, patho, n)))
        taches.append(("Web officiel", f"{termes} off-label site:" + ", ".join(DOMAINES_OFFICIELS), lambda: web_officiel_search(termes)))

    def lancer(t):
        try:
            return t[0], t[1], t[2](), None
        except Exception as e:  # une source en échec ne doit pas bloquer les autres
            return t[0], t[1], [], str(e)

    with ThreadPoolExecutor(max_workers=4) as ex:
        sorties = list(ex.map(lancer, taches))

    articles, vus, journal = [], set(), []
    for outil, requete, items, erreur in sorties:
        nouveaux = 0
        for a in items:
            cle = a["pmid"] or a["url"]  # Europe PMC renvoie aussi des notices PubMed : même PMID = doublon
            if cle in vus:
                continue
            vus.add(cle)
            articles.append(a)
            nouveaux += 1
        journal.append({"outil": outil, "requete": requete, "trouves": len(items), "nouveaux": nouveaux, "erreur": erreur})
    return articles, journal


def lien_valide(url):
    """False si la page n'existe pas (404/410/5xx ou injoignable). 403/429 et erreurs SSL sont tolérés :
    certains sites bloquent les robots alors que la page s'ouvre dans un navigateur."""
    entetes = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=entetes, timeout=10, allow_redirects=True, stream=True)
    except requests.exceptions.SSLError:
        return True
    except requests.RequestException:
        return False
    r.close()
    return r.status_code not in (404, 410) and r.status_code < 500


def web_officiel_search(terme, max_results_par_site=2):
    """Recherche web (DuckDuckGo) limitée aux sites officiels. Un site en échec est ignoré."""
    from ddgs import DDGS

    candidats = []
    for domaine in DOMAINES_OFFICIELS:
        try:
            trouves = DDGS().text(f"{terme} off-label site:{domaine}", max_results=max_results_par_site)
        except Exception:
            continue
        for x in trouves:
            url = x.get("href", "")
            # le moteur peut renvoyer d'autres sites : on exige le bon domaine
            hote = urlparse(url).netloc.lower()
            if hote == domaine or hote.endswith("." + domaine):
                candidats.append({"pmid": None, "source": f"Web officiel ({domaine})", "titre": x.get("title", ""),
                                  "resume": x.get("body", ""), "url": url})
    # le moteur renvoie parfois des URL tronquées ou périmées (page introuvable) : on les écarte
    with ThreadPoolExecutor(max_workers=6) as ex:
        valides = list(ex.map(lambda c: lien_valide(c["url"]), candidats))
    return [c for c, ok in zip(candidats, valides) if ok]
