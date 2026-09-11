# Phase 1 — Stabilisation Flask et tests

État : **TERMINÉ**

## Fichiers créés ou restructurés

`classexp/__init__.py`, `classexp/db.py`, `classexp/pages.py`, les templates, `static/css/app.css`, `.gitignore`, `.env.example`, `README.md` et les premiers tests. `app.py`, `requirements.txt` et `schema.sql` ont été restructurés. Le prototype `index.html`, non relié à Flask, a été remplacé par de vrais templates.

## Fonctionnalités et architecture

- fabrique `create_app` isolable par configuration de test ;
- point d’entrée WSGI minimal ;
- connexion SQLite par contexte avec clés étrangères actives ;
- commande `init-db` idempotente et non destructive ;
- routes `/`, `/connexion`, `/eleve`, `/professeur` ;
- réponses JSON cohérentes pour les erreurs sous `/api/` ;
- frontend responsive avec CSS séparé.

## Sécurité

Secrets et données runtime exclus de Git, secret de session lu depuis l’environnement (valeur aléatoire éphémère en développement), cookies `HttpOnly` et `SameSite=Lax`, contrainte SQL sur les rôles et relations SQLite actives.

## Tests exécutés

Compilation avec `python -m compileall`, inspection de `url_map`, exécution réelle du CLI puis `pytest`. Résultat final du socle et des phases suivantes : **13 tests réussis**. Le bac à sable Windows imposait `-p no:tmpdir -p no:cacheprovider` à cause de ses ACL temporaires ; ce n’est pas un défaut applicatif.

## Restant

Le schéma SQL reste volontairement initial et devra être remplacé par une stratégie de migrations avant les classes et devoirs. Les routes métier ne sont pas encore implémentées.
