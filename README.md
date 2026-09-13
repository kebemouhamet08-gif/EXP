# ClasseXP

Plateforme Flask de devoirs chronometres, en construction progressive.

## Lancer le projet

Depuis `/workspaces/EXP` :

```bash
python -m pip install -r ../requirements.txt
python -m flask --app app init-db
python app.py
```

Ouvrir ensuite `http://127.0.0.1:5000`.

## Phase actuelle

- inscription eleve ou professeur ;
- connexion et deconnexion ;
- mots de passe hashes ;
- tableaux de bord proteges par role ;
- classes avec code d’invitation ;
- création de devoirs avec sujet, ouverture et durée ;
- chrono calculé côté serveur ;
- dépôt de copies PDF, DOCX, JPG et PNG ;
- consultation des copies et notation professeur ;
- affichage des notes côté élève ;
- base SQLite pour les classes, devoirs et sessions d’examen.

La commande `init-db` reinitialise la base et efface les donnees existantes.

## Social login / OAuth

ClasseXP conserve la connexion locale par e-mail et mot de passe et peut aussi utiliser
Google, Facebook, Apple et Microsoft. L'application démarre sans ces fournisseurs :
leurs boutons sont alors affichés comme « Non configuré ». Copiez `.env.example` vers
un fichier `.env` ignoré par Git, puis injectez ces variables dans l'environnement du
processus Flask. ClasseXP charge ce fichier au démarrage ; ne committez jamais `.env`.
En développement, si `CLASSEXP_SECRET_KEY` est absente, une clé est générée une seule
fois dans `.classexp-secret-key`, également ignoré par Git, afin que les sessions et
les cookies « Se souvenir de moi » survivent aux redémarrages.

- Google : `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Créez un client OAuth Web dans
  Google Cloud, activez OpenID Connect et enregistrez
  `http://127.0.0.1:5000/auth/google/callback` en développement.
- Facebook : `FACEBOOK_CLIENT_ID`, `FACEBOOK_CLIENT_SECRET`, et facultativement
  `FACEBOOK_API_VERSION`. Créez une application Meta avec Facebook Login et enregistrez
  `http://127.0.0.1:5000/auth/facebook/callback`.
- Microsoft : `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` et
  `MICROSOFT_TENANT=common`. Dans Microsoft Entra, choisissez les comptes de toute
  organisation et les comptes Microsoft personnels, puis enregistrez
  `http://127.0.0.1:5000/auth/microsoft/callback`.
- Apple : `APPLE_CLIENT_ID` (Services ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID` et
  `APPLE_PRIVATE_KEY_PATH` (chemin local vers la clé `.p8`). Configurez le domaine et
  l'URI `https://votre-domaine/auth/apple/callback` dans Apple Developer. Apple exige
  un domaine HTTPS et ne prend pas en charge `localhost` comme URI Web ; le fournisseur
  reste donc « Non configuré » sans ces éléments externes.

En production, définissez obligatoirement une valeur longue et stable dans
`CLASSEXP_SECRET_KEY`, servez exclusivement en HTTPS et utilisez `CLASSEXP_HTTPS=1`.
Remplacez toutes les URI locales ci-dessus par les URI HTTPS exactes du domaine public.
Les URI doivent correspondre caractère pour caractère à celles enregistrées chez les
fournisseurs. Apple utilise un callback `form_post`; ClasseXP active alors un cookie de
session `SameSite=None; Secure`. Les autres flux utilisent `SameSite=Lax`.

Les flux utilisent Authorization Code, `state`, `nonce` pour OIDC et PKCE lorsque le
fournisseur le prend en charge. Authlib valide les réponses OIDC (signature, issuer,
audience et expiration). ClasseXP ne conserve ni access token, ni refresh token. Une
nouvelle identité externe passe par « Finaliser votre compte » pour choisir le rôle.
Une adresse déjà locale n'est jamais fusionnée automatiquement : son mot de passe et
une confirmation explicite sont requis. La migration OAuth est idempotente, s'exécute
au démarrage et ne supprime aucun compte existant.

## Architecture et tests

Le point d'entrée officiel est `app.py`, utilisé par `Procfile` avec `gunicorn app:app`.
Le dossier `classexp/` conserve une première architecture expérimentale et n'est pas
chargé par le déploiement actuel. La suite active dans `tests/` cible `app.py` et crée
une base SQLite ainsi qu'un dossier d'uploads temporaires pour chaque test.

Installer les dépendances de développement puis lancer les contrôles :

```powershell
python -m pip install -r requirements.txt
python -m compileall .
pytest -vv --cov=app --cov-report=term-missing
```
