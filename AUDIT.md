# Audit technique et sécurité d'EventCrawler

> **État de remédiation :** les dix constats ci-dessous décrivent l'état initial
> ayant motivé les corrections. Ils sont désormais traités dans le code :
> authentification obligatoire, CSRF, écoute locale sans debug, approbation humaine
> à usage unique, validation SSRF, données d'exemple, API filtrées, écritures
> atomiques, journalisation, factory testable, tests/CI et manifests unifiés.

**Date :** 16 août 2026  
**Portée :** application Flask, crawler Python, automatisations Playwright, configuration, dépendances et exploitation.  
**Méthode :** revue statique ciblée, compilation Python, contrôle de cohérence des dépendances et recherche de secrets/fichiers sensibles suivis par Git. Aucun parcours réel de réservation n'a été lancé afin d'éviter une commande involontaire.

## Synthèse exécutive

L'application remplit son objectif fonctionnel, mais son modèle de sécurité correspond uniquement à un outil local sur une machine de confiance. Dans son état actuel, elle ne doit pas être exposée sur un réseau : le serveur écoute sur toutes les interfaces, n'authentifie personne et propose des routes capables de modifier la configuration, lancer des processus et confirmer automatiquement une réservation.

| Sévérité | Nombre |
| --- | ---: |
| Critique | 1 |
| Élevée | 3 |
| Moyenne | 4 |
| Faible | 2 |

**Priorité immédiate :** limiter l'écoute à `127.0.0.1`, désactiver le mode debug, ajouter une authentification et une protection CSRF, puis exiger une confirmation humaine avant toute soumission de réservation.

## Constats

### AUD-01 — Interface d'administration et réservation exposées sans authentification (critique)

**Preuves.** Flask démarre sur `0.0.0.0:5000` avec `debug=True`. Aucun décorateur ni middleware d'authentification ne protège les routes. Des requêtes POST peuvent lancer/arrêter le crawler, activer le planificateur, modifier les notes et la configuration, ou démarrer `booking_prepare.js`. Ce script est en mode `auto_confirm` et cherche notamment des boutons « Confirmer », « Commander », « Payer » et `button[type='submit']`.

**Impact.** Toute personne pouvant joindre le port peut piloter le service, provoquer des requêtes sortantes, lire les données collectées et potentiellement effectuer une réservation au nom du profil configuré. Le debugger Flask augmente encore l'impact d'une erreur applicative.

**Recommandation.** Par défaut, écouter uniquement sur `127.0.0.1` et désactiver le debug. Pour un accès distant, placer l'application derrière un reverse proxy TLS avec authentification forte; ajouter une autorisation applicative à toutes les routes et API. Refuser le démarrage en mode debug hors environnement explicitement local.

### AUD-02 — Absence de protection CSRF sur toutes les mutations (élevée)

**Preuves.** Les formulaires POST et l'appel JSON `/booking/prepare` ne valident aucun jeton CSRF. Les redirections utilisent en outre directement `request.referrer`, une entrée contrôlée par le client.

**Impact.** Un navigateur ayant accès au service peut être amené par un site tiers à démarrer un crawl, changer la configuration, activer le planificateur ou lancer une réservation.

**Recommandation.** Installer Flask-WTF (ou une protection CSRF équivalente), protéger aussi les appels JSON avec un jeton/en-tête dédié et remplacer les redirections vers le référent par des destinations internes en liste blanche. Configurer les cookies `Secure`, `HttpOnly` et `SameSite=Strict` une fois une session ajoutée.

### AUD-03 — Réservation automatique sans garde-fou transactionnel (élevée)

**Preuves.** L'API accepte directement `event_url`, `product_name`, `email` et `ticket_count`, puis lance Playwright. Les scripts annoncent un flux `auto_confirm` et peuvent cliquer sur des actions de validation ou paiement sans étape d'approbation séparée.

**Impact.** Une erreur utilisateur, un appel forgé, une page modifiée ou un sélecteur réparé incorrectement peut déclencher une commande non voulue. Le nombre de billets fourni à cette route n'est pas plafonné, contrairement à la valeur par défaut normalisée dans la configuration.

