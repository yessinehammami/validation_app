# Validation ordonnances

Application Streamlit (accès par identifiant / mot de passe) d'aide à la validation d'ordonnances :

| Page | Fichier | Rôle |
|---|---|---|
| Liste AMMs en Tunisie | `conversion_dci.py` | spécialités du DPM → DCI, génériques, statut réglementaire, **analyse des interactions** d'une ordonnance (Thésaurus ANSM) |
| RCP (France) | `donnees_rcp.py` | données RCP françaises (BDPM) |
| Nomenclature hospitalière | `nomenclature_hospitaliere.py` | dépôt du PDF de la nomenclature, extraction et affichage du tableau |
| Produits en consignation | `consignation.py` | idem pour les 4 listes de consignation (hospitalier / officinal, visa PCT / DPM) |
| Recherche indication hors AMM | `agent_hors_indication/` | agent LLM + recherche bibliographique (voir § 7) |
| Bibliothèque hors AMM | `bibliotheque_hors_amm.py` | indications hors AMM saisies et partagées par les utilisateurs |

Les sections 1 à 6 expliquent, depuis les données brutes, comment on arrive à l'analyse d'interactions.

---

## 1. Vue d'ensemble

```
DPM (Tunisie) ──► dpm_produit_raw ─────────────┐
                                               │ DCI (texte libre "A+B")
BDPM (France) ──► table_rcp (CIS, substance, DCI) ──► substance (nom → INN + codes ATC)
                                                              │
ATC (BioPortal) + inn_dci (FR→EN) ──► build.db ───────────────┘
                                                              │
Thésaurus ANSM (PDF) ──► thesaurus_interactions ──► thesaurus_atc (nom → préfixes ATC)
                                  ▲                        ▲
                                  │                        └── classes_atc.csv (classes → préfixes, manuel)
                                  └── extraction du PDF (extract_thesaurus.py, une seule fois)
```

**Idée centrale : le code ATC est le pont.** Le DPM, le RCP et le thésaurus n'utilisent pas les mêmes noms
(DCI tunisienne, substance française avec sel, classe thérapeutique…). On donne donc un code ATC à chaque
médicament de l'ordonnance, et des préfixes ATC à chaque entrée du thésaurus (substance ou classe).
Un médicament est concerné par une entrée du thésaurus si son code ATC commence par le préfixe de cette entrée.

---

## 2. Les sources de données

| Source | Contenu | Script | Table / fichier |
|---|---|---|---|
| DPM (Direction de la Pharmacie et du Médicament, Tunisie) | Spécialités tunisiennes, DCI, classe, sous-classe | `update_dpm.py` | `dpm_produit_raw` |
| BDPM (base publique des médicaments, France) | Spécialités, compositions (`CIS_COMPO_bdpm.txt`), RCP | `update_bdpm.py` | `table_rcp` |
| ATC (BioPortal) | Classification ATC (niveau 5 = substance) | `update_dci_atc.py` | `atc` (dans `build.db`) |
| INN/DCI | Correspondance noms français ↔ anglais | `update_dci_atc.py` | `inn_dci` (dans `build.db`) |
| Thésaurus ANSM (sept. 2023, PDF) | Interactions médicamenteuses | `extract_thesaurus.py` (une fois) | `thesaurus_interactions.csv` |

Le thésaurus 2023 est la dernière version publiée ; il n'est plus mis à jour. Son extraction est donc figée.

### Deux bases SQLite

- `cached_data/cached_data.db` : base **de l'application** (versionnée, lue par Streamlit) ;
- `cached_data/build.db` : base **de construction** (tables intermédiaires `atc`, `inn_dci`), non versionnée, régénérée par les scripts.

Tables de `cached_data.db` : `dpm_produit_raw`, `table_rcp`, `thesaurus_interactions` (données brutes),
`substance`, `thesaurus_atc` (dérivées) et `maj_tables` (date de dernière mise à jour de chaque table).

