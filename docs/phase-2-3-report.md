# Phases 2–3 — Authentification locale et permissions

État : **TERMINÉ**

## Implémentation

- inscription locale JSON avec validation et conflit d’e-mail ;
- mots de passe hachés avec `scrypt` via Werkzeug ;
- connexion, déconnexion et utilisateur courant ;
- sessions nettoyées avant connexion et après déconnexion ;
- jeton CSRF lié à la session pour les mutations d’authentification ;
- chargement du rôle depuis SQLite à chaque requête authentifiée ;
- décorateurs d’accès connecté et par rôle ;
- redirection des visiteurs anonymes et réponses 401/403 pour l’API ;
- formulaire de connexion piloté par Fetch API sans logique métier dans Jinja.

## Routes API

- `GET /api/auth/csrf`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

## Vérifications

Les tests couvrent inscription valide/invalide, doublon, hash, CSRF absent, bon et mauvais mot de passe, session, logout, anonymat et interdictions croisées entre `STUDENT` et `TEACHER`. Résultat : **13 tests réussis** sur la suite complète.

## Limites et prochaine phase

La sélection du rôle à l’inscription est actuellement ouverte et validée côté serveur ; une politique d’invitation pour les professeurs devra être décidée avant mise en production. La prochaine phase doit introduire une stratégie de migrations et les modèles `Class` / `Membership`, puis l’API créer/rejoindre une classe avec contrôle objet par objet.
