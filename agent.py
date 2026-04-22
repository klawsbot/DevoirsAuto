"""
Agent Devoirs IESEG
Scrape MyCourses, rédige les devoirs avec Claude API, notifie via Telegram.
"""

import os
import json
import argparse
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Setup logging
Path("logs").mkdir(exist_ok=True)
Path("data/assignments").mkdir(parents=True, exist_ok=True)
Path("data/courses").mkdir(parents=True, exist_ok=True)
Path("data/drafts").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

MOODLE_URL = "https://mycourses.ieseg.fr"
MOODLE_USER = os.getenv("MOODLE_USER")
MOODLE_PASS = os.getenv("MOODLE_PASS")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ─────────────────────────────────────────────
# SCRAPING MOODLE
# ─────────────────────────────────────────────

async def fetch_assignments():
    """Se connecte à MyCourses et récupère tous les devoirs en cours."""
    from playwright.async_api import async_playwright

    log.info("Connexion à MyCourses...")
    assignments = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Connexion
        await page.goto(f"{MOODLE_URL}/login/index.php")
        await page.fill("#username", MOODLE_USER)
        await page.fill("#password", MOODLE_PASS)
        await page.click("#loginbtn")
        await page.wait_for_load_state("networkidle")

        log.info("Connecté. Récupération des devoirs...")

        # Aller sur la page des devoirs à rendre
        await page.goto(f"{MOODLE_URL}/my/")
        await page.wait_for_load_state("networkidle")

        # Récupérer le bloc "À rendre"
        # Moodle affiche les devoirs dans le timeline block
        try:
            await page.wait_for_selector(".block_timeline", timeout=5000)
            items = await page.query_selector_all(".event-list-item")

            for item in items:
                try:
                    title_el = await item.query_selector(".event-name")
                    course_el = await item.query_selector(".course-name")
                    date_el = await item.query_selector(".date-column")
                    link_el = await item.query_selector("a")

                    title = await title_el.inner_text() if title_el else "Sans titre"
                    course = await course_el.inner_text() if course_el else "Cours inconnu"
                    due_date = await date_el.inner_text() if date_el else "Date inconnue"
                    link = await link_el.get_attribute("href") if link_el else ""

                    assignment = {
                        "id": len(assignments) + 1,
                        "title": title.strip(),
                        "course": course.strip(),
                        "due_date": due_date.strip(),
                        "url": link,
                        "status": "pending",
                        "fetched_at": datetime.now().isoformat()
                    }

                    # Aller chercher la consigne détaillée
                    if link:
                        await page.goto(link)
                        await page.wait_for_load_state("networkidle")

                        intro_el = await page.query_selector(".box.py-3")
                        if intro_el:
                            assignment["instructions"] = await intro_el.inner_text()
                        else:
                            assignment["instructions"] = "Consigne non trouvée, vérifier manuellement."

                    assignments.append(assignment)
                    log.info(f"  ✓ Devoir trouvé : {title}")

                except Exception as e:
                    log.warning(f"Erreur sur un devoir : {e}")
                    continue

        except Exception as e:
            log.warning(f"Bloc timeline non trouvé, tentative méthode alternative... ({e})")
            # Méthode alternative : chercher via les cours
            assignments = await fetch_from_courses(page)

        await browser.close()

    # Sauvegarder
    output_file = "data/assignments/assignments.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(assignments, f, ensure_ascii=False, indent=2)

    log.info(f"{len(assignments)} devoir(s) récupéré(s) → {output_file}")
    return assignments


async def fetch_from_courses(page):
    """Méthode alternative : parcourt chaque cours pour trouver les devoirs."""
    assignments = []

    await page.goto(f"{MOODLE_URL}/my/")
    course_links = await page.query_selector_all("a[href*='/course/view.php']")
    urls = []
    for link in course_links:
        href = await link.get_attribute("href")
        if href and href not in urls:
            urls.append(href)

    for course_url in urls:
        try:
            await page.goto(course_url)
            await page.wait_for_load_state("networkidle")
            course_name_el = await page.query_selector("h1")
            course_name = await course_name_el.inner_text() if course_name_el else course_url

            assign_links = await page.query_selector_all("a[href*='/mod/assign/view.php']")
            for link in assign_links:
                href = await link.get_attribute("href")
                text = await link.inner_text()
                if href:
                    assignments.append({
                        "id": len(assignments) + 1,
                        "title": text.strip(),
                        "course": course_name.strip(),
                        "due_date": "À vérifier",
                        "url": href,
                        "status": "pending",
                        "fetched_at": datetime.now().isoformat()
                    })
        except Exception as e:
            log.warning(f"Erreur sur cours {course_url}: {e}")

    return assignments


