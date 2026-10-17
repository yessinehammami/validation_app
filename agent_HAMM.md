# Page « 🔬 Recherche indication hors AMM » : fonctionnement détaillé

## 1. Objectif

Aider le pharmacien à retrouver rapidement, pour un médicament ou une pathologie, les **usages hors AMM**
décrits dans la littérature et les sources officielles, **sans risque d'invention** :
chaque résultat affiché est relié à une source réelle, citée mot pour mot, avec un lien vérifié.

Ce n'est **pas** un chatbot libre : c'est un pipeline en 4 étapes où le modèle de langage (LLM) est
encadré par du code qui contrôle ses réponses.

## 2. Fichiers

| Fichier | Rôle |
|---|---|
| `agent_hors_indication/recherche_hors_amm.py` | Interface Streamlit (page), lecture des secrets, affichage |
| `agent_hors_indication/pipeline_hors_amm.py` | Les 4 étapes : requêtes, collecte, extraction, validation |
| `agent_hors_indication/sources_hors_amm.py` | Accès aux sources : PubMed, ClinicalTrials.gov, web officiel, test des liens |
| `.streamlit/secrets.toml` (local) ou *Settings → Secrets* (Streamlit Cloud) | Clé API du LLM |

(`hors_amm.py` à la racine est l'ancien chatbot, inutilisé.)

## 3. Configuration

Bloc `[llm]` dans les secrets :

```toml
[llm]
provider = "openai"      # openai | gemini | groq
api_key  = "..."
model    = "gpt-5-mini"  # facultatif (défauts : gpt-4.1-mini / gemini-2.5-flash / llama-3.3-70b-versatile)
```

- `[tavily] api_key = "tvly-..."` est **facultatif** : s'il est présent, Tavily sert pour la recherche web
  officielle ; sinon DuckDuckGo (gratuit) est utilisé.
- Sans bloc `[llm]`, la page affiche « Clé API non configurée ».
- Le fichier `secrets.toml` local n'est jamais envoyé sur GitHub : sur Streamlit Cloud, les secrets se
  saisissent dans *Settings → Secrets*.

## 4. Le pipeline, étape par étape

L'utilisateur saisit une question (ex. « Quelles indications hors AMM pour le propranolol ? »).

### Étape 1 : Préparation des requêtes (LLM)
Le LLM transforme la question en un JSON contenant :
- `indication_en` / `medicament_en` : pathologie et DCI en anglais ;
- 2 à 4 requêtes **PubMed** (termes `off-label`, `unlicensed`, `repurposing`, `systematic review`...) ;
- 2 à 3 requêtes **web** ciblant HAS, ANSM, EMA, FDA, sociétés savantes, RTU, CPC.

### Étape 2 : Collecte (code, en parallèle)
Le code lance les recherches simultanément (6 threads). Un échec d'une source ne bloque pas les autres.

| Source | Contenu récupéré | Limite |
|---|---|---|
| **PubMed** (API NCBI) | titre, types de publication, résumé, PMID | 8 articles par requête |
| **ClinicalTrials.gov** | titre, conditions, résumé, numéro NCT | 8 essais |
| **Web officiel** | titre, extrait | HAS, ANSM, EMA, FDA (une requête `site:` par domaine via DuckDuckGo, puis filtre sur le domaine ; Tavily si configuré) |

Les résultats sont dédoublonnés par URL et numérotés **S1, S2, S3...** dans un **registre** (40 sources
maximum). Le registre est la seule base de vérité de la suite.

### Étape 3 : Extraction (LLM)
Le LLM reçoit la question et le texte des sources numérotées. Il a l'interdiction d'utiliser ses
connaissances générales. Il renvoie un JSON : pour chaque usage trouvé, le médicament, l'indication,
le **statut**, le type d'étude, un résumé, une **citation copiée mot pour mot** et l'identifiant de
la source (ex. `S3`).

Statuts possibles :
- `hors_amm_explicite` : la source dit explicitement hors AMM / off-label / non autorisé ;
- `usage_etudie` : la source étudie l'usage sans préciser son statut d'AMM ;
- `amm` : l'indication est autorisée (ce résultat est **écarté** à l'étape suivante).

### Étape 4 : Validation (code)
Aucun résultat n'est affiché sans passer ces contrôles :
1. la source citée **existe** dans le registre ;
2. le statut est `hors_amm_explicite` ou `usage_etudie` (jamais `amm`) ;
3. la **citation** (≥ 15 caractères) est **retrouvée telle quelle** dans le texte de la source
   (comparaison normalisée : casse, ponctuation, espaces) ;
4. pour les sources web, le **lien est testé** : rejeté si 404, 410, 5xx ou injoignable (403 et 429 sont
   tolérés car certains sites bloquent les robots) ;
5. les **liens sont construits par le code** (PMID, NCT, URL du registre) : le LLM ne produit jamais de lien.

Les résultats sont triés : d'abord « Hors AMM explicite », puis « Usage étudié », puis par médicament.
Le nombre de résultats rejetés est affiché.

## 5. Ce que voit l'utilisateur

- Une zone de progression (préparation, interrogation, extraction, vérification).
- Un tableau : Médicament, Indication, Statut (🟢 / 🟡), Type d'étude, Résumé, Sources (liens cliquables).
- Un volet **« Extraits cités (mot pour mot) »** pour contrôler chaque affirmation.
- Un volet **« Recherches effectuées »** : requêtes envoyées à chaque outil, nombre de sources, erreurs éventuelles,
  nombre de résultats rejetés.
- Un historique de la session (bouton « Effacer ») et trois exemples de questions au démarrage.
- Un avertissement : synthèse documentaire indicative, à valider par un professionnel de santé.

## 6. Garanties et limites

**Garanties**
- Pas de lien inventé (construits par le code).
- Pas de citation inventée (vérifiée dans la source).
- Pas de résultat « AMM » présenté comme hors AMM.
- Traçabilité complète des recherches.

**Limites**
- Le LLM ne lit que les **résumés/extraits** (pas les articles complets) : un usage décrit seulement dans le
  texte intégral ne sera pas vu.
- DuckDuckGo peut limiter le débit (le domaine en échec est signalé dans le journal) ; ses extraits sont courts (600 caractères).
- Les résultats HAS portent surtout sur l'AMM (avis de la Commission de la transparence) ; l'ANSM (accès
  dérogatoire, RTU) est plus pertinent.
- Le statut « hors AMM » vient uniquement du texte de la source, jamais d'une vérification dans la base de
  l'AMM : il faut le confirmer.
- Le RCP n'est volontairement pas consulté (il décrit l'AMM, pas le hors AMM).
- Chaque recherche appelle le LLM deux fois (requêtes + extraction) : elle a un coût API faible mais non nul.
- La qualité dépend du modèle choisi et de la formulation de la question.

## 7. Lien avec la Bibliothèque

Un résultat utile peut être reporté manuellement dans la page « 📚 Bibliothèque des indications hors AMM »
(DCI, indication, dosage, population, lien vers la source) pour constituer l'historique partagé de l'équipe.
