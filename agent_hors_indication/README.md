# Agent « Recherche indication hors AMM »

Le pharmacien pose une question ; le code interroge des sources, classe les résultats et le LLM en fait une
synthèse sourcée. **Le LLM ne cherche rien lui-même** : il traduit la question, puis résume ce que le code
lui donne.

Fichiers : `recherche_hors_amm.py` (page), `llm.py` (appels au LLM), `sources.py` (recherches).

---

## 1. La question est transformée en « plan » de recherche

L'utilisateur saisit, par exemple :

```
gabapentine toux chronique
```

Le LLM la transforme en ce JSON (et rien d'autre) :

```json
{
  "medicament_en": "gabapentin",
  "medicament_fr": "gabapentine",
  "pathologie_en": "chronic cough",
  "requetes": ["gabapentin[tiab] AND \"chronic cough\"[tiab]"]
}
```

Il n'ajoute aucun mot, aucun filtre et n'invente aucun médicament. Les filtres sont ajoutés ensuite par le code.

## 2. À partir de ce plan, 4 recherches lancées en même temps

| Source | Ce qui est envoyé (construit par le code) | Ce qui est récupéré |
|---|---|---|
| **ANSM** (accès dérogatoire) | recherche du site ansm.sante.fr avec `gabapentine`, puis `gabapentin` | cadres CPC / AAC / AAP de la substance : statut (en cours, arrêté) et indication |
| **PubMed** | `(requête) AND (meta-analysis[pt] OR systematic review[pt] OR guideline[pt] OR practice guideline[pt] OR randomized controlled trial[pt])` | 5 articles : titre, résumé, année, revue, type d'étude |
| **Europe PMC** | `TITLE_ABS:("gabapentin") AND TITLE_ABS:("chronic cough")` + le même filtre de types d'étude | 5 articles, mêmes informations |
| **ClinicalTrials.gov** | médicament = `gabapentin`, pathologie = `chronic cough` | 5 essais : titre, statut (en cours, terminé…), résumé |

En plus : une recherche web (DuckDuckGo) limitée à ansm.sante.fr, has-sante.fr, ema.europa.eu et fda.gov.

- **Complément** : si PubMed ou Europe PMC trouve moins de 5 articles avec le filtre, la recherche est relancée
  sans filtre pour compléter.
- **Panne** : si une source ne répond pas, les autres continuent ; l'erreur est affichée.
- **Liens** : construits par le code à partir des identifiants (PMID, NCT…), jamais par le LLM.

## 3. Le code trie les résultats (sans LLM)

- **Doublons supprimés** : même PMID, même lien ou même titre.
- **Classement par niveau de preuve**, puis du plus récent au plus ancien :

  Cadre ANSM → méta-analyse → revue systématique → recommandation → essai randomisé → essai clinique →
  essai enregistré → étude observationnelle → site officiel → revue → cas clinique

## 4. Le LLM rédige la synthèse

Il reçoit la question et les résultats numérotés, par exemple :

```
[S1] (ANSM · Cadre officiel ANSM) Gabaliquid GeriaSan (Gabapentine). Autorisation d'accès compassionnel…
[S2] (PubMed · Revue systématique · 2016) Treatment of Unexplained Chronic Cough: CHEST Guideline… <résumé>
[S3] (PubMed · Essai randomisé · 2012) Gabapentin for refractory chronic cough… <résumé>
```

Consignes : utiliser **seulement** ces textes, citer la source après chaque phrase (`[S2]`), commencer par
le cadre ANSM s'il y en a un, privilégier les preuves fortes, ne donner aucune recommandation de prescription.

Dans la même réponse, il remplit une **fiche par source** : indication traitée, posologie utilisée, résultat,
tirés du texte de cette source uniquement ; « Non précisé dans le résumé » si l'information n'y est pas.

Le code supprime ensuite toute citation ou fiche qui renvoie à une source inexistante.

## 5. Ce que voit l'utilisateur

1. **🧠 Recherches effectuées** : les requêtes exactes envoyées et le nombre de résultats par source.
2. **🏛️ Cadre officiel ANSM** : les cadres trouvés, ou « aucun cadre trouvé ».
3. **📝 Synthèse** : chaque `[S#]` est un lien vers la source.
4. **📋 Détail par source** : une ligne par source, dans l'ordre du classement.

   | Source | Indication traitée | Posologie utilisée | Résultat |
   |---|---|---|---|
   | **S3 · PubMed**<br>Essai randomisé · 2012 | toux chronique réfractaire, adultes | jusqu'à 1800 mg/j, 10 semaines | amélioration de la qualité de vie liée à la toux… |

   - `S#` est un lien vers la source ; suivent le nom de la source (ANSM, PubMed, Europe PMC,
     ClinicalTrials.gov, Web officiel), le type d'étude et l'année.
   - Le texte passe à la ligne (rien n'est tronqué). Sur un écran étroit, le tableau défile horizontalement.
   - « Non précisé dans le résumé » signale une information absente du résumé, fréquent pour la posologie.
5. **📚 Sources** : type d'étude, année, citée ou non, lien, fiche (indication, posologie, résultat) et résumé
   complet.

---

## À savoir

- La question est envoyée à OpenAI : **ne jamais y mettre de données patient**.
- L'outil ne vérifie pas encore si l'indication figure dans l'AMM (rubrique 4.1 du RCP) ; « aucun cadre
  ANSM » ne veut dire ni « dans l'AMM » ni « hors AMM ».
- La synthèse repose sur les résumés, pas sur le texte intégral des articles.
- Clé OpenAI dans `.streamlit/secrets.toml`, section `[llm]` (`api_key`, `model` facultatif).