async def download_course_files(assignment_id: int):
    """Télécharge les fichiers de cours associés à un devoir."""
    from playwright.async_api import async_playwright

    assignments = load_assignments()
    assignment = next((a for a in assignments if a["id"] == assignment_id), None)
    if not assignment:
        log.error(f"Devoir {assignment_id} introuvable")
        return []

    course_dir = Path(f"data/courses/{assignment_id}")
    course_dir.mkdir(exist_ok=True)

    downloaded = []
    log.info(f"Téléchargement des cours pour : {assignment['title']}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        # Reconnexion
        await page.goto(f"{MOODLE_URL}/login/index.php")
        await page.fill("#username", MOODLE_USER)
        await page.fill("#password", MOODLE_PASS)
        await page.click("#loginbtn")
        await page.wait_for_load_state("networkidle")

        # Aller sur le cours
        await page.goto(assignment["url"])
        await page.wait_for_load_state("networkidle")

        # Trouver tous les PDFs et ressources
        pdf_links = await page.query_selector_all("a[href$='.pdf'], a[href*='resource']")

        for link in pdf_links[:5]:  # Limite à 5 fichiers pour éviter les surcharges
            try:
                href = await link.get_attribute("href")
                name = await link.inner_text()

                async with page.expect_download() as dl:
                    await link.click()
                download = await dl.value
                dest = course_dir / f"{name.strip()[:50]}.pdf"
                await download.save_as(str(dest))
                downloaded.append(str(dest))
                log.info(f"  ✓ Téléchargé : {dest.name}")

            except Exception as e:
                log.warning(f"  Impossible de télécharger {href}: {e}")

        await browser.close()

    return downloaded


# ─────────────────────────────────────────────
# RÉDACTION AVEC CLAUDE API
# ─────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrait le texte d'un PDF."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages[:20]:  # Max 20 pages par fichier
                text += page.extract_text() or ""
        return text[:8000]  # Limite pour le contexte
    except Exception as e:
        log.warning(f"Impossible de lire {pdf_path}: {e}")
        return ""


def write_draft(assignment_id: int):
    """Appelle Claude API pour rédiger le devoir."""
    import anthropic

    assignments = load_assignments()
    assignment = next((a for a in assignments if a["id"] == assignment_id), None)
    if not assignment:
        log.error(f"Devoir {assignment_id} introuvable")
        return None

    log.info(f"Rédaction du devoir : {assignment['title']}")

    # Charger le contexte des cours
    course_context = ""
    course_dir = Path(f"data/courses/{assignment_id}")
    if course_dir.exists():
        for pdf_file in course_dir.glob("*.pdf"):
            text = extract_text_from_pdf(str(pdf_file))
            if text:
                course_context += f"\n\n--- Extrait de {pdf_file.name} ---\n{text}"

    # Construire le prompt
    system_prompt = """Tu es un étudiant en alternance en gestion de projet supply chain à l'IESEG.
Tu rédiges un devoir universitaire de manière naturelle, comme un vrai étudiant.
Ton style : clair, structuré, avec la terminologie exacte des cours fournis.
Ne mentionne jamais l'IA. Écris comme si c'était toi qui avais réfléchi et rédigé.
Si des cours sont fournis, base-toi PRIORITAIREMENT dessus pour la terminologie et les concepts."""

    user_prompt = f"""Voici un devoir à rédiger.

**Cours :** {assignment['course']}
**Titre :** {assignment['title']}
**Date limite :** {assignment['due_date']}

**Consigne :**
{assignment.get('instructions', 'Consigne non disponible, fais de ton mieux.')}

{f"**Extraits de cours disponibles :**{course_context}" if course_context else "Aucun cours téléchargé, base-toi sur tes connaissances générales en supply chain."}

Rédige une réponse complète et bien structurée. Indique clairement si tu as dû faire des hypothèses."""

    # Appel API
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=system_prompt
    )

    draft = message.content[0].text

    # Sauvegarder
    draft_file = f"data/drafts/draft_{assignment_id}.md"
    with open(draft_file, "w", encoding="utf-8") as f:
        f.write(f"# {assignment['title']}\n")
        f.write(f"**Cours :** {assignment['course']}\n")
        f.write(f"**Date limite :** {assignment['due_date']}\n\n")
        f.write("---\n\n")
        f.write(draft)

    # Mettre à jour le statut
    assignment["status"] = "drafted"
    assignment["draft_file"] = draft_file
    save_assignments(assignments)

    log.info(f"Brouillon sauvegardé → {draft_file}")
    return draft


