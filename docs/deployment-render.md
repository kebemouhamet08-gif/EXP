# Deploiement durable sur Render

ClasseXP doit utiliser PostgreSQL externe et un bucket objet prive. Le disque d'un
Web Service Render n'est ni la base de donnees ni l'archive des uploads.

## Avant le deploiement

1. Sauvegarder sans rien supprimer : `python scripts/backup_local_data.py`.
2. Creer une base PostgreSQL Neon (recommande) ou Supabase. Utiliser une connection
   string commencant par `postgresql+psycopg://` et conserver ses options TLS.
3. Creer un bucket Cloudflare R2 **prive**, un token API limite a ce bucket et
   relever l'endpoint S3, l'access key et la secret key.
4. Ajouter les variables ci-dessous dans Render. Ne jamais les committer.
5. Executer `alembic upgrade head` contre la base vide.
6. Auditer la SQLite avec `python scripts/migrate_sqlite_to_postgres.py --source
   database/classexp.db --dry-run`, puis relancer avec `--target-url` apres lecture
   du rapport. La cible doit etre vide; tout conflit provoque un rollback.
7. Auditer les uploads avec `python scripts/migrate_local_uploads_to_object_storage.py
   --dry-run`, puis relancer avec les variables R2. Les originaux restent intacts.
   `MISSING_SOURCE_FILE` signale une perte historique sans effacer la reference DB.

## Variables Render

```env
CLASSEXP_ENV=production
FLASK_ENV=production
CLASSEXP_HTTPS=1
CLASSEXP_SECRET_KEY=<secret long et stable>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>/<database>?sslmode=require
STORAGE_BACKEND=r2
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<secret Render>
R2_SECRET_ACCESS_KEY=<secret Render>
R2_BUCKET=<bucket prive>
R2_REGION=auto
```

OAuth reste optionnel. Ajouter les variables Google, Facebook, Microsoft et Apple
de `.env.example` uniquement pour les fournisseurs actives. Les callbacks doivent
utiliser le domaine HTTPS Render exact.

## Neon et Supabase

Pour Neon, creer projet/base, copier l'URL du role applicatif et remplacer le prefixe
`postgresql://` par `postgresql+psycopg://`. Une URL pooler convient. Pour Supabase,
copier l'URL PostgreSQL directe ou pooler depuis les parametres Database et appliquer
le meme prefixe. Dans les deux cas, stocker l'URL uniquement dans Render et lancer
Alembic. Le code ne depend d'aucun fournisseur particulier.

## Cloudflare R2

Creer un bucket prive, puis un API Token Object Read & Write limite a ce bucket.
Utiliser l'endpoint S3 du compte, jamais une URL publique R2.dev. ClasseXP genere des
URL presignees de cinq minutes apres controle des droits. Verifier sans exposer de
secret avec `flask --app app system-status`.

## Configuration Render

- Build command : `pip install -r requirements.txt`
- Pre-deploy command, si disponible : `alembic upgrade head`
- Start command : `gunicorn app:app`
- Variante sans pre-deploy : `alembic upgrade head && gunicorn app:app`
- Health check path : `/health`

Le `Procfile` utilise la variante idempotente. L'application refuse de demarrer en
production si la secret key est absente, la DB est SQLite ou le stockage est local ou
incomplet. `/health` teste l'application et la DB sans ecrire dans R2; `/ready` valide
aussi la presence de la configuration storage.

## Premier deploiement et redeploiement

Executer `system-status`, verifier `/health`, puis creer professeur, classe et devoir
avec sujet. Inscrire/rejoindre un eleve, deposer une copie, noter la copie et verifier
les telechargements ainsi qu'un acces tiers refuse en 403.

Declencher ensuite un redeploiement sans modifier les donnees. Le meme mot de passe
doit reconnecter les deux comptes; classe, devoir, session et note doivent etre
identiques; sujet et copie doivent rester telechargeables. C'est la preuve finale que
le disque Render n'est plus une dependance de persistance.

## Sauvegarde et rollback

Ne jamais supprimer `database/classexp.db`, `uploads/` ni le ZIP produit par le script
pendant la bascule. En cas d'echec, arreter les ecritures, conserver le rapport,
restaurer la version applicative precedente et diagnostiquer la transaction annulee.
Pour une DB deja en production, preferer un backup fournisseur a un downgrade Alembic
non relu.

## Checklist

Before deploy: backup cree; dry-runs relus; DB migree; bucket prive; variables Render
presentes; callbacks OAuth verifies.

After deploy: `/health` 200; `system-status` OK; parcours professeur/eleve complet;
controle 403; aucun secret dans les logs.

After redeploy: comptes, hashes, classe, devoir, session, note et objets identiques;
remember-me restaure le meme compte grace a la secret key stable.
