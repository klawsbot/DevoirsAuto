# Agent Devoirs IESEG 🎓

Agent autonome qui récupère les devoirs sur MyCourses, les rédige avec Claude, et les soumet après validation via Telegram.

## Architecture

```
VPS (tourne 24/7)
├── cron → lance agent.py run chaque nuit
├── Playwright → se connecte à MyCourses
├── Claude API → rédige les devoirs
└── Telegram bot → notifie pour validation

Toi (téléphone)
└── Reçois la notif → réponds /submit ou /modify
```

## Installation (première fois)

### 1. Cloner le repo

```bash
git clone https://github.com/TON_USERNAME/agent-devoirs.git
cd agent-devoirs
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurer les credentials

```bash
cp .env.example .env
# Ouvre .env et remplis tous les champs
```

**Récupérer ton token Telegram :**
1. Parle à `@BotFather` sur Telegram
2. Tape `/newbot` et suis les instructions
3. Récupère le token
4. Envoie un message à ton bot, puis ouvre :
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Copie ton `chat_id` depuis la réponse

**Récupérer ta clé Claude API :**
1. Va sur https://console.anthropic.com
2. API Keys → Create Key
3. Colle dans `.env`

### 4. Tester en local

```bash
# Récupère les devoirs
python agent.py fetch

# Vérifier ce qui a été trouvé
python agent.py status

# Rédiger le devoir n°1
python agent.py write --id 1

# Envoyer sur Telegram
python agent.py notify --id 1

# Soumettre après validation
python agent.py submit --id 1
```

## Déploiement sur VPS (automatisation totale)

### 1. Copier le projet sur le VPS

```bash
# Sur le VPS
git clone https://github.com/TON_USERNAME/agent-devoirs.git
cd agent-devoirs
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
nano .env  # Remplis les credentials
```

### 2. Configurer le cron

```bash
crontab -e
```

Ajouter cette ligne (lance l'agent tous les jours à 6h du matin) :

```
0 6 * * * cd /root/agent-devoirs && python agent.py run >> logs/cron.log 2>&1
```

### 3. Mettre à jour depuis GitHub

```bash
cd agent-devoirs && git pull
```

## Commandes disponibles

| Commande | Description |
|---|---|
| `python agent.py fetch` | Récupère tous les devoirs en cours |
| `python agent.py status` | Affiche l'état de tous les devoirs |
| `python agent.py write --id X` | Rédige le devoir X |
| `python agent.py notify --id X` | Envoie sur Telegram pour validation |
| `python agent.py submit --id X` | Soumet le devoir X sur Moodle |
| `python agent.py run` | Tout en une fois |

## Commandes Telegram

Depuis ton téléphone après réception d'une notif :

| Commande | Action |
|---|---|
| `/submit 1` | Soumet le devoir 1 tel quel |
| `/modify 1 reformule l'intro` | Demande une modification |
| `/cancel 1` | Annule la soumission |
| `/status` | État de tous les devoirs |

## Coût estimé

- **VPS Contabo** : déjà payé
- **Claude API** : ~2€ à 5€ / mois selon le nombre de devoirs
- **Telegram** : gratuit

## Structure du projet

```
agent-devoirs/
├── CLAUDE.md              ← Instructions pour Claude Code
├── agent.py               ← Script principal
├── requirements.txt       ← Dépendances Python
├── .env.example           ← Template credentials
├── .gitignore             
├── README.md              
├── data/                  ← Données locales (ignoré par git)
│   ├── assignments/       ← Devoirs récupérés (JSON)
│   ├── courses/           ← Fichiers de cours téléchargés
│   └── drafts/            ← Brouillons rédigés
└── logs/                  ← Journaux (ignoré par git)
```