**Recommandation.** Séparer strictement « préparer » et « confirmer »; rendre la confirmation humaine obligatoire avec un jeton à usage unique, un résumé immuable (événement, produit, quantité, prix maximal) et une expiration courte. Plafonner la quantité côté serveur, autoriser uniquement les domaines et schémas attendus, et interrompre le flux si le prix ou le produit diffère du résumé approuvé.

### AUD-04 — SSRF via les URL de régions configurables (élevée)

**Preuves.** `/config` accepte une URL libre. `config_store.py` vérifie seulement qu'elle n'est pas vide, puis `crawler.py` la transmet à `requests.get`; aucune validation du schéma, de l'hôte, des redirections ou des adresses privées n'est appliquée.

**Impact.** Un utilisateur de l'interface — ou une attaque combinée avec AUD-01/AUD-02 — peut faire contacter au serveur des services internes, l'API de métadonnées d'un cloud ou une cible arbitraire.

**Recommandation.** N'autoriser que `https`, définir une liste blanche d'hôtes (`bizouk.com`, `kiwol.com` et sous-domaines nécessaires), résoudre puis refuser les plages privées, loopback, link-local et réservées, et revalider chaque redirection. Appliquer la même validation à `event_url` avant Playwright.

### AUD-05 — Données personnelles codées en dur et exposées par API (moyenne)

**Preuves.** Un nom, un numéro de téléphone et une adresse e-mail réels ou réalistes figurent dans les valeurs par défaut Python et JavaScript ainsi que dans `data/config.json`, suivi par Git. `/api/config` renvoie le profil complet sans filtrage.

**Impact.** Ces données sont copiées dans les clones, images, sauvegardes et historiques Git, puis divulguées à tout client pouvant appeler l'API.

**Recommandation.** Remplacer les valeurs par des exemples neutres, retirer `data/config.json` du suivi Git au profit d'un fichier `.example`, migrer les données opérationnelles vers un secret/fichier local aux permissions `0600`, masquer le profil dans l'API et réécrire l'historique si les valeurs sont authentiques.

### AUD-06 — Fuite de données métier et de diagnostic via les API (moyenne)

**Preuves.** Les API publiques exposent événements, billets (dont e-mails), échecs de réservation (extraits HTML, texte visible et erreurs), activité, configuration et états des processus. Les pages équivalentes sont elles aussi publiques.

**Impact.** Des données personnelles, des détails de billets, la topologie fonctionnelle et le contenu de pages tierces peuvent être exfiltrés.

**Recommandation.** Appliquer authentification et autorisation par défaut, supprimer ou masquer les champs sensibles dans les sérialisations, limiter les extraits de diagnostic, définir une durée de conservation et ajouter des en-têtes `Cache-Control: no-store` aux réponses sensibles.

### AUD-07 — Écritures de fichiers d'état non atomiques et concurrence fragile (moyenne)

**Preuves.** La configuration et les états JSON sont écrits directement avec `Path.write_text`. Le thread du planificateur, les routes Flask et les processus enfants peuvent lire ou écrire ces fichiers concurremment. Seuls certains lancements de processus ont un verrou, et ces verrous ne couvrent pas plusieurs workers/processus WSGI.

**Impact.** Un arrêt ou une lecture pendant une écriture peut produire du JSON tronqué, perdre une mise à jour ou lancer deux tâches. Plusieurs instances créeraient aussi plusieurs threads de planification.

**Recommandation.** Écrire dans un fichier temporaire du même répertoire, effectuer `fsync` puis `os.replace`; protéger les transitions avec un verrou interprocessus ou les stocker transactionnellement dans SQLite. Exécuter le planificateur comme service unique séparé de Flask.

### AUD-08 — Exceptions critiques silencieuses et observabilité insuffisante (moyenne)

**Preuves.** La boucle du planificateur intercepte toute `Exception` puis exécute `pass`; la lecture de plusieurs états remplace silencieusement les erreurs par des valeurs par défaut. Les erreurs de synchronisation des rapports sont également ignorées.

**Impact.** Une panne de planification, une corruption de fichier ou une régression peut rester invisible et donner une impression de fonctionnement normal.

**Recommandation.** Journaliser les exceptions avec contexte et trace, exposer un état dégradé dans un endpoint de santé, employer des exceptions ciblées et réserver les valeurs par défaut aux cas attendus (par exemple fichier absent).

