import pandas as pd
import streamlit as st
from streamlit_searchbox import st_searchbox
from common import load_data, suggestions

df, file_time = load_data()

st.title("Recherche par DCI")
st.caption(f"Données du {pd.Timestamp(file_time, unit='s'):%d/%m/%Y} - {len(df)} produits")


def suggest(term):
    return suggestions(df, "_dci", "dci", term)


selected = st_searchbox(
    suggest,
    key="sb_dci",
    default_options=suggest(""),
    placeholder="Tapez une DCI (ex: parac...)",
)

if selected:
    view = df[df["dci"] == selected].reset_index(drop=True)
    st.write(f"{len(view)} résultat(s)")

    row = view.iloc[0]
    st.write("**Classe:** " + str(row["classe"]))
    st.write("**Sous-classe:** " + str(row["sous_classe"]))

    if st.button("📋 Afficher Indications", key="indications_0"):
        st.write("**Indications:**")
        if pd.notna(row.get("indications")):
            st.info(row["indications"])
        else:
            st.warning("Aucune indication disponible")
else:
    st.info("Commencez à taper, puis choisissez une suggestion.")
