# Phase 0 — Audit initial

État : **TERMINÉ**

Audit réalisé avant toute modification fonctionnelle, sur le commit `3abbfb4` et les changements locaux préexistants.

## 1. Structure initiale

Le dépôt contenait uniquement `app.py`, `index.html`, `requirements.txt` et `schema.sql`. Le commit initial suivait quatre fichiers vides ; leur contenu constituait donc des modifications locales non validées, conservées comme point de départ.

## 2. Architecture détectée

Application Flask monolithique de 51 lignes, connexion SQLite attachée à `flask.g`, commande `init-db` et une unique route `/`. Aucun paquet applicatif, service métier, module d’authentification ou configuration par environnement.

## 3. Routes initiales

Seule `GET /` existait. `/connexion`, `/eleve`, `/professeur`, l’upload affiché dans le HTML et toutes les routes API étaient absents.

## 4. Dépendances initiales

`requirements.txt` était un export de système Linux de plus de cent paquets sans Flask. Il comportait des composants sans rapport avec ClasseXP et non installables tels quels sous Windows. Flask et pytest étaient absents du Python actif.

## 5. Base de données initiale

Aucun fichier de base n’existait. Le schéma brut comportait `utilisateurs`, `classes`, `devoirs` et `sessions_examen`. Il supprimait toutes les tables à chaque initialisation, ne rendait pas plusieurs relations obligatoires, n’activait pas les clés étrangères SQLite et ne modélisait ni membership, ni vraie remise, ni photo ordonnée.

## 6. Frontend initial

Un fichier HTML isolé simulait un devoir de trois heures. Il n’était servi par aucune route, contenait CSS et JavaScript en ligne, pointait vers des routes inexistantes et un fichier supposé public. Son minuteur client était présenté comme autorité de fermeture, ce qui ne peut pas constituer un contrôle métier.

## 7. Tests initiaux

Aucun dossier ni fichier de test. `pytest --collect-only` ne pouvait pas démarrer car pytest n’était pas installé.

## 8. Problèmes et bugs visibles

- application impossible à importer sans Flask ;
- chemin SQLite relatif au répertoire de lancement ;
- création du dossier de base uniquement dans le CLI ;
- absence des routes annoncées ;
- frontend inutilisé et endpoints inexistants ;
- aucune validation testée ni gestion d’erreur API ;
- mode debug activé lors du lancement direct.

## 9. Risques de sécurité initiaux

- aucune session, permission, CSRF ou authentification ;
- schéma acceptant un rôle `ADMIN` non demandé ;
- liens vers des sujets potentiellement publics ;
- aucune défense d’upload (MIME, taille, chemin, permissions) ;
- clés étrangères non garanties par SQLite ;
- aucune exclusion Git pour secrets, base ou stockage.

## 10. Plan de phase 1 retenu

Créer une fabrique Flask testable, centraliser la configuration, fiabiliser le cycle SQLite, rendre le schéma initial non destructif, brancher les quatre pages de base, séparer les assets, normaliser les erreurs API, réduire les dépendances, ignorer les données locales et bâtir des tests d’intégration. Ce plan a été exécuté dans la phase 1.
