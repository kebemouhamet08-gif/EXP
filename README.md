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