### Table `substance` : référentiel commun DPM ↔ RCP

Le DPM (Tunisie) et la BDPM (France) n'ont aucun code en commun : le seul pont est la **substance**.
`update_dci_atc.py` construit une table unique à partir des DCI de `table_rcp` et des composants de
`dpm_produit_raw` (une association `A + B` est découpée en un nom par composant). Une ligne par (nom, code ATC) :

| Colonne | Contenu |
|---|---|
| `nom` / `nom_normalise` | nom tel que rencontré (sel, hydrate, ordre inversé, orthographe DPM…) / sans accents ni majuscules |
| `id_substance` | identifiant commun : INN anglais si trouvé dans l'ATC, sinon nom normalisé sans sel |
| `inn_en`, `code_atc` | INN anglais retenu et code ATC niveau 5 (vide si pas d'ATC) |
| `statut` | `ok` (ATC trouvé), `sans_atc` (déclaré sans ATC : excipients, acides aminés, homéopathie…) ou `a_verifier` |
| `methode`, `sources` | règle de rapprochement utilisée ; origine du nom (`rcp`, `dpm` ou `dpm+rcp`) |

Deux noms de même `id_substance` désignent la même substance, côté France comme côté Tunisie. L'identifiant est
déterministe : il ne change pas d'une mise à jour à l'autre tant que les alias ne changent pas.

Exemple : toutes les graphies d'une substance et ses codes ATC.

```sql
SELECT nom, sources, code_atc FROM substance WHERE id_substance = 'ibuprofen';
```

Les noms `a_verifier` sont listés dans `cached_data/rapport_substances.csv` (non versionné, triés par nombre de
produits concernés). Pour en corriger un, ajouter une ligne à `alias_manuels.csv` (`dci_bdpm`, `inn_en` ou
`sans_atc`, `commentaire`) puis relancer `update_dci_atc.py`.

### Données de nomenclature hospitalière et de consignation

Les tableaux extraits des PDF sont enregistrés dans `consignation_Nomenclature hospit/documents.db` :
`nomenclature_hospitaliere`, `consignation_hospitalier_dpm`, `consignation_hospitalier_pct`,
`consignation_officinal_dpm` et `consignation_officinal_pct`. Chaque nouveau dépôt remplace les lignes
de la table correspondante. Les PDF restent dans `documents_nomenclature/` et `documents_consignation/`
pour l'affichage et le téléchargement.

---

## 3. Étapes de construction

### Étape 1 – DPM → `dpm_produit_raw`
Téléchargement de la liste des spécialités tunisiennes. La colonne `dci` est un texte libre
(association : `A+B`).

### Étape 2 – BDPM → `table_rcp`
`update_bdpm.py` télécharge les fichiers BDPM et la composition (`CIS_COMPO_bdpm.txt`, traitée en mémoire).
Chaque ligne : code CIS, dénomination, substance (avec sel), **DCI** (substance sans sel), code substance.

### Étape 3 – DCI → ATC : `substance`
`update_dci_atc.py` commence par charger dans `build.db` la classification ATC (on ne garde que les codes de niveau 5,
ex. `B01AA03` warfarine) et la table de traduction français → anglais (ex. *paracétamol* → *paracetamol*), car l'ATC est
en anglais. Il associe ensuite chaque nom de substance (DCI de `table_rcp`, composants du DPM) à un ou plusieurs codes ATC (plusieurs selon la voie
d'administration). Cascade, du plus sûr au moins sûr ; la première correspondance trouvée gagne :

1. règle spéciale : homéopathie / virus → pas d'ATC ;
2. alias manuel (`alias_manuels.csv`) ;
3. nom exact ;
4. traduction FR → EN (`inn_dci`) ;
5. nom sans le sel (chlorhydrate, sodique…) ;
6. variantes (sans « e » final, acide…).

`alias_manuels.csv` permet de forcer un rattachement (`DCI → nom ATC`) ou de déclarer qu'une DCI n'a
pas d'ATC (`sans_atc`: acides aminés, minéraux, excipients, substances absentes de l'ATC…).

### Étape 4 – Extraction du thésaurus (une seule fois)
`extract_thesaurus.py` (nécessite `pymupdf`) lit le PDF en s'appuyant
sur la taille de police et la position des textes :

- substance ou classe **A** : grande police, à gauche ;
- lignes `+ B` : le médicament ou la classe en interaction avec A ;
- niveau et conduite à tenir : colonne de droite ; mécanisme : texte en dessous.

Résultat : `thesaurus_interactions.csv`, **3216 interactions** (616 A distincts, 630 B), conforme au nombre
de lignes `+ B` du PDF. Niveaux :

| Code | Signification |
|---|---|
| CI | Contre-indication |
| ASDEC | Association déconseillée |
| PE | Précaution d'emploi |
| APEC | À prendre en compte |

Quand plusieurs niveaux sont cités, `niveaux` les contient tous (séparés par `|`) et `niveau_max` donne le
plus sévère. Le fichier CSV est versionné : il n'y a pas besoin de refaire l'extraction.

### Étape 5 – Thésaurus → ATC : `thesaurus_atc`
`update_thesaurus.py` charge le CSV dans `thesaurus_interactions` et construit `thesaurus_atc`
(`nom_thesaurus`, `prefixe_atc`, `origine`) :

- **Substances** : le nom est nettoyé (suppression de « (et, par extrapolation, …) », inversion de
  « X (acide) », séparation de « A + B », retrait des parenthèses), puis rapproché des DCI de `table_rcp`,
  et on reprend leurs codes ATC (via `substance`) ;
- **Classes** (ex. « ANTICOAGULANTS ORAUX », « ANTI-INFLAMMATOIRES NON STÉROÏDIENS ») : l'ATC ne contient
  pas la liste des membres d'une classe du thésaurus ; elle est donc définie à la main dans
  `classes_atc.csv` (`nom_thesaurus`, `prefixes_atc` séparés par `|`, `commentaire`). Ex. AINS → `M01A`.

Couverture actuelle : 445 des 644 noms du thésaurus ont au moins un préfixe ATC ; 61 % des interactions
ont leurs deux côtés couverts.

---

## 4. L'analyse d'interactions dans l'application

Page « Liste AMMs en Tunisie » → bouton **🔍 Détecter une interaction** (actif à partir de 2 médicaments).
Code : `analyser_ordonnance()` dans `common.py`.

1. **Médicament → DCI** : la colonne `dci` du DPM (découpée sur `+`).
2. **DCI → substances RCP** : correspondance avec `table_rcp.dci` (égalité si le nom fait moins de 4 caractères,
   sinon « contient »), après normalisation (minuscules, sans accents).
3. **Substances → codes ATC** via `substance`.
4. **Codes ATC → entrées du thésaurus** : une entrée est retenue si un des codes du médicament commence
   par un de ses préfixes dans `thesaurus_atc`.
5. **Pour chaque paire de médicaments** : on cherche dans `thesaurus_interactions` les lignes `(a, b)` dans
   les deux sens (30 paires n'ont qu'une direction dans le PDF).
6. **Affichage** : triées par gravité (CI > ASDEC > PE > APEC), avec les médicaments concernés, les noms du
   thésaurus, la conduite à tenir et le mécanisme. Les médicaments sans ATC sont listés « non analysés ».

Exemple : Sintrom (acénocoumarol, `B01AA07`) + Adofen (ibuprofène, `M01AE01`) → entrée « ANTICOAGULANTS ORAUX »
(préfixe `B01A`) et « ANTI-INFLAMMATOIRES NON STÉROÏDIENS » (`M01A`) → **association déconseillée**.

---

## 5. Limites connues

L'analyse est **indicative** et ne remplace ni un pharmacien ni la lecture du RCP.

- Classes non couvertes : celles sans équivalent ATC (inhibiteurs/inducteurs du CYP3A4, substances donnant
  des torsades de pointes, millepertuis, pamplemousse, alcool, fer, zinc, vaccins vivants atténués…).
- Certaines classes de `classes_atc.csv` sont approximatives et ignorent les exclusions du thésaurus
  (« sauf hydrocortisone », etc.) : faux positifs possibles. **Une relecture par un pharmacien est nécessaire.**
- La voie d'administration et les doses ne sont pas prises en compte (le thésaurus exclut en général les
  voies locales, sauf exceptions).
