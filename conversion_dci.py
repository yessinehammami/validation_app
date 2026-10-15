import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox
from common import (
    NIVEAU_LIBELLE, analyser_ordonnance, load_data, load_rcp, normalize, specialites_pour_dci,
    suggestions,
)

df, file_time = load_data()
labels = sorted(df["label"].dropna().unique())

st.title("Liste AMMs en Tunisie")
st.caption(f"Données du {pd.Timestamp(file_time, unit='s'):%d/%m/%Y}")

# Initialiser session state pour la liste d'ordonnance
if "ordonnance" not in st.session_state:
    st.session_state.ordonnance = []

# Sélectionner un produit (en haut)
def suggest(term):
    return suggestions(df, "_label", "label", term)

def ajouter(choix):
    if choix and choix not in st.session_state.ordonnance:
        st.session_state.ordonnance.append(choix)


dci_options = df[["dci", "_dci"]].dropna().drop_duplicates("dci").sort_values("dci")


def suggest_dci(term):
    t = normalize(term)
    return dci_options.loc[dci_options["_dci"].str.contains(t, regex=False), "dci"].head(20).tolist()


st.markdown("**Rechercher par DCI** (consultation uniquement, n'ajoute rien à l'ordonnance)")
dci_cherchee = st_searchbox(
    suggest_dci,
    key="sb_dci_recherche",
    default_options=suggest_dci(""),
    placeholder="Tapez une DCI (ex: amoxicilline)...",
)
if dci_cherchee:
    correspondants = (
        df.loc[df["dci"] == dci_cherchee, "label"].dropna().drop_duplicates().sort_values()
    )
    with st.expander(f"{len(correspondants)} spécialité(s) pour {dci_cherchee}", expanded=True):
        for i, nom in enumerate(correspondants):
            c_nom, c_btn = st.columns([12, 1], vertical_alignment="center")
            c_nom.write(nom)
            deja = nom in st.session_state.ordonnance
            c_btn.button(
                "✓" if deja else "➕",
                key=f"add_dci_{i}",
                disabled=deja,
                help="Déjà dans l'ordonnance" if deja else "Ajouter à l'ordonnance",
                on_click=ajouter,
                args=(nom,),
            )

st.markdown("**Ajouter une spécialité à l'ordonnance**")
st_searchbox(
    suggest,
    key="sb_specialite",
    default_options=suggest(""),
    placeholder="Tapez une spécialité...",
    clear_on_submit=True,
    submit_function=ajouter,
)

st.divider()


def valeurs_de(label, colonne):
    vals = sorted(df.loc[df["label"] == label, colonne].dropna().astype(str).str.strip().unique())
    vals = [v for v in vals if v]
    return " + ".join(vals) if vals else "-"


def dci_de(label):
    return valeurs_de(label, "dci")


if st.session_state.ordonnance:
    titre_col, reset_col = st.columns([4, 1], vertical_alignment="center")
    titre_col.subheader("📋 Ordonnance actuelle")
    if reset_col.button("🗑️ Réinitialiser", width="stretch"):
        st.session_state.ordonnance = []
        st.rerun()
    rcp = load_rcp()
    poids = [3, 3, 2, 2, 2, 1]
    entete = st.columns(poids)
    for col, titre in zip(entete, ["Spécialité", "DCI", "Classe", "Sous-classe", "Spécialités RCP"]):
        col.markdown(f"**{titre}**")
    for idx, label in enumerate(st.session_state.ordonnance):
        c1, c2, c3, c4, c5, c6 = st.columns(poids, vertical_alignment="center")
        c1.write(label)
        c2.write(dci_de(label))
        c3.write(valeurs_de(label, "classe"))
        c4.write(valeurs_de(label, "sous_classe"))
        for d in sorted(df.loc[df["label"] == label, "dci"].dropna().unique()):
            n = len(specialites_pour_dci(rcp, d))
            if n and c5.button(f"{n} spécialité(s) →", key=f"rcp_{idx}_{d}"):
                st.session_state.rcp_dci = d
                st.switch_page("donnees_rcp.py")
        if c6.button("❌", key=f"remove_{idx}"):
            st.session_state.ordonnance.pop(idx)
            st.rerun()

    st.divider()
    if st.button("🔍 Détecter une interaction", type="primary", disabled=len(st.session_state.ordonnance) < 2):
        medicaments = {
            label: sorted(df.loc[df["label"] == label, "dci"].dropna().unique())
            for label in st.session_state.ordonnance
        }
        interactions, sans_atc = analyser_ordonnance(rcp, medicaments)

        if interactions:
            st.subheader(f"⚠️ {len(interactions)} interaction(s) détectée(s)")
        else:
            st.success("Aucune interaction trouvée dans le Thésaurus ANSM pour ces médicaments.")
        for r in interactions:
            alerte = st.error if r["niveau"] in ("CI", "ASDEC") else st.warning
            with st.container(border=True):
                alerte(f"**{NIVEAU_LIBELLE.get(r['niveau'], r['niveau'])}** : {r['m1']} ↔ {r['m2']}")
                st.caption(f"Thésaurus : {r['a']} + {r['b']} ({r['niveaux'].replace('|', ', ')})")
                if r["conduite"]:
                    st.write(f"**Conduite à tenir :** {r['conduite']}")
                st.write(f"**Mécanisme :** {r['mecanisme']}")
        if sans_atc:
            st.info("Non analysés (aucun code ATC trouvé) : " + ", ".join(sans_atc))
        st.caption(
            "Analyse indicative basée sur le Thésaurus des interactions médicamenteuses de l'ANSM "
            "(sept. 2023, classes partiellement couvertes). Elle ne remplace pas l'avis d'un "
            "pharmacien ni la lecture du RCP."
        )
