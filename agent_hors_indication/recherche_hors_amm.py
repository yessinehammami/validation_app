import re
from html import escape

import streamlit as st

from agent_hors_indication.llm import MODELE_DEFAUT, creer_client, generer_requetes, synthetiser
from agent_hors_indication.sources import collecter

NOMBRE_PAR_SOURCE = 5

st.title("🔬 Recherche indication hors AMM")
st.caption("Sources : PubMed, Europe PMC, ClinicalTrials.gov et sites officiels (ANSM, HAS, EMA, FDA). Posez votre question en français ou en anglais.")

try:
    cfg = dict(st.secrets["llm"])
    cle = cfg["api_key"]
except (KeyError, FileNotFoundError):
    st.warning('Clé API non configurée. Ajoutez dans les secrets :\n\n```toml\n[llm]\napi_key = "sk-..."\nmodel = "gpt-4.1-mini"\n```')
    st.stop()
modele = cfg.get("model", MODELE_DEFAUT)


@st.cache_resource
def client_llm(api_key):
    return creer_client(api_key)


question = st.text_input("Votre question", placeholder="ex : propranolol hors AMM, ou : traitement de la migraine chronique")

if st.button("🔎 Rechercher", type="primary") and question.strip():
    try:
        with st.spinner("Le LLM prépare les requêtes..."):
            plan = generer_requetes(client_llm(cle), modele, question.strip())
        with st.spinner("Interrogation de PubMed, Europe PMC, ClinicalTrials.gov et des sites officiels..."):
            articles, journal = collecter(plan, NOMBRE_PAR_SOURCE)
        with st.spinner("Le LLM rédige la synthèse..."):
            synthese, cites = synthetiser(client_llm(cle), modele, question.strip(), articles)
        # on garde tout en session pour survivre aux rechargements de la page
        st.session_state["pubmed"] = {
            "question": question.strip(), "plan": plan, "articles": articles, "journal": journal,
            "synthese": synthese, "cites": cites,
        }
    except Exception as e:
        st.error(f"Erreur : {e}")

resultat = st.session_state.get("pubmed")


def synthese_html(texte, articles):
    """Transforme chaque [S#] en lien cliquable vers la source (gras, souligné, orange)."""
    def lien(m):
        i = int(m.group(1))
        if not 1 <= i <= len(articles):
            return ""
        url = escape(articles[i - 1]["url"], quote=True)
        return (f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                f'style="font-weight:700;text-decoration:underline;color:#f97316;">[S{i}]</a>')

    # le texte du LLM est échappé avant d'insérer notre HTML
    return re.sub(r"\[S(\d+)\]", lien, escape(texte, quote=False))

if resultat:
    plan = resultat["plan"]
    with st.expander("🧠 Recherches effectuées", expanded=False):
        st.write(f"**Médicament** : {plan.get('medicament_en') or '-'}  ·  **Pathologie** : {plan.get('pathologie_en') or '-'}")
        for j in resultat["journal"]:
            st.write(f"**{j['outil']}** : {j['trouves']} trouvé(s), {j['nouveaux']} nouveau(x)" + (f" ⚠️ {j['erreur']}" if j["erreur"] else ""))
            st.code(j["requete"], language=None)
        st.caption("Le filtre hors AMM est ajouté par le programme, pas par le LLM.")
    if not resultat["articles"]:
        st.info("Aucun article trouvé. Reformulez la question.")
    else:
        st.subheader("📝 Synthèse")
        st.markdown(synthese_html(resultat["synthese"], resultat["articles"]) or "_Le LLM n'a rien pu synthétiser._", unsafe_allow_html=True)
        st.caption("Synthèse générée à partir des résumés ci-dessous ; à vérifier dans les sources.")
        st.subheader("📚 Sources")
    for i, a in enumerate(resultat["articles"], 1):
        cite = "✅ citée" if i in resultat["cites"] else "non citée"
        with st.expander(f"[S{i}] {a['titre'] or a['url']} · :orange[**{a['source']}**] · {cite}"):
            st.markdown(
                f'<span style="font-weight:700;text-decoration:underline;color:#f97316;">{escape(a["source"])}</span>',
                unsafe_allow_html=True,
            )
            st.markdown(f"[{a['url']}]({a['url']})")
            st.write(a["resume"] or "_Pas de résumé disponible._")
