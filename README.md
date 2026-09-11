# ClasseXP

ClasseXP est une application scolaire Flask en cours de construction. Le socle actuel fournit une fabrique d’application, SQLite, une interface HTML/CSS/JavaScript, une authentification locale par session et des permissions `STUDENT` / `TEACHER`.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Définir ensuite `CLASSEXP_SECRET_KEY` avec une valeur longue et aléatoire. Les variables attendues sont répertoriées dans `.env.example` ; ce fichier n’est pas chargé automatiquement.

```powershell
flask --app app init-db
flask --app app run --debug
```

L’application est alors disponible sur `http://127.0.0.1:5000`.

## Tests

```powershell
python -m pytest -q tests
```

Le bac à sable utilisé pendant le développement exigeait de désactiver les plugins temporaires de pytest :

```powershell
python -m pytest -q tests -p no:tmpdir -p no:cacheprovider
```

## Organisation

- `app.py` : point d’entrée WSGI et développement ;
- `classexp/` : fabrique Flask, base, authentification et routes ;
- `templates/` : vues HTML légères ;
- `static/` : CSS et JavaScript vanilla ;
- `schema.sql` : schéma SQLite initial idempotent ;
- `tests/` : tests d’intégration Flask/SQLite ;
- `docs/` : audits et rapports de phase.

Les fichiers de base, secrets, environnements et futurs uploads sont exclus de Git.
