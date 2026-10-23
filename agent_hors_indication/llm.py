"""Étape 4 : le LLM comprend la question (FR ou EN) et propose des requêtes PubMed.

Le LLM ne répond jamais à la question : il ne fait que traduire/préparer la recherche.
Le code ajoute lui-même le filtre hors AMM et appelle PubMed.
"""
import json
import re

from openai import OpenAI

MODELE_DEFAUT = "gpt-4.1-mini"

PROMPT_SYNTHESE = """Tu es un assistant de pharmacie. À partir de SOURCES numérotées (S1, S2...), tu rédiges en \
français une synthèse des usages HORS AMM rapportés, en répondant à la question.
Règles strictes :
- Utilise UNIQUEMENT le texte des sources, jamais tes connaissances générales.
- Chaque phrase factuelle se termine par la ou les sources qui la soutiennent, au format [S1] ou [S1][S3].
- Si une source ne parle pas de la question, ne la cite pas. Si rien n'est exploitable, dis-le simplement.
- N'affirme jamais qu'un usage est hors AMM si la source ne le dit pas : écris alors « usage étudié ».
- Chaque source indique son type (cadre officiel ANSM, méta-analyse, revue systématique, recommandation, essai
  randomisé… cas clinique) et son année. Commence par un éventuel cadre officiel ANSM (CPC, AAC, AAP), avec son
  statut. Puis privilégie les niveaux de preuve les plus élevés et nomme le type d'étude quand tu cites
  (ex : « une méta-analyse de 2021 [S2] »). Si seules des preuves faibles existent (cas cliniques, revues
  narratives), dis-le.
- Ne donne pas de recommandation de prescription. 5 à 10 phrases maximum, en puces si utile.
Ensuite, pour CHAQUE source (S1, S2…), remplis une fiche en termes clairs, en français, d'après le texte de
CETTE source uniquement :
- "indication" : la pathologie et la population traitées (ex : « toux chronique réfractaire, adultes ») ;
- "posologie" : dose, rythme et durée utilisés (ex : « 300 à 1800 mg/j, 10 semaines ») ;
- "resultat" : le résultat principal, chiffré si la source le donne, et les effets indésirables notables.
Si l'information n'est pas dans le texte de la source, écris exactement « Non précisé dans le résumé ».
N'invente ni ne déduis jamais une dose ou un résultat. Une phrase courte par champ.
Réponds UNIQUEMENT par un objet JSON :
{"synthese": "texte avec les [S#]",
 "fiches": [{"source": "S1", "indication": "...", "posologie": "...", "resultat": "..."}]}"""

NON_PRECISE = "Non précisé dans le résumé"

PROMPT = """Tu aides un pharmacien à chercher des usages HORS AMM de médicaments dans PubMed.
La question de l'utilisateur peut être en français ou en anglais.
Réponds UNIQUEMENT par un objet JSON :
{
  "medicament_en": "DCI en anglais, ou null",
  "medicament_fr": "DCI en français (ex : amoxicilline), ou null",
  "pathologie_en": "pathologie en anglais, ou null",
  "requetes": ["UNE seule requête PubMed en anglais"]
}
Règles pour la requête :
- Uniquement le médicament et/ou la pathologie nommés dans la question, avec [tiab] (ex : propranolol[tiab] AND "infantile hemangioma"[tiab]).
- N'ajoute AUCUN autre mot : pas de use, treatment, therapy, efficacy, safety, etc.
- N'ajoute PAS de termes off-label / unlicensed : le programme les ajoute lui-même.
- N'invente aucun médicament : si la question n'en nomme pas, cherche par pathologie."""


def creer_client(api_key):
    return OpenAI(api_key=api_key, timeout=60)


def generer_requetes(client, modele, question):
    """Retourne le dict JSON du LLM (medicament_en, pathologie_en, requetes)."""
    rep = client.chat.completions.create(
        model=modele,
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": question}],
        response_format={"type": "json_object"},  # force une sortie JSON valide
    )
    data = json.loads(rep.choices[0].message.content or "{}")
    # on ne fait pas confiance au format : on garde uniquement des chaînes non vides, une seule requête
    data["requetes"] = [q.strip() for q in data.get("requetes", []) if isinstance(q, str) and q.strip()][:1]
    return data


def synthetiser(client, modele, question, articles):
    """Rédige la synthèse et une fiche par source. Retourne (texte, ids_cités, fiches).

    Les sources sont S1..Sn dans l'ordre de `articles` ; `fiches` associe le numéro de la source (1..n) à
    {"indication", "posologie", "resultat"}.
    """
    if not articles:
        return "", [], {}
    corpus = "\n\n".join(
        f"[S{i}] ({a['source']} · {a.get('type', 'Article')} · {a.get('annee') or 'année inconnue'}) {a['titre']}. {a['resume']}"
        for i, a in enumerate(articles, 1)
    )
    rep = client.chat.completions.create(
        model=modele,
        messages=[
            {"role": "system", "content": PROMPT_SYNTHESE},
            {"role": "user", "content": f"QUESTION : {question}\n\nSOURCES :\n{corpus}"},
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(rep.choices[0].message.content or "{}")
    texte = str(data.get("synthese", "")).strip()
    # contrôle du code : on supprime toute citation vers une source qui n'existe pas
    valides = {f"S{i}" for i in range(1, len(articles) + 1)}
    texte = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valides else "", texte)
    cites = sorted({int(x) for x in re.findall(r"\[S(\d+)\]", texte)})

    # même contrôle pour les fiches : on ne garde que celles d'une source existante, avec des champs texte
    fiches = {}
    for f in data.get("fiches", []) if isinstance(data.get("fiches"), list) else []:
        m = re.fullmatch(r"S(\d+)", str(f.get("source", "")).strip()) if isinstance(f, dict) else None
        if m and 1 <= int(m.group(1)) <= len(articles):
            fiches[int(m.group(1))] = {
                champ: (str(f.get(champ) or "").strip() or NON_PRECISE)[:400]
                for champ in ("indication", "posologie", "resultat")
            }
    return texte, cites, fiches
