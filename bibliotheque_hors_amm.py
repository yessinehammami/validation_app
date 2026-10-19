import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from common import normalize

# base séparée de cached_data.db, qui est régénérée à chaque mise à jour des données
DB_BIBLIO = Path(__file__).parent / "bibliotheque" / "bibliotheque.db"

POPULATIONS = ["Adulte", "Pédiatrique", "Nouveau-né", "Sujet âgé", "Femme enceinte"]
SPECIALITES_MED = [
    "Cardiologie", "Pneumologie", "Neurologie", "Psychiatrie", "Gastro-entérologie", "Néphrologie",
    "Endocrinologie", "Infectiologie", "Oncologie", "Hématologie", "Dermatologie", "Rhumatologie",
    "Pédiatrie", "Gynécologie-obstétrique", "Ophtalmologie", "ORL", "Urologie", "Anesthésie-réanimation",
    "Douleur / soins palliatifs", "Autre",
]
COLONNES = {
    "dci": "DCI", "specialite": "Spécialité", "dosage": "Dosage", "population": "Population cible",
    "indication": "Indication", "specialite_med": "Spécialité médicale", "commentaire": "Commentaire",
    "lien": "Lien", "auteur": "Ajouté par", "date": "Date",
}


def connexion():
    DB_BIBLIO.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_BIBLIO)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS indications_hors_amm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dci TEXT NOT NULL, specialite TEXT, dosage TEXT, population TEXT,
            indication TEXT NOT NULL, specialite_med TEXT, commentaire TEXT, lien TEXT,
            auteur TEXT, date TEXT)"""
    )
    return conn


def charger():
    conn = connexion()
    try:
        return pd.read_sql("SELECT * FROM indications_hors_amm ORDER BY id DESC", conn).fillna("")
    finally:
        conn.close()


def executer(sql, params):
    conn = connexion()
    try:
        with conn:
            conn.execute(sql, params)
    finally:
        conn.close()


def utilisateur():
    return st.session_state.get("name") or st.session_state.get("username") or "inconnu"


# largeur relative des colonnes ; la dernière est celle des boutons Modifier / Supprimer
LARGEURS = [9, 9, 12, 9, 13, 9, 15, 6, 8, 8, 8]
CELLULE = "font-size:1rem; line-height:1.5; overflow-wrap:break-word;"


def cellule(texte, gras=False):
    st.html(f'<div style="{CELLULE}{"font-weight:700;" if gras else ""}">{escape(str(texte))}</div>')


def champs_indication(prefixe, init=None):
    """Champs du formulaire (ajout ou modification). Retourne un dict de valeurs."""
    init = init or {}
    c1, c2 = st.columns(2)
    dci = c1.text_input("DCI *", value=init.get("dci", ""), key=f"{prefixe}_dci", placeholder="ex : propranolol")
    specialite = c2.text_input("Spécialité (nom commercial)", value=init.get("specialite", ""), key=f"{prefixe}_spe", placeholder="ex : AVLOCARDYL")
    c3, c4 = st.columns(2)
    dosage = c3.text_input("Dosage / posologie", value=init.get("dosage", ""), key=f"{prefixe}_dos", placeholder="ex : 2 mg/kg/j en 2 prises")
    population = c4.multiselect(
        "Population cible", POPULATIONS, key=f"{prefixe}_pop",
        default=[p for p in init.get("population", "").split(", ") if p in POPULATIONS],
    )
    indication = st.text_input("Indication hors AMM *", value=init.get("indication", ""), key=f"{prefixe}_ind", placeholder="ex : hémangiome infantile")
    sm = init.get("specialite_med") or None
    specialite_med = st.selectbox(
        "Spécialité médicale", SPECIALITES_MED, index=SPECIALITES_MED.index(sm) if sm in SPECIALITES_MED else None,
        placeholder="Choisir...", key=f"{prefixe}_sm",
    )
    commentaire = st.text_area("Commentaire", value=init.get("commentaire", ""), key=f"{prefixe}_com", placeholder="Contexte, niveau de preuve, précautions...")
    lien = st.text_input("Lien vers l'étude ou le document", value=init.get("lien", ""), key=f"{prefixe}_lien", placeholder="https://...")
    return {
        "dci": dci.strip().upper(), "specialite": specialite.strip().upper(), "dosage": dosage.strip(),
        "population": ", ".join(population), "indication": indication.strip(),
        "specialite_med": specialite_med or "", "commentaire": commentaire.strip(), "lien": lien.strip(),
    }


def erreur_champs(v):
    if not v["dci"] or not v["indication"]:
        return "La DCI et l'indication sont obligatoires."
    if v["lien"] and not v["lien"].lower().startswith(("http://", "https://")):
        return "Le lien doit commencer par http:// ou https://"
    return None


@st.dialog("Modifier l'indication", width="large")
def dialogue_modifier(entree):
    v = champs_indication(f"mod{entree['id']}", entree)
    if st.button("💾 Enregistrer les modifications", type="primary", width="stretch"):
        if (err := erreur_champs(v)):
            st.error(err)
        else:
            executer(
                "UPDATE indications_hors_amm SET dci=?, specialite=?, dosage=?, population=?, indication=?, "
                "specialite_med=?, commentaire=?, lien=? WHERE id=? AND auteur=?",
                (v["dci"], v["specialite"], v["dosage"], v["population"], v["indication"], v["specialite_med"],
                 v["commentaire"], v["lien"], int(entree["id"]), utilisateur()),
            )
            st.rerun()


@st.dialog("Supprimer l'indication")
def dialogue_supprimer(entree):
    st.write(f"Supprimer **{entree['dci']}** - {entree['indication']} ?")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Supprimer", type="primary", width="stretch"):
        executer("DELETE FROM indications_hors_amm WHERE id = ? AND auteur = ?", (int(entree["id"]), utilisateur()))
        st.rerun()
    if c2.button("Annuler", width="stretch"):
        st.rerun()


def afficher_tableau(lignes):
    entetes = [c for k, c in COLONNES.items()] + [""]
    cols = st.columns(LARGEURS)
    for col, nom in zip(cols, entetes):
        with col:
            cellule(nom, gras=True)
    st.divider()
    moi = utilisateur()
    for r in lignes.to_dict("records"):
        cols = st.columns(LARGEURS)
        for col, cle in zip(cols, COLONNES):
            with col:
                if cle == "lien" and r["lien"]:
                    st.html(f'<a style="font-size:1rem" href="{escape(r["lien"], quote=True)}" target="_blank" rel="noopener noreferrer">🔗 Ouvrir</a>')
                else:
                    cellule(r[cle])
        with cols[-1]:
            # modification et suppression réservées à l'auteur de l'entrée
            if r["auteur"] == moi:
                b1, b2 = st.columns(2)
                if b1.button("", icon=":material/edit:", key=f"edit_{r['id']}", help="Modifier"):
                    dialogue_modifier(r)
                if b2.button("", icon=":material/delete:", key=f"del_{r['id']}", help="Supprimer"):
                    dialogue_supprimer(r)
        st.divider()


st.title("📚 Bibliothèque des indications hors AMM")
st.caption(
    "Historique partagé des indications hors AMM rencontrées lors de la validation des ordonnances : "
    "consultez avant de valider, et enrichissez la bibliothèque."
)

tab_consulter, tab_ajouter = st.tabs(["🔎 Consulter", "➕ Ajouter une indication"])

with tab_ajouter:
    with st.form("form_biblio", clear_on_submit=True):
        v = champs_indication("ajout")
        envoye = st.form_submit_button("💾 Ajouter à la bibliothèque", type="primary")

    if envoye:
        if (err := erreur_champs(v)):
            st.error(err)
        else:
            executer(
                "INSERT INTO indications_hors_amm (dci, specialite, dosage, population, indication, "
                "specialite_med, commentaire, lien, auteur, date) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (v["dci"], v["specialite"], v["dosage"], v["population"], v["indication"], v["specialite_med"],
                 v["commentaire"], v["lien"], utilisateur(), datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
            st.success("Indication ajoutée à la bibliothèque.")

df = charger()

with tab_consulter:
    if df.empty:
        st.info("La bibliothèque est vide. Ajoutez la première indication dans l'onglet « Ajouter ».")
    else:
        c1, c2 = st.columns(2)
        noms = sorted({n for n in list(df["dci"]) + list(df["specialite"]) if n})
        f_dci = c1.selectbox("DCI ou spécialité", noms, index=None, placeholder="Tapez pour filtrer la liste...")
        f_ind = c2.text_input("Indication contient", placeholder="ex : migraine")
        c3, c4 = st.columns(2)
        f_spe = c3.multiselect("Spécialité médicale", sorted(s for s in df["specialite_med"].unique() if s))
        f_pop = c4.multiselect("Population cible", POPULATIONS, key="filtre_pop")

        masque = pd.Series(True, index=df.index)
        if f_dci:
            masque &= (df["dci"] == f_dci) | (df["specialite"] == f_dci)
        if f_ind:
            masque &= df["indication"].map(normalize).str.contains(normalize(f_ind), regex=False)
        if f_spe:
            masque &= df["specialite_med"].isin(f_spe)
        if f_pop:
            masque &= df["population"].map(lambda p: any(x in p.split(", ") for x in f_pop))

        st.caption(f"{int(masque.sum())} indication(s) sur {len(df)}")
        afficher_tableau(df[masque])''''''