#!/bin/bash
# Setup VPS — Agent Devoirs IESEG
# Lance ce script une seule fois sur ton VPS Contabo

echo "=== Installation Agent Devoirs IESEG ==="

# Mise à jour système
apt update && apt upgrade -y

# Python et pip
apt install -y python3 python3-pip git

# Cloner le repo
git clone https://github.com/klawsbot/DevoirsAuto.git
cd DevoirsAuto

# Dépendances Python
pip3 install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# Créer les dossiers
mkdir -p data/assignments data/courses data/drafts logs

# Copier le template .env
cp .env.example .env
echo ""
echo "=== Remplis maintenant le fichier .env ==="
echo "nano .env"
echo ""

# Configurer le cron (lance l'agent tous les jours à 7h)
(crontab -l 2>/dev/null; echo "0 7 * * * cd /root/DevoirsAuto && python3 agent.py run >> logs/cron.log 2>&1") | crontab -

# Créer un service systemd pour le bot Telegram (tourne en permanence)
cat > /etc/systemd/system/devoirs-bot.service << EOF
[Unit]
Description=Agent Devoirs IESEG — Bot Telegram
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/DevoirsAuto
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable devoirs-bot
systemctl start devoirs-bot

echo ""
echo "=== Installation terminée ==="
echo ""
echo "Prochaines étapes :"
echo "1. nano .env → remplis tous les credentials"
echo "2. systemctl status devoirs-bot → vérifie que le bot tourne"
echo "3. Envoie /help sur Telegram → le bot doit répondre"
echo "4. python3 agent.py fetch → premier test"
