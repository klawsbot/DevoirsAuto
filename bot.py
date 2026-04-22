"""
Bot Telegram bidirectionnel — Agent Devoirs IESEG
Écoute les commandes d'Isaac et pilote agent.py en réponse.
"""

import os
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID"))

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ENVOI DE MESSAGES
# ─────────────────────────────────────────────

def send_message(text: str, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode
    })


def send_document(file_path: str, caption: str = ""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption
        }, files={"document": f})


# ─────────────────────────────────────────────
# GESTION DES COMMANDES
# ─────────────────────────────────────────────

def handle_command(text: str):
    """Traite une commande reçue sur Telegram."""
    text = text.strip()
    parts = text.split(" ", 2)
    command = parts[0].lower()

    # /status — état de tous les devoirs
    if command == "/status":
        result = subprocess.run(
            ["python", "agent.py", "status"],
            capture_output=True, text=True
        )
        send_message(f"```\n{result.stdout}\n```")

    # /fetch — récupère les devoirs
    elif command == "/fetch":
        send_message("🔄 Récupération des devoirs en cours...")
        result = subprocess.run(
            ["python", "agent.py", "fetch"],
            capture_output=True, text=True
        )
        send_message(f"✅ Fetch terminé :\n```\n{result.stdout[-1000:]}\n```")

    # /write <id> — rédige un devoir
    elif command == "/write" and len(parts) >= 2:
        assignment_id = parts[1]
        send_message(f"✍️ Rédaction du devoir {assignment_id} en cours...")
        result = subprocess.run(
            ["python", "agent.py", "write", "--id", assignment_id],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            send_message(f"✅ Devoir {assignment_id} rédigé. Envoi du brouillon...")
            subprocess.run(["python", "agent.py", "notify", "--id", assignment_id])
        else:
            send_message(f"❌ Erreur :\n```\n{result.stderr[-500:]}\n```")

    # /submit <id> — soumet le devoir après validation
    elif command == "/submit" and len(parts) >= 2:
        assignment_id = parts[1]
        # Vérifier la zone de dépôt avant de soumettre
        assignments = load_assignments()
        assignment = next((a for a in assignments if str(a["id"]) == assignment_id), None)
        if assignment:
            send_message(
                f"⚠️ *Confirmation de soumission*\n\n"
                f"📝 *Devoir :* {assignment['title']}\n"
                f"📖 *Cours :* {assignment['course']}\n"
                f"📂 *Zone de dépôt :* {assignment.get('url', 'URL non disponible')}\n"
                f"⏰ *Date limite :* {assignment['due_date']}\n\n"
                f"Réponds `/confirm {assignment_id}` pour confirmer la soumission."
            )
        else:
            send_message(f"❌ Devoir {assignment_id} introuvable.")

    # /confirm <id> — confirmation finale avant soumission
    elif command == "/confirm" and len(parts) >= 2:
        assignment_id = parts[1]
        send_message(f"🚀 Soumission du devoir {assignment_id} en cours...")
        result = subprocess.run(
            ["python", "agent.py", "submit", "--id", assignment_id],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            send_message(f"✅ Devoir {assignment_id} soumis avec succès !")
        else:
            send_message(f"❌ Erreur lors de la soumission :\n```\n{result.stderr[-500:]}\n```")

    # /modify <id> <instructions> — demande une modification
    elif command == "/modify" and len(parts) >= 3:
        assignment_id = parts[1]
        instructions = parts[2]
        send_message(f"✏️ Modification en cours selon tes instructions...")
        result = subprocess.run(
            ["python", "agent.py", "modify", "--id", assignment_id, "--instructions", instructions],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            send_message(f"✅ Devoir modifié. Envoi de la nouvelle version...")
            subprocess.run(["python", "agent.py", "notify", "--id", assignment_id])
        else:
            send_message(f"❌ Erreur :\n```\n{result.stderr[-500:]}\n```")

    # /cancel <id> — annule
    elif command == "/cancel" and len(parts) >= 2:
        assignment_id = parts[1]
        assignments = load_assignments()
        assignment = next((a for a in assignments if str(a["id"]) == assignment_id), None)
        if assignment:
            assignment["status"] = "cancelled"
            save_assignments(assignments)
            send_message(f"❌ Devoir {assignment_id} annulé.")

    # /mfa <code> — transmet le code MFA au handler
    elif command == "/mfa" and len(parts) >= 2:
        code = parts[1]
        # Écrire le code dans un fichier temporaire que mfa_handler.py lit
        Path("data").mkdir(exist_ok=True)
        with open("data/mfa_code.txt", "w") as f:
            f.write(code)
        send_message(f"🔐 Code MFA `{code}` transmis. Déverrouillage en cours...")

    # /run — tout en une fois
    elif command == "/run":
        send_message("🤖 Lancement complet : fetch + rédaction + notification...")
        result = subprocess.run(
            ["python", "agent.py", "run"],
            capture_output=True, text=True
        )
        send_message(f"✅ Run terminé :\n```\n{result.stdout[-1000:]}\n```")

    # /help — liste des commandes
    elif command == "/help":
        send_message(
            "📋 *Commandes disponibles*\n\n"
            "`/status` — État de tous les devoirs\n"
            "`/fetch` — Récupère les devoirs depuis MyCourses\n"
            "`/write <id>` — Rédige le devoir\n"
            "`/submit <id>` — Vérifie la zone de dépôt\n"
            "`/confirm <id>` — Confirme et soumet\n"
            "`/modify <id> <instructions>` — Modifie le brouillon\n"
            "`/cancel <id>` — Annule\n"
            "`/mfa <code>` — Transmet le code MFA\n"
            "`/run` — Tout en une fois\n"
            "`/help` — Cette aide"
        )

    else:
        send_message(
            "❓ Commande non reconnue. Tape `/help` pour voir les commandes disponibles."
        )


# ─────────────────────────────────────────────
# POLLING TELEGRAM
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


def run_bot():
    """Démarre le bot en long polling."""
    log.info("Bot Telegram démarré. En écoute...")
    send_message("🤖 Agent Devoirs en ligne. Tape `/help` pour voir les commandes.")

    offset = None
    base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            response = requests.get(f"{base_url}/getUpdates", params=params, timeout=35)
            data = response.json()

            if not data.get("ok"):
                log.warning(f"Telegram API error: {data}")
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "")

                # Sécurité : ignorer les messages qui ne viennent pas d'Isaac
                if chat_id != TELEGRAM_CHAT_ID:
                    log.warning(f"Message ignoré de chat_id inconnu : {chat_id}")
                    continue

                if text.startswith("/"):
                    log.info(f"Commande reçue : {text}")
                    handle_command(text)

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            log.error(f"Erreur bot : {e}")
            import time
            time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/bot.log"),
            logging.StreamHandler()
        ]
    )
    run_bot()
