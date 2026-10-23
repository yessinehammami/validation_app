"""Étape 2 : interroger les sources (PubMed, Europe PMC, ClinicalTrials.gov, ANSM, sites officiels)."""
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import urlparse

import requests
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TIMEOUT = 20

# Niveaux de preuve, du plus fort au plus faible : (type de publication en minuscules, libellé affiché).
# Le rang d'un article est la position de son type le plus fort dans cette liste.
NIVEAUX = [
    ("cadre ansm", "Cadre officiel ANSM"),
    ("meta-analysis", "Méta-analyse"),
    ("systematic review", "Revue systématique"),
    ("practice guideline", "Recommandation"),
    ("guideline", "Recommandation"),
    ("randomized controlled trial", "Essai randomisé"),
    ("clinical trial", "Essai clinique"),
    ("essai enregistre", "Essai enregistré"),
    ("observational study", "Étude observationnelle"),
    ("comparative study", "Étude comparative"),
    ("site officiel", "Site officiel"),
    ("review", "Revue"),
    ("case reports", "Cas clinique"),
]


def niveau(types_publication):
    """Retourne (rang, libellé) du type de publication le plus fort ; « Article » si aucun n'est reconnu."""
    types = {t.lower() for t in types_publication}
    for rang, (cle, libelle) in enumerate(NIVEAUX):
        if cle in types:
            return rang, libelle
    return len(NIVEAUX), "Article"


def _annee(texte):
    # pas de \b : PubMed colle souvent l'année au mois (« 2024Jan »)
    m = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", texte or "")
    return int(m.group(0)) if m else None


