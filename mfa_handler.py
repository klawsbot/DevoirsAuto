"""
MFA Handler — Gère l'authentification Microsoft avec code transmis via Telegram.
Utilisé par agent.py quand la session est expirée.
"""

import os
import asyncio
import logging
import time
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = str(os.getenv("TELEGRAM_CHAT_ID"))

log = logging.getLogger(__name__)


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    })


def wait_for_mfa_code(timeout: int = 180) -> str:
    """
    Attend qu'Isaac envoie /mfa <code> sur Telegram.
    Retourne le code ou None si timeout.
    """
    mfa_file = Path("data/mfa_code.txt")

    # Supprimer l'ancien code s'il existe
    if mfa_file.exists():
        mfa_file.unlink()

    send_telegram(
        "🔐 *Authentification requise*\n\n"
        "La session MyCourses a expiré.\n\n"
        "1. Ouvre Microsoft Authenticator\n"
        "2. Copie le code affiché\n"
        "3. Réponds ici : `/mfa XXXXXX`\n\n"
        f"⏳ Tu as {timeout // 60} minutes."
    )

    start = time.time()
    while time.time() - start < timeout:
        if mfa_file.exists():
            code = mfa_file.read_text().strip()
            if code:
                mfa_file.unlink()
                log.info(f"Code MFA reçu : {code}")
                return code
        time.sleep(2)

    send_telegram("❌ Timeout MFA — aucun code reçu. Relance manuellement.")
    return None


async def handle_mfa_page(page) -> bool:
    """
    Détecte et gère la page MFA Microsoft.
    - Clique sur 'Autre moyen de connexion' pour utiliser le code TOTP
    - Attend le code depuis Telegram
    - Le saisit et coche 'Ne plus demander pendant 30 jours'
    """
    try:
        # Vérifier si on est sur une page MFA
        current_url = page.url
        if "login.microsoftonline.com" not in current_url and "mfa" not in current_url.lower():
            return False

        log.info("Page MFA détectée")

        # Chercher le bouton 'Autre moyen de connexion' ou équivalent
        other_methods_selectors = [
            "a[href*='otherOptions']",
            "a:has-text('autre')",
            "a:has-text('Other')",
            "#otherWaysToSigninLink",
            "a[id*='other']",
            "a:has-text('Se connecter d\\'une autre façon')",
            "a:has-text('Sign in another way')"
        ]

        clicked_other = False
        for selector in other_methods_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    await page.wait_for_load_state("networkidle")
                    log.info(f"Cliqué sur 'Autre moyen' avec sélecteur : {selector}")
                    clicked_other = True
                    break
            except Exception:
                continue

        # Si on a cliqué sur 'autre moyen', chercher l'option code TOTP/Authenticator
        if clicked_other:
            totp_selectors = [
                "div[data-value*='PhoneAppOTP']",
                "div:has-text('code')",
                "li:has-text('Authenticator')",
                "div[aria-label*='code']"
            ]
            for selector in totp_selectors:
                try:
                    opt = await page.query_selector(selector)
                    if opt:
                        await opt.click()
                        await page.wait_for_load_state("networkidle")
                        log.info("Option code TOTP sélectionnée")
                        break
                except Exception:
                    continue

        # Demander le code à Isaac via Telegram
        code = wait_for_mfa_code(timeout=180)
        if not code:
            return False

        # Saisir le code
        code_input_selectors = [
            "input[name='otc']",
            "input[placeholder*='code']",
            "input[placeholder*='Code']",
            "input[type='tel']",
            "input[autocomplete='one-time-code']"
        ]

        for selector in code_input_selectors:
            try:
                input_el = await page.query_selector(selector)
                if input_el:
                    await input_el.fill(code)
                    log.info(f"Code MFA saisi : {code}")
                    break
            except Exception:
                continue

        # Cocher "Ne plus me demander pendant 30 jours"
        checkbox_selectors = [
            "input#KmsiCheckboxField",
            "input[name='DontShowAgain']",
            "input[type='checkbox']",
            "#idChkBx_SAOTCC_TD"
        ]

        for selector in checkbox_selectors:
            try:
                checkbox = await page.query_selector(selector)
                if checkbox:
                    is_checked = await checkbox.is_checked()
                    if not is_checked:
                        await checkbox.check()
                        log.info("Case '30 jours' cochée")
                    break
            except Exception:
                continue

        # Valider
        submit_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "#idSubmit_SAOTCC_Continue",
            "input[value*='Vérifier']",
            "input[value*='Verify']",
            "button:has-text('Vérifier')"
        ]

        for selector in submit_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    await page.wait_for_load_state("networkidle")
                    log.info("MFA validé")
                    break
            except Exception:
                continue

        # Vérifier qu'on est bien passé
        await asyncio.sleep(2)
        new_url = page.url
        if "mycourses.ieseg.fr" in new_url or "login.microsoftonline.com" not in new_url:
            send_telegram("✅ MFA validé ! Session active pour 30 jours.")
            log.info("MFA réussi — session établie")
            return True
        else:
            send_telegram("❌ MFA échoué. Vérifie le code et réessaie.")
            log.error("MFA échoué — toujours sur la page de login")
            return False

    except Exception as e:
        log.error(f"Erreur MFA handler : {e}")
        send_telegram(f"❌ Erreur MFA : {e}")
        return False