### AUD-09 — Absence de suite de tests et point d'entrée racine trompeur (faible)

**Preuves.** Aucun fichier de test n'est présent. Le `main.py` racine affiche seulement un message tandis que l'application réelle se lance depuis `EventCrawler/app.py`. L'import de l'application initialise la base et démarre un thread, ce qui complique les tests isolés.

**Impact.** Les parseurs de pages, migrations SQLite, routes sensibles et transitions du planificateur peuvent régresser sans détection. Les plateformes utilisant `main.py` ne lancent pas le produit attendu.

**Recommandation.** Introduire une factory `create_app`, déplacer les effets de bord vers le démarrage explicite, fournir des fixtures temporaires et tester au minimum la normalisation des URL, les parseurs, la configuration, les autorisations et les routes. Aligner ou supprimer le point d'entrée racine.

### AUD-10 — Gestion des dépendances incohérente et audit non reproductible (faible)

**Preuves.** Les dépendances Python sont déclarées à la fois sans versions dans `requirements.txt` et avec des bornes minimales dans `pyproject.toml`. Deux `package.json` utilisent des versions Playwright différentes. Il n'existe pas de CI visible exécutant compilation, tests et audits.

**Impact.** Deux installations peuvent produire des environnements différents; une mise à jour transitive peut casser le service ou introduire une vulnérabilité sans alerte.

**Recommandation.** Choisir une source de vérité par écosystème, verrouiller et mettre à jour les dépendances avec un processus automatisé, puis ajouter une CI avec tests, `pip check`, audit Python et `npm audit`. L'audit npm devra être rejoué depuis un environnement autorisé : le registre a répondu HTTP 403 pendant cet audit.

## Points positifs observés

- Les requêtes SQL alimentées par des données utilisateur utilisent généralement des paramètres plutôt que de concaténer les valeurs.
- Les processus enfants sont lancés avec une liste d'arguments et sans `shell=True`, ce qui réduit le risque d'injection de commande.
- Les requêtes HTTP ont un délai maximal configurable et utilisent la vérification TLS par défaut de `requests`.
- Les identifiants d'événement présents dans les routes sont typés comme entiers par Flask.
- Les fichiers de base SQLite, journaux, captures et états d'exécution sont couverts par `.gitignore` (à l'exception notable de la configuration déjà suivie).

## Plan de remédiation proposé

### Sous 24 heures

1. Basculer sur `127.0.0.1`, `debug=False` et bloquer le port au pare-feu.
2. Désactiver le flux `auto_confirm` jusqu'à l'ajout d'une confirmation humaine.
3. Ajouter une authentification devant l'ensemble du service.
4. Retirer et renouveler les données personnelles si elles sont réelles.

### Sous 7 jours

1. Ajouter CSRF, validation stricte/listes blanches des URL et plafonds de réservation.
2. Filtrer les API et définir la conservation des données sensibles.
3. Rendre les écritures atomiques et sortir le planificateur du processus web.
4. Ajouter des journaux structurés et un endpoint de santé authentifié.

### Sous 30 jours

1. Refactoriser vers une factory Flask sans effet de bord à l'import.
2. Ajouter tests unitaires et d'intégration, puis une CI bloquante.
3. Unifier et verrouiller les manifests de dépendances; automatiser leurs audits.
4. Réaliser un test dynamique authentifié dans un environnement isolé, sans réservation réelle.

## Vérifications exécutées et limites

- `python -m compileall -q . ../main.py` : réussi.
- `python -m pip check` : réussi, aucune dépendance installée incohérente signalée.
- `rg --files | rg '(^|/)(test|tests|spec)'` : aucun test détecté.
- `git ls-files | rg '(\.env|\.sqlite|data/|key|secret|credential)'` : `data/config.json` détecté et examiné.
- `npm audit --omit=dev --json` : non concluant; l'endpoint d'audit du registre npm a répondu HTTP 403. Ce résultat ne permet pas d'affirmer l'absence de vulnérabilités.

Cet audit est une revue ponctuelle du code disponible. Il n'inclut ni pentest réseau, ni analyse SAST/DAST exhaustive, ni validation des comportements actuels des sites tiers.