def pubmed_search(query, max_results=8):
    """Retourne une liste de dicts : pmid, titre, resume, url, type, rang, annee, journal."""
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
        rang, libelle = niveau(t.text or "" for t in art.findall(".//PublicationType"))
        date = art.find(".//PubDate")
        articles.append({
            "pmid": pmid,
            "source": "PubMed",
            "titre": titre,
            "resume": resume,
            # le lien est construit par NOUS à partir du PMID : il ne peut pas être inventé
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "type": libelle, "rang": rang,
            "annee": _annee("".join(date.itertext())) if date is not None else None,
            "journal": art.findtext(".//Journal/ISOAbbreviation") or art.findtext(".//Journal/Title") or "",
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
        rang, libelle = niveau(x.get("pubTypeList", {}).get("pubType", []))
        journal = x.get("journalInfo", {}).get("journal", {})
        articles.append({"pmid": ident if origine == "MED" else None, "source": "Europe PMC",
                         "titre": re.sub(r"<[^>]+>", "", x.get("title", "")), "resume": resume, "url": url,
                         "type": libelle, "rang": rang, "annee": _annee(x.get("pubYear")),
                         "journal": journal.get("isoabbreviation") or journal.get("title") or ""})
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
        rang, libelle = niveau(["essai enregistre"])
        essais.append({
            "pmid": None, "source": "ClinicalTrials.gov",
            "titre": p["identificationModule"].get("briefTitle", ""),
            "resume": f"Essai {nct} (statut : {statut}). Conditions : {conds}. {desc}",
            "url": f"https://clinicaltrials.gov/study/{nct}",
            "type": f"{libelle} ({statut.lower().replace('_', ' ')})" if statut else libelle, "rang": rang,
            "annee": _annee(p.get("statusModule", {}).get("startDateStruct", {}).get("date")), "journal": "",
        })
    return essais


DOMAINES_OFFICIELS = ["ansm.sante.fr", "has-sante.fr", "ema.europa.eu", "fda.gov"]

# Un mot-clé « off-label » écartait la plupart des preuves (les essais et méta-analyses l'emploient rarement) :
# on cherche d'abord les niveaux de preuve élevés, puis on complète sans filtre.
FILTRE_PUBMED = ('(meta-analysis[pt] OR systematic review[pt] OR guideline[pt] OR practice guideline[pt] '
                 'OR randomized controlled trial[pt])')
FILTRE_EUROPEPMC = ('(PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Systematic Review" OR PUB_TYPE:"Practice Guideline" '
                    'OR PUB_TYPE:"Guideline" OR PUB_TYPE:"Randomized Controlled Trial")')


def preuves_fortes_puis_autres(chercher, requete, filtre, n):
    """Cherche `requete` avec le filtre de niveau de preuve ; s'il y a moins de n résultats, complète sans filtre."""
    articles = chercher(f"({requete}) AND {filtre}", n)
    if len(articles) < n:
        vus = {a["pmid"] or a["url"] for a in articles}
        articles += [a for a in chercher(requete, n) if (a["pmid"] or a["url"]) not in vus][: n - len(articles)]
    return articles


def _sans_accents(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in texte if not unicodedata.combining(c)).lower()


ANSM = "https://ansm.sante.fr"
ENTETES = {"User-Agent": "Mozilla/5.0"}


def _texte(fragment):
    # « >? » : un fragment coupé peut finir par une balise non fermée
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>?", " ", fragment))).strip()


def ansm_acces_derogatoire(noms, max_pages=3):
    """Pages « accès dérogatoire » de l'ANSM (CPC, AAC, AAP) d'une substance, trouvées par la recherche du site.

    `noms` : DCI en français et/ou en anglais. Seules les pages dont la substance active contient l'un de ces
    noms (mot entier) sont gardées : « ketamine » ne doit pas ramener l'eskétamine.
    """
    cles = {_sans_accents(n) for n in noms if n}
    chemins = []
    for nom in cles:
        r = requests.get(f"{ANSM}/resultats-de-recherche", params={"global_search[text]": nom},
                         headers=ENTETES, timeout=TIMEOUT)
        r.raise_for_status()
        for c in re.findall(r"/tableau-acces-derogatoire/[a-z0-9-]+", r.text):
            if c not in chemins and not c.endswith("/recherche") and not c.endswith("/impression"):
                chemins.append(c)

    pages = []
    for chemin in chemins:
        if len(pages) >= max_pages:
            break
        r = requests.get(ANSM + chemin, headers=ENTETES, timeout=TIMEOUT)
        if not r.ok:
            continue
        r.encoding = "utf-8"
        page = re.sub(r"(?s)<(script|style|svg)\b.*?</\1>", "", r.text)
        m = re.search(r'(?s)Substance active\s*</h3>\s*<div[^>]*>(.*?)</div>', page)
        substance = _texte(m.group(1)) if m else ""
        if not set(re.findall(r"[a-z0-9]+", _sans_accents(substance))) & cles:
            continue
        m = re.search(r"<title>(.*?)</title>", page)
        # titre de la page : « Liste des spécialités en accès dérogatoire - Kétamine - ANSM »
        titre = _texte(m.group(1)).split(" - ")[1] if m and " - " in m.group(1) else substance

        cadres = []
        # un bloc « panel » par cadre (CPC, AAC, AAP), avec son statut dans l'en-tête
        for bloc in re.split(r'class="panel panel-blue', page)[1:]:
            m = re.search(r'(?s)class="panel-heading[^"]*"[^>]*>(.*?)</div>', bloc)
            entete = _texte(m.group(1)) if m else ""
            # « Cadre de prescription compassionnelle (CPC) – En cours » : le statut suit le dernier tiret
            m = re.match(r"(.*)\s[–-]\s(.+)$", entete)
            cadre, statut = m.groups() if m else (entete, "")
            m = re.search(r"(?s)<h3>\s*(Indication[^<]*)</h3>(.*?)<h3", bloc)
            if m:
                indication = f"{_texte(m.group(1))} : {_texte(m.group(2))}"
            else:  # cadre arrêté, sans indication : on garde le début du texte (« Fin des AAC le … »)
                texte = _texte(re.split(r"Documents de r|Qui sommes", bloc.split(">", 1)[-1])[0])
                indication = texte.replace(entete, "", 1).strip()[:300]
            cadres.append({"cadre": cadre.strip(), "statut": statut.strip(), "indication": indication})
        if not cadres:
            continue
        rang, libelle = niveau(["cadre ansm"])
        pages.append({
            "pmid": None, "source": "ANSM (accès dérogatoire)", "titre": f"{titre} ({substance})",
            "resume": " ; ".join(f"{c['cadre']} – {c['statut']}. {c['indication']}" for c in cadres),
            "url": ANSM + chemin, "type": libelle, "rang": rang, "annee": None, "journal": "", "cadres": cadres,
        })
    return pages


def collecter(plan, n=5):
    """Interroge toutes les sources en parallèle. Retourne (articles dédoublonnés et classés par niveau de preuve, journal)."""
    med, patho = plan.get("medicament_en"), plan.get("pathologie_en")
    med_fr = plan.get("medicament_fr")
    termes = " ".join(t for t in (med, patho) if t)
    taches = []
    for q in plan.get("requetes", []):
        taches.append(("PubMed", f"({q}) AND {FILTRE_PUBMED}\n→ complété sans filtre si < {n} résultats",
                       lambda q=q: preuves_fortes_puis_autres(pubmed_search, q, FILTRE_PUBMED, n)))
    if med or med_fr:
        noms = [x for x in (med_fr, med) if x]
        taches.append(("ANSM (accès dérogatoire)", "recherche du site ansm.sante.fr : " + " / ".join(noms),
                       lambda: ansm_acces_derogatoire(noms)))
    if termes:
        # titre et résumé seulement : sur le texte intégral, les résultats dérivent hors sujet
        epmc = " AND ".join(f'TITLE_ABS:("{t}")' for t in (med, patho) if t)
        taches.append(("Europe PMC", f"{epmc} AND {FILTRE_EUROPEPMC}\n→ complété sans filtre si < {n} résultats",
                       lambda: preuves_fortes_puis_autres(europepmc_search, epmc, FILTRE_EUROPEPMC, n)))
        taches.append(("ClinicalTrials.gov", f"médicament={med} · pathologie={patho}", lambda: clinicaltrials_search(med, patho, n)))
        taches.append(("Web officiel", f"{termes} off-label site:" + ", ".join(DOMAINES_OFFICIELS), lambda: web_officiel_search(termes)))

    def lancer(t):
        try:
            return t[0], t[1], t[2](), None
        except Exception as e:  # une source en échec ne doit pas bloquer les autres
            return t[0], t[1], [], str(e)

    with ThreadPoolExecutor(max_workers=len(taches) or 1) as ex:
        sorties = list(ex.map(lancer, taches))

    articles, vus, journal = [], set(), []
    for outil, requete, items, erreur in sorties:
        nouveaux = 0
        for a in items:
            # Europe PMC renvoie aussi des notices PubMed (même PMID) et parfois plusieurs versions d'un même
            # texte (même titre) : ce sont des doublons
            cles = {a["pmid"] or a["url"], re.sub(r"[^a-z0-9]", "", _sans_accents(a["titre"]))[:80] or a["url"]}
            if cles & vus:
                continue
            vus |= cles
            articles.append(a)
            nouveaux += 1
        journal.append({"outil": outil, "requete": requete, "trouves": len(items), "nouveaux": nouveaux, "erreur": erreur})
    # cadres ANSM d'abord, puis méta-analyses, revues systématiques… ; à niveau égal, le plus récent d'abord
    articles.sort(key=lambda a: (a.get("rang", len(NIVEAUX)), -(a.get("annee") or 0)))
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
                rang, libelle = niveau(["site officiel"])
                candidats.append({"pmid": None, "source": f"Web officiel ({domaine})", "titre": x.get("title", ""),
                                  "resume": x.get("body", ""), "url": url,
                                  "type": libelle, "rang": rang, "annee": None, "journal": ""})
    # le moteur renvoie parfois des URL tronquées ou périmées (page introuvable) : on les écarte
    with ThreadPoolExecutor(max_workers=6) as ex:
        valides = list(ex.map(lambda c: lien_valide(c["url"]), candidats))
    return [c for c, ok in zip(candidats, valides) if ok]
