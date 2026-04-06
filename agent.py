import requests
import smtplib
import os
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ============================================================
# CONFIGURATION
# ============================================================
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL")

# Sujets à surveiller
TOPICS = [
    "musculoskeletal physiotherapy",
    "chronic pain neuroscience",
    "sport performance rehabilitation",
    "physical therapy outcomes",
]

# Journaux reconnus en kiné / médecine du sport / douleur
TRUSTED_JOURNALS = [
    "journal of orthopaedic and sports physical therapy",
    "jospt",
    "british journal of sports medicine",
    "bjsm",
    "physical therapy",
    "journal of physiotherapy",
    "manual therapy",
    "musculoskeletal science and practice",
    "pain",
    "the journal of pain",
    "european journal of pain",
    "sports medicine",
    "american journal of sports medicine",
    "journal of sport rehabilitation",
    "clinical journal of sport medicine",
    "scandinavian journal of medicine and science in sports",
    "journal of strength and conditioning research",
    "international journal of sports physical therapy",
    "physiotherapy",
    "physiotherapy theory and practice",
    "archives of physical medicine and rehabilitation",
    "disability and rehabilitation",
    "spine",
    "european spine journal",
    "knee surgery sports traumatology arthroscopy",
    "journal of athletic training",
    "neuroscience",
    "nature neuroscience",
]

# ============================================================
# ÉTAPE 1 — Récupérer les IDs PubMed
# ============================================================
def fetch_pubmed_ids(topic, max_results=20):
    yesterday = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
    today = datetime.now().strftime("%Y/%m/%d")

    params = {
        "db": "pubmed",
        "term": f"{topic}[Title/Abstract]",
        "mindate": yesterday,
        "maxdate": today,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params=params
    )
    return response.json().get("esearchresult", {}).get("idlist", [])

# ============================================================
# ÉTAPE 2 — Récupérer les détails des articles (XML)
# ============================================================
def fetch_article_details(ids):
    if not ids:
        return []

    response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={
            "db": "pubmed",
            "id": ",".join(ids),
            "rettype": "xml",
            "retmode": "xml",
        }
    )

    articles = []
    root = ET.fromstring(response.content)

    for article in root.findall(".//PubmedArticle"):
        try:
            title_el = article.find(".//ArticleTitle")
            title = title_el.text if title_el is not None else "Sans titre"

            authors = []
            for author in article.findall(".//Author")[:3]:
                lastname = author.find("LastName")
                forename = author.find("ForeName")
                if lastname is not None:
                    name = lastname.text
                    if forename is not None:
                        name += f" {forename.text[0]}."
                    authors.append(name)
            if len(article.findall(".//Author")) > 3:
                authors.append("et al.")
            authors_str = ", ".join(authors) if authors else "Auteurs inconnus"

            journal_el = article.find(".//Journal/Title")
            journal = journal_el.text if journal_el is not None else ""

            year_el = article.find(".//PubDate/Year")
            year = year_el.text if year_el is not None else "2025"

            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else ""
            pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

            abstract_el = article.find(".//AbstractText")
            abstract = abstract_el.text if abstract_el is not None else ""

            articles.append({
                "title": title,
                "authors": authors_str,
                "journal": journal,
                "year": year,
                "url": pubmed_url,
                "abstract": abstract,
            })
        except Exception:
            continue

    return articles

# ============================================================
# ÉTAPE 3 — Filtrer par journaux reconnus
# ============================================================
def filter_trusted_articles(articles):
    trusted = []
    others = []
    for article in articles:
        journal_lower = article["journal"].lower()
        if any(trusted_j in journal_lower for trusted_j in TRUSTED_JOURNALS):
            trusted.append(article)
        else:
            others.append(article)

    result = trusted if trusted else others[:3]
    return result[:5]

# ============================================================
# ÉTAPE 4 — Synthèse Groq
# ============================================================
def synthesize_with_groq(topic, articles):
    if not articles:
        return "Aucun article pertinent trouvé cette semaine."

    abstracts_text = ""
    for i, a in enumerate(articles, 1):
        abstracts_text += f"\n--- Article {i} ---\n"
        abstracts_text += f"Titre: {a['title']}\n"
        abstracts_text += f"Auteurs: {a['authors']}\n"
        abstracts_text += f"Journal: {a['journal']} ({a['year']})\n"
        abstracts_text += f"Résumé: {a['abstract'][:800]}\n"

    prompt = f"""Tu es un assistant scientifique expert en kinésithérapie et médecine du sport.

Voici {len(articles)} articles récents sur le thème : "{topic}"

{abstracts_text}

Rédige une synthèse clinique en français (150-200 mots) qui :
1. Identifie le message clé de chaque étude en une phrase
2. Explique concrètement ce que ça change pour la pratique clinique d'un kiné
3. Signale si les résultats se confirment entre plusieurs études

Sois direct, précis, et utile pour un kinésithérapeute praticien."""

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 600,
        },
    )

    data = response.json()
    if "choices" not in data:
        error_msg = data.get("error", {}).get("message", str(data))
        print(f"Erreur Groq pour '{topic}': {error_msg}")
        return f"Erreur lors de la synthèse : {error_msg}"

    return data["choices"][0]["message"]["content"]

