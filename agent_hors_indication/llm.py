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
- Ne donne pas de recommandation de prescription. 5 à 10 phrases maximum, en puces si utile.
Réponds UNIQUEMENT par un objet JSON : {"synthese": "texte avec les [S#]"}"""

PROMPT = """Tu aides un pharmacien à chercher des usages HORS AMM de médicaments dans PubMed.
La question de l'utilisateur peut être en français ou en anglais.
Réponds UNIQUEMENT par un objet JSON :
{
  "medicament_en": "DCI en anglais, ou null",
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
    # on ne fait pas confiance au format : on garde uniquement des chaînes non vides, 3 au maximum
    data["requetes"] = [q.strip() for q in data.get("requetes", []) if isinstance(q, str) and q.strip()][:1]
    return data


def synthetiser(client, modele, question, articles):
    """Rédige la synthèse. Retourne (texte, ids_cités). Les sources sont S1..Sn dans l'ordre de `articles`."""
    if not articles:
        return "", []
    corpus = "\n\n".join(f"[S{i}] ({a['source']}) {a['titre']}. {a['resume']}" for i, a in enumerate(articles, 1))
    rep = client.chat.completions.create(
        model=modele,
        messages=[
            {"role": "system", "content": PROMPT_SYNTHESE},
            {"role": "user", "content": f"QUESTION : {question}\n\nSOURCES :\n{corpus}"},
        ],
        response_format={"type": "json_object"},
    )
    texte = str(json.loads(rep.choices[0].message.content or "{}").get("synthese", "")).strip()
    # contrôle du code : on supprime toute citation vers une source qui n'existe pas
    valides = {f"S{i}" for i in range(1, len(articles) + 1)}
    texte = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valides else "", texte)
    cites = sorted({int(x) for x in re.findall(r"\[S(\d+)\]", texte)})
    return texte, cites