# ─────────────────────────────────────────────
# NOTIFICATION TELEGRAM
# ─────────────────────────────────────────────

def notify_telegram(assignment_id: int, draft: str):
    """Envoie le brouillon sur Telegram pour validation."""
    import requests

    assignments = load_assignments()
    assignment = next((a for a in assignments if a["id"] == assignment_id), None)

    # Message de notification
    message = f"""📚 *Nouveau devoir rédigé !*

📖 *Cours :* {assignment['course']}
📝 *Devoir :* {assignment['title']}
⏰ *Date limite :* {assignment['due_date']}

Voici la préversion (voir fichier joint).

Pour valider et soumettre, réponds :
✅ `/submit {assignment_id}` — Soumettre tel quel
✏️ `/modify {assignment_id} [tes remarques]` — Modifier d'abord
❌ `/cancel {assignment_id}` — Annuler"""

    # Envoyer le message
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    })

    # Envoyer le fichier draft
    draft_file = f"data/drafts/draft_{assignment_id}.md"
    if Path(draft_file).exists():
        files_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        with open(draft_file, "rb") as f:
            requests.post(files_url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": f"Préversion — {assignment['title']}"
            }, files={"document": f})

    log.info(f"Notification Telegram envoyée pour le devoir {assignment_id}")


# ─────────────────────────────────────────────
# SOUMISSION SUR MOODLE
# ─────────────────────────────────────────────

async def submit_assignment(assignment_id: int):
    """Soumet le devoir sur Moodle."""
    from playwright.async_api import async_playwright

    assignments = load_assignments()
    assignment = next((a for a in assignments if a["id"] == assignment_id), None)
    if not assignment:
        log.error(f"Devoir {assignment_id} introuvable")
        return False

    draft_file = assignment.get("draft_file", f"data/drafts/draft_{assignment_id}.md")
    if not Path(draft_file).exists():
        log.error(f"Fichier brouillon introuvable : {draft_file}")
        return False

    log.info(f"Soumission du devoir : {assignment['title']}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Connexion
        await page.goto(f"{MOODLE_URL}/login/index.php")
        await page.fill("#username", MOODLE_USER)
        await page.fill("#password", MOODLE_PASS)
        await page.click("#loginbtn")
        await page.wait_for_load_state("networkidle")

        # Aller sur le devoir
        await page.goto(assignment["url"])
        await page.wait_for_load_state("networkidle")

        try:
            # Cliquer sur "Ajouter une remise" ou "Modifier ma remise"
            submit_btn = await page.query_selector("input[value*='remise'], input[value*='submission'], a[href*='editsubmission']")
            if submit_btn:
                await submit_btn.click()
                await page.wait_for_load_state("networkidle")

                # Lire le contenu du draft
                with open(draft_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Essayer de remplir la zone de texte en ligne
                text_area = await page.query_selector(".editor_atto_content, div[contenteditable='true'], textarea[name*='text']")
                if text_area:
                    await text_area.click()
                    await text_area.fill(content)
                    log.info("Contenu inséré dans la zone texte")
                else:
                    # Upload fichier si pas de zone texte
                    log.info("Pas de zone texte, tentative d'upload de fichier...")
                    # Convertir le MD en fichier texte
                    txt_file = draft_file.replace(".md", ".txt")
                    with open(txt_file, "w", encoding="utf-8") as f:
                        f.write(content)

                    file_input = await page.query_selector("input[type='file']")
                    if file_input:
                        await file_input.set_input_files(txt_file)

                # Valider
                save_btn = await page.query_selector("input[value*='Enregistrer'], input[value*='Save']")
                if save_btn:
                    await save_btn.click()
                    await page.wait_for_load_state("networkidle")
                    log.info("✅ Devoir soumis avec succès !")

                    # Mettre à jour le statut
                    assignment["status"] = "submitted"
                    assignment["submitted_at"] = datetime.now().isoformat()
                    save_assignments(assignments)

                    # Notifier
                    notify_submitted(assignment)
                    await browser.close()
                    return True

        except Exception as e:
            log.error(f"Erreur lors de la soumission : {e}")
            notify_error(assignment, str(e))

        await browser.close()
    return False


def notify_submitted(assignment):
    """Notifie Isaac que le devoir a été soumis."""
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"✅ Devoir soumis avec succès !\n\n📝 *{assignment['title']}*\n📖 {assignment['course']}",
        "parse_mode": "Markdown"
    })


