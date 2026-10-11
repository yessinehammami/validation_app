import time

import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

BASE = "https://medicaments-api.giygas.dev"

st.title("Données RCP")
st.caption("Source : API Médicaments FR (BDPM / ANSM)")


RATE = 3  # jetons rechargés par seconde


@st.cache_resource
def call_log():
    return []


@st.cache_data(ttl=3600, show_spinner=False)
def api_get(path, **params):
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    remaining = r.headers.get("x-ratelimit-remaining")
    if remaining is not None:
        log = call_log()
        now = time.time()
        remaining = int(remaining)
        cost = None
        if log:
            prev = log[-1]
            cost = round(prev["restant"] + (now - prev["t"]) * RATE - remaining)
        log.append({"t": now, "appel": path, "restant": remaining, "coût estimé": cost})
    r.raise_for_status()
    return r.json()


def show_quota():
    log = call_log()
    with st.sidebar:
        st.subheader("Quota API")
        if not log:
            st.caption("Aucun appel réel effectué (réponses en cache ou pas encore d'appel).")
            return
        st.metric("Jetons restants", f"{log[-1]['restant']} / 1000")
        st.caption("Coût estimé = baisse du quota, recharge (3/s) incluse. Les réponses en cache ne coûtent rien.")
        st.dataframe(
            [{k: v for k, v in e.items() if k != "t"} for e in reversed(log[-15:])],
            hide_index=True,
        )


def suggest(term):
    if not term or len(term) < 3:
        return []
    try:
        meds = api_get("/v1/medicaments", search=term)
    except requests.RequestException:
        return []
    return [(m["elementPharmaceutique"], m["cis"]) for m in meds[:20]]


cis = st_searchbox(
    suggest,
    key="sb_rcp",
    placeholder="Tapez un médicament (ex: doliprane 500)",
)

if not cis:
    show_quota()
    st.info("Tapez au moins 3 caractères, puis choisissez un médicament.")
    st.stop()

try:
    med = api_get(f"/v1/medicaments/{cis}")
    rcp = api_get(f"/v1/medicaments/{cis}/rcp")
except requests.RequestException as e:
    show_quota()
    st.error(f"Erreur lors de l'appel à l'API : {e}")
    st.stop()

show_quota()
st.subheader(med["elementPharmaceutique"])
col1, col2, col3 = st.columns(3)
col1.write(f"**Forme :** {med.get('formePharmaceutique') or '-'}")
col2.write(f"**Titulaire :** {med.get('titulaire') or '-'}")
col3.write(f"**Statut :** {med.get('statusAutorisation') or '-'}")

substances = [
    f"{c['denominationSubstance']} ({c['dosage']})"
    for c in med.get("composition") or []
    if c.get("natureComposant") == "SA"
]
st.write("**Substances actives :** " + (", ".join(substances) or "-"))

st.divider()
st.caption(f"RCP mis à jour le {rcp.get('miseAJour', '-')} - {rcp.get('source', '')}")
for section in rcp.get("sections", []):
    with st.expander(section["titre"], expanded=section["id"] == "4.1"):
        st.html(section["contenu"])

with st.expander("Réponse JSON brute (test)"):
    st.json({"medicament": med, "rcp": rcp}, expanded=False)