- L'ATC de BioPortal est incomplet ; des DCI restent sans code (listées comme « non analysés »).
- Seules les interactions du thésaurus sont exploitées (pas la rubrique 4.5 des RCP).

---

## 6. Mise à jour des données

Le workflow GitHub `.github/workflows/update_data.yml` s'exécute chaque mois et lance, dans l'ordre :

```
update_dpm → update_bdpm → update_dci_atc → update_thesaurus
```

`update_thesaurus.py` est relancé car `thesaurus_atc` dépend de `substance`, qui change avec les données.
En local, lancer les scripts depuis le dossier `cached_data` (ils importent `maj_tables`) ; `update_dci_atc.py`
et `update_thesaurus.py` ont besoin de `build.db` (généré par `update_dci_atc.py`).

Les tableaux de nomenclature / consignation (`documents.db`) et la bibliothèque hors AMM
(`bibliotheque/bibliotheque.db`) sont modifiés depuis l'application et ne sont pas concernés par ce workflow.
Sur un hébergement au disque éphémère (Streamlit Community Cloud), ces modifications sont perdues au
redémarrage de l'app : penser à les sauvegarder ou à les committer.

---

## 7. Recherche d'indications hors AMM (agent)

Page « Recherche indication hors AMM » (`agent_hors_indication/`) :