# ============================================================
# ÉTAPE 5 — Email HTML
# ============================================================
def build_html_email(topic_results):
    today_str = datetime.now().strftime("%d %B %Y")

    topic_labels = {
        "musculoskeletal physiotherapy": "🦴 Pathologies musculo-squelettiques",
        "chronic pain neuroscience": "🧠 Neurosciences & Douleur",
        "sport performance rehabilitation": "⚡ Performance sportive",
        "physical therapy outcomes": "🔄 Rééducation & Réhabilitation",
    }

    sections_html = ""
    for topic, data in topic_results.items():
        label = topic_labels.get(topic, topic)
        articles = data["articles"]
        summary = data["summary"]

        articles_html = ""
        for a in articles:
            is_trusted = any(j in a["journal"].lower() for j in TRUSTED_JOURNALS)
            badge = '<span style="background:#2b7a78;color:white;font-size:11px;padding:2px 7px;border-radius:10px;margin-left:8px;">✓ Journal reconnu</span>' if is_trusted else ""
            articles_html += f"""
            <div style="border:1px solid #e0e0e0; border-radius:6px; padding:14px; margin-bottom:10px; background:white;">
                <p style="margin:0 0 4px; font-weight:bold; color:#222;">{a['title']}{badge}</p>
                <p style="margin:0 0 2px; color:#555; font-size:13px;">✍️ {a['authors']}</p>
                <p style="margin:0 0 6px; color:#888; font-size:13px;">📖 {a['journal']} — {a['year']}</p>
                <a href="{a['url']}" style="color:#2b7a78; font-size:13px;">🔗 Voir sur PubMed</a>
            </div>
            """

        sections_html += f"""
        <div style="margin-bottom:36px;">
            <h2 style="color:#2b7a78; border-bottom:2px solid #2b7a78; padding-bottom:8px;">{label}</h2>
            <div style="background:#f0f7f7; border-left:4px solid #2b7a78; padding:16px; border-radius:4px; margin-bottom:16px;">
                <p style="margin:0 0 6px; font-weight:bold; color:#2b7a78;">💡 Synthèse clinique</p>
                <p style="margin:0; line-height:1.7; color:#333;">{summary.replace(chr(10), '<br>')}</p>
            </div>
            <p style="font-weight:bold; color:#444; margin-bottom:8px;">📄 Articles sources ({len(articles)})</p>
            {articles_html}
        </div>
        """

    total_articles = sum(len(d["articles"]) for d in topic_results.values())

    html = f"""
    <html><body style="font-family: Georgia, serif; max-width:720px; margin:auto; padding:24px; color:#222; background:#fafafa;">
        <div style="background:#2b7a78; color:white; padding:28px; border-radius:10px; margin-bottom:36px;">
            <h1 style="margin:0; font-size:24px;">📚 Veille Scientifique Kiné</h1>
            <p style="margin:8px 0 0; opacity:0.85;">{today_str} — {total_articles} articles sélectionnés</p>
        </div>
        {sections_html}
        <p style="font-size:12px; color:#aaa; text-align:center; margin-top:40px; border-top:1px solid #eee; padding-top:16px;">
            Sources : PubMed · Synthèse : Groq LLaMA 3.3 · Filtrage : journaux reconnus en kiné & médecine du sport
        </p>
    </body></html>
    """
    return html

# ============================================================
# ÉTAPE 6 — Envoi Gmail
# ============================================================
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
    topic_results = {}

    for topic in TOPICS:
        print(f"  → {topic}")
        ids = fetch_pubmed_ids(topic)
        articles = fetch_article_details(ids)
        filtered = filter_trusted_articles(articles)
        summary = synthesize_with_groq(topic, filtered)
        topic_results[topic] = {"articles": filtered, "summary": summary}
        print(f"     {len(filtered)} articles retenus")

    print("📧 Construction et envoi de l'email...")
    html = build_html_email(topic_results)
    send_email(html)

if __name__ == "__main__":
    main()
