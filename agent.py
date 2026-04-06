import requests
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ============================================================
# CONFIGURATION — Remplis uniquement cette section
# ============================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")  # Ton adresse email

# Sujets à surveiller (tu peux en ajouter/retirer)
TOPICS = [
    "musculoskeletal physiotherapy",
    "chronic pain neuroscience",
    "sport performance rehabilitation",
    "physical therapy outcomes",
]

# ============================================================
# ÉTAPE 1 — Récupérer les articles PubMed (gratuit)
# ============================================================
def fetch_pubmed_articles(topic, max_results=5):
    yesterday = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
    today = datetime.now().strftime("%Y/%m/%d")

    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": f"{topic}[Title/Abstract]",
        "mindate": yesterday,
        "maxdate": today,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    response = requests.get(search_url, params=params)
    ids = response.json().get("esearchresult", {}).get("idlist", [])

    if not ids:
        return []

    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "abstract",
        "retmode": "text",
    }
    fetch_response = requests.get(fetch_url, params=fetch_params)
    return fetch_response.text

# ============================================================
# ÉTAPE 2 — Synthétiser avec Groq (gratuit)
# ============================================================
def synthesize_with_groq(topic, raw_abstracts):
    if not raw_abstracts:
        return f"Aucun article récent trouvé pour : {topic}"

    prompt = f"""Tu es un assistant scientifique spécialisé en kinésithérapie.
Voici des résumés d'articles scientifiques récents sur le thème : "{topic}"

{raw_abstracts[:6000]}

Fais une synthèse claire et concise en français (max 250 mots) qui :
1. Résume les principales découvertes
2. Indique ce qui est cliniquement pertinent pour un kinésithérapeute
3. Mentionne les auteurs/études clés si possible

Réponds directement sans introduction."""

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama3-70b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 500,
        },
    )
    return response.json()["choices"][0]["message"]["content"]

# ============================================================
# ÉTAPE 3 — Construire et envoyer l'email HTML
# ============================================================
def build_html_email(summaries):
    today_str = datetime.now().strftime("%d %B %Y")
    topic_labels = {
        "musculoskeletal physiotherapy": "🦴 Pathologies musculo-squelettiques",
        "chronic pain neuroscience": "🧠 Neurosciences & Douleur",
        "sport performance rehabilitation": "⚡ Performance sportive",
        "physical therapy outcomes": "🔄 Rééducation & Réhabilitation",
    }

    sections_html = ""
    for topic, summary in summaries.items():
        label = topic_labels.get(topic, topic)
        sections_html += f"""
        <div style="margin-bottom:32px; padding:20px; background:#f9f9f9; border-left:4px solid #2b7a78; border-radius:4px;">
            <h2 style="color:#2b7a78; margin-top:0;">{label}</h2>
            <p style="line-height:1.7; color:#333;">{summary.replace(chr(10), '<br>')}</p>
        </div>
        """

    html = f"""
    <html><body style="font-family: Georgia, serif; max-width:700px; margin:auto; padding:24px; color:#222;">
        <div style="background:#2b7a78; color:white; padding:24px; border-radius:8px; margin-bottom:32px;">
            <h1 style="margin:0; font-size:22px;">📚 Veille Scientifique Kiné</h1>
            <p style="margin:8px 0 0; opacity:0.85;">{today_str} — Dernières publications PubMed</p>
        </div>
        {sections_html}
        <p style="font-size:12px; color:#999; text-align:center; margin-top:40px;">
            Généré automatiquement via PubMed + Groq LLaMA 3 · Sources : ncbi.nlm.nih.gov
        </p>
    </body></html>
    """
    return html

def send_email(html_content):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 Veille Kiné du {datetime.now().strftime('%d/%m/%Y')}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    print("✅ Email envoyé avec succès !")

# ============================================================
# MAIN
# ============================================================
def main():
    print("🔍 Recherche des articles PubMed...")
    summaries = {}
    for topic in TOPICS:
        print(f"  → {topic}")
        abstracts = fetch_pubmed_articles(topic)
        summary = synthesize_with_groq(topic, abstracts)
        summaries[topic] = summary

    print("📧 Envoi de l'email...")
    html = build_html_email(summaries)
    send_email(html)

if __name__ == "__main__":
    main()