1. `llm.py` : le LLM (OpenAI, modèle `gpt-4.1-mini` par défaut) transforme la question (FR ou EN) en une
   requête PubMed. Il ne répond pas à la question ; le filtre hors AMM est ajouté par le code.
2. `sources.py` : interrogation de PubMed, Europe PMC, ClinicalTrials.gov et de sites officiels
   (ANSM, HAS, EMA, FDA). Les liens sont construits par le code, jamais par le LLM.
3. `llm.py` : synthèse en français, **uniquement** à partir des résumés trouvés, chaque phrase citant ses
   sources `[S#]` ; les citations vers des sources inexistantes sont supprimées.

La page « Bibliothèque des indications hors AMM » permet ensuite d'enregistrer les usages retenus
(DCI, population, indication, spécialité médicale, lien…) dans `bibliotheque/bibliotheque.db`.

---

## 8. Lancer l'application

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

L'application a besoin de `.streamlit/secrets.toml` (en local) ou des *Secrets* de Streamlit Cloud ;
ce fichier n'est jamais versionné :

```toml
[cookie]
name = "val_app_auth"
key = "une-longue-cle-aleatoire"
expiry_days = 7

[credentials.usernames.identifiant]
name = "Nom affiché"
password = "mot de passe haché (bcrypt)"   # voir creer_utilisateur.py

[llm]
api_key = "sk-..."
model = "gpt-4.1-mini"
```

**Reconnexion automatique (mobile)** : la session Streamlit est conservée 6 h après une coupure
(`server.disconnectedSessionTTL` dans `.streamlit/config.toml`) ; au-delà, l'utilisateur est reconnecté par le
cookie signé (`[cookie]`, valable `expiry_days` jours), que `app.py` réécrit à chaque session.

Fichiers principaux : `app.py` (navigation et login), `conversion_dci.py` (page 1 + analyse),
`donnees_rcp.py` (page RCP), `common.py` (chargement des données et logique d'analyse).