def notify_error(assignment, error):
    """Notifie Isaac d'une erreur."""
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"❌ Erreur lors de la soumission de *{assignment['title']}*\n\nDétail : {error}\n\nIntervention manuelle requise.",
        "parse_mode": "Markdown"
    })


# ─────────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────────

def load_assignments():
    path = "data/assignments/assignments.json"
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_assignments(assignments):
    path = "data/assignments/assignments.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(assignments, f, ensure_ascii=False, indent=2)


def print_status():
    assignments = load_assignments()
    if not assignments:
        print("Aucun devoir en base. Lance d'abord : python agent.py fetch")
        return
    print(f"\n{'ID':<5} {'Statut':<12} {'Cours':<30} {'Titre':<40} {'Date limite'}")
    print("-" * 100)
    for a in assignments:
        print(f"{a['id']:<5} {a['status']:<12} {a['course'][:28]:<30} {a['title'][:38]:<40} {a['due_date']}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agent Devoirs IESEG")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("fetch", help="Récupère les devoirs depuis MyCourses")

    write_p = subparsers.add_parser("write", help="Rédige un devoir")
    write_p.add_argument("--id", type=int, required=True)

    notify_p = subparsers.add_parser("notify", help="Envoie sur Telegram")
    notify_p.add_argument("--id", type=int, required=True)

    submit_p = subparsers.add_parser("submit", help="Soumet le devoir sur Moodle")
    submit_p.add_argument("--id", type=int, required=True)

    subparsers.add_parser("run", help="Tout en une fois (fetch + write + notify)")
    subparsers.add_parser("status", help="Affiche l'état des devoirs")

    args = parser.parse_args()

    if args.command == "fetch":
        asyncio.run(fetch_assignments())

    elif args.command == "write":
        asyncio.run(download_course_files(args.id))
        draft = write_draft(args.id)
        if draft:
            print(f"\n{'='*60}")
            print(draft[:500] + "..." if len(draft) > 500 else draft)
            print(f"{'='*60}")
            print(f"\nBrouillon complet → data/drafts/draft_{args.id}.md")

    elif args.command == "notify":
        assignments = load_assignments()
        assignment = next((a for a in assignments if a["id"] == args.id), None)
        if assignment:
            draft_file = assignment.get("draft_file", f"data/drafts/draft_{args.id}.md")
            with open(draft_file, "r", encoding="utf-8") as f:
                draft = f.read()
            notify_telegram(args.id, draft)

    elif args.command == "submit":
        asyncio.run(submit_assignment(args.id))

    elif args.command == "run":
        assignments = asyncio.run(fetch_assignments())
        for assignment in assignments:
            if assignment["status"] == "pending":
                asyncio.run(download_course_files(assignment["id"]))
                draft = write_draft(assignment["id"])
                if draft:
                    notify_telegram(assignment["id"], draft)

    elif args.command == "status":
        print_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
