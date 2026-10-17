import streamlit as st

from agent_hors_indication.pipeline_hors_amm import collecter, extraire, generer_requetes, valider

FOURNISSEURS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openai": (None, "gpt-4.1-mini"),
}
STATUTS = {
    "hors_amm_explicite": "🟢 Hors AMM (explicite dans la source)",
    "usage_etudie": "🟡 Usage étudié (statut AMM non précisé)",
}
EXEMPLES = [
    "Quelles indications hors AMM pour le propranolol ?",
    "Médicaments utilisés hors AMM dans la migraine chronique",
    "Metformine hors AMM : quelles indications ?",
]

st.title("🔬 Recherche indication hors AMM")
st.caption(
    "Sources : PubMed, ClinicalTrials.gov et sites officiels (HAS, ANSM, EMA, FDA, sociétés savantes). "
    "Chaque résultat est lié à une source réelle, citée mot pour mot et dont le lien est vérifié."
)

try:
    cfg = dict(st.secrets["llm"])
    cle = cfg["api_key"]
except (KeyError, FileNotFoundError):
    st.warning(
        "Clé API non configurée. Ajoutez dans les secrets :\n\n"
        "```toml\n[llm]\nprovider = \"openai\"  # openai | gemini | groq\napi_key = \"...\"\n"
        "model = \"gpt-4.1-mini\"\n\n[tavily]  # optionnel (sinon DuckDuckGo gratuit sur sites officiels)\n"
        "api_key = \"tvly-...\"\n```"
    )
    st.stop()

cle_tavily = None
try:
    cle_tavily = st.secrets["tavily"]["api_key"]
except (KeyError, FileNotFoundError):
    pass

_url, _modele = FOURNISSEURS.get(cfg.get("provider", "openai"), FOURNISSEURS["openai"])
modele = cfg.get("model", _modele)

from openai import OpenAI, OpenAIError  # noqa: E402


@st.cache_resource
def client_llm(api_key, url):
    return OpenAI(api_key=api_key, base_url=url, timeout=120)


client = client_llm(cle, cfg.get("base_url", _url))

if "historique_hors_amm" not in st.session_state:
    st.session_state.historique_hors_amm = []


def _cell(t):
    return (t or "").replace("|", "/").replace("\n", " ")


def afficher(entree):
    with st.chat_message("user"):
        st.markdown(entree["question"])
    with st.chat_message("assistant"):
        resultats = entree["resultats"]
        if not resultats:
            st.info("Aucun résultat solide trouvé dans les sources vérifiées. Reformulez ou précisez la question.")
        else:
            lignes = ["| Médicament | Indication | Statut | Type d'étude | Résumé | Sources |", "|---|---|---|---|---|---|"]
            for r in resultats:
                liens = ", ".join(f"[{s['label']}]({s['url']})" for s in r["liens"])
                lignes.append(
                    f"| **{_cell(r.get('medicament'))}** | {_cell(r.get('indication'))} | {STATUTS[r['statut']]} "
                    f"| {_cell(r.get('type_etude'))} | {_cell(r.get('resume'))} | {liens} |"
                )
            st.markdown("\n".join(lignes))
            with st.expander("📎 Extraits cités (mot pour mot)"):
                for r in resultats:
                    st.markdown(f"**{r.get('medicament')} - {r.get('indication')}** : « {r.get('citation')} »")
        with st.expander(f"🔎 Recherches effectuées ({len(entree['journal'])}) · {entree['rejetes']} résultat(s) rejeté(s)"):
            for outil, q, n, erreur in entree["journal"]:
                st.write(f"- **{outil}** : `{q}` → {n} source(s)" + (f" ⚠️ {erreur}" if erreur else ""))
        st.caption(
            "Synthèse documentaire indicative, à valider par un professionnel de santé ; "
            "ce n'est pas une recommandation de prescription."
        )


def traiter(question):
    with st.status("Recherche en cours...", expanded=True) as statut:
        st.write("🧠 Préparation des requêtes")
        requetes = generer_requetes(client, modele, question)
        st.write("🔎 Interrogation de PubMed, ClinicalTrials.gov et du web officiel")
        registre, journal = collecter(requetes, cle_tavily)
        st.write(f"📚 {len(registre)} source(s) récupérée(s) · extraction")
        brut = extraire(client, modele, question, registre)
        st.write("✅ Vérification des citations et des liens")
        resultats, rejetes = valider(brut, registre)
        statut.update(label="Recherche terminée", state="complete", expanded=False)
    return {"question": question, "resultats": resultats, "journal": journal, "rejetes": rejetes}


_, col_reset = st.columns([4, 1])
if st.session_state.historique_hors_amm and col_reset.button("🗑️ Effacer", width="stretch"):
    st.session_state.historique_hors_amm = []
    st.rerun()

for e in st.session_state.historique_hors_amm:
    afficher(e)

question = st.chat_input("Indication ou médicament (ex: propranolol, migraine chronique...)")

if not st.session_state.historique_hors_amm and not question:
    st.markdown("**Exemples de questions**")
    for exemple in EXEMPLES:
        if st.button(exemple, key=f"ex_{exemple}"):
            question = exemple

if question:
    try:
        st.session_state.historique_hors_amm.append(traiter(question))
    except OpenAIError as e:
        st.error(f"Erreur du fournisseur LLM : {e}")
        st.stop()
    st.rerun()
