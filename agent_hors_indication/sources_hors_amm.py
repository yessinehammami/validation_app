"""Sources de références pour la recherche hors AMM : PubMed et ClinicalTrials.gov."""
import re
import xml.etree.ElementTree as ET

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT = 30
ABSTRACT_MAX = 900


def _texte(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def pubmed_search(query, max_results=8, years=None):
    """Recherche PubMed (syntaxe PubMed acceptée). Renvoie titre, revue, année, types de publication, résumé."""
    max_results = max(1, min(int(max_results or 8), 15))
    term = query
    if years:
        term = f"({query}) AND (\"last {int(years)} years\"[dp])"
    r = requests.get(
        f"{EUTILS}/esearch.fcgi",
        params={"db": "pubmed", "term": term, "retmax": max_results, "retmode": "json", "sort": "relevance"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    ids = r.json()["esearchresult"]["idlist"]
    if not ids:
        return []
    r = requests.get(
        f"{EUTILS}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    resultats = []
    for art in ET.fromstring(r.content).findall(".//PubmedArticle"):
        pmid = _texte(art.find(".//PMID"))
        annee = _texte(art.find(".//JournalIssue/PubDate/Year")) or _texte(
            art.find(".//JournalIssue/PubDate/MedlineDate")
        )
        resume = " ".join(_texte(a) for a in art.findall(".//Abstract/AbstractText"))
        resultats.append({
            "pmid": pmid,
            "titre": _texte(art.find(".//ArticleTitle")),
            "revue": _texte(art.find(".//Journal/Title")),
            "annee": annee,
            "types": [_texte(t) for t in art.findall(".//PublicationType")],
            "resume": resume[:ABSTRACT_MAX] + ("…" if len(resume) > ABSTRACT_MAX else ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return resultats


DOMAINES_OFFICIELS = [
    "has-sante.fr", "ansm.sante.fr", "base-donnees-publique.medicaments.gouv.fr", "sante.gouv.fr",
    "ema.europa.eu", "fda.gov", "nice.org.uk", "who.int", "cochranelibrary.com",
    "cnge.fr", "sfpt-fr.org", "sfdermato.org", "sfar.org", "e-cancer.fr", "esmo.org", "escardio.org",
]


def web_institutionnel(query, api_key, max_results=6, domaines=None):
    """Recherche web via Tavily, limitée à des domaines officiels. Renvoie titre, url, extrait."""
    r = requests.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": query,
            "include_domains": domaines or DOMAINES_OFFICIELS,
            "max_results": max(1, min(int(max_results or 6), 10)),
            "search_depth": "advanced",
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return [
        {"titre": x.get("title", ""), "url": x.get("url", ""), "resume": (x.get("content", "") or "")[:1200]}
        for x in r.json().get("results", [])
    ]


PRIORITAIRES = ["has-sante.fr", "ansm.sante.fr", "ema.europa.eu", "fda.gov"]


def web_officiel_gratuit(query, max_results=4):
    """Recherche gratuite (DuckDuckGo, sans clé) limitée aux domaines officiels : une requête site: par domaine,
    puis filtrage par code du domaine des résultats."""
    from ddgs import DDGS

    sorties, vus = [], set()
    for dom in PRIORITAIRES:
        try:
            res = DDGS().text(f"{query} site:{dom}", max_results=max_results)
        except Exception:  # limitation de débit : on passe au domaine suivant
            continue
        for x in res:
            url = x.get("href", "")
            hote = re.sub(r"^https?://", "", url).split("/")[0].lower()
            if url in vus or not any(hote == d or hote.endswith("." + d) for d in DOMAINES_OFFICIELS):
                continue
            vus.add(url)
            sorties.append({"titre": x.get("title", ""), "url": url, "resume": (x.get("body", "") or "")[:600]})
    return sorties


def lien_valide(url):
    """Faux seulement si la page n'existe pas (404/410) ou si le serveur est injoignable.
    Un 403/429 (blocage anti-robot) est considéré comme valide."""
    h = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.head(url, allow_redirects=True, timeout=10, headers=h)
        if r.status_code >= 400:
            r = requests.get(url, allow_redirects=True, timeout=10, headers=h, stream=True)
        return r.status_code not in (404, 410) and r.status_code < 500
    except requests.RequestException:
        return False


def web_search(query, max_results=6):
    """Recherche web générale (DuckDuckGo) : ANSM, HAS, EMA, FDA, sociétés savantes."""
    from ddgs import DDGS

    resultats = DDGS().text(query, max_results=max(1, min(int(max_results or 6), 10)))
    return [
        {"titre": r.get("title", ""), "url": r.get("href", ""), "extrait": (r.get("body", "") or "")[:400]}
        for r in resultats
    ]


def clinicaltrials_search(condition=None, intervention=None, max_results=8):
    """Recherche d'essais cliniques (ClinicalTrials.gov) par pathologie et/ou médicament."""
    if not condition and not intervention:
        return []
    params = {"pageSize": max(1, min(int(max_results or 8), 15)), "format": "json"}
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    r = requests.get(CTGOV, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    resultats = []
    for s in r.json().get("studies", []):
        p = s.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        statut = p.get("statusModule", {})
        design = p.get("designModule", {})
        nct = ident.get("nctId", "")
        resultats.append({
            "nct": nct,
            "titre": ident.get("briefTitle", ""),
            "statut": statut.get("overallStatus", ""),
            "phases": design.get("phases", []),
            "conditions": p.get("conditionsModule", {}).get("conditions", []),
            "resume": (p.get("descriptionModule", {}).get("briefSummary", "") or "")[:ABSTRACT_MAX],
            "resultats_publies": bool(s.get("hasResults")),
            "url": f"https://clinicaltrials.gov/study/{nct}",
        })
    return resultats
