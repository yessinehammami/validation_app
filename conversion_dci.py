import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox
from common import load_data, suggestions

df, file_time = load_data()
labels = sorted(df["label"].dropna().unique())

st.title("Conversion rapide en DCI")
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


st_searchbox(
    suggest,
    key="sb_specialite",
    default_options=suggest(""),
    placeholder="Tapez une spécialité...",
    clear_on_submit=True,
    submit_function=ajouter,
)

st.divider()


def dci_de(label):
    dcis = sorted(df.loc[df["label"] == label, "dci"].dropna().unique())
    return " + ".join(dcis) if dcis else "-"


if st.session_state.ordonnance:
    st.subheader("📋 Ordonnance actuelle")
    entete = st.columns([5, 5, 1])
    entete[0].markdown("**Spécialité**")
    entete[1].markdown("**DCI**")
    for idx, label in enumerate(st.session_state.ordonnance):
        c1, c2, c3 = st.columns([5, 5, 1], vertical_alignment="center")
        c1.write(label)
        c2.write(dci_de(label))
        if c3.button("❌", key=f"remove_{idx}"):
            st.session_state.ordonnance.pop(idx)
            st.rerun()
    st.divider()
