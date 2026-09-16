"""Centralised server-side authorisation for collaborative ClasseXP features."""

def _one(db, sql, params):
    return db.execute(sql, params).fetchone() is not None


def is_admin(user):
    return bool(user and user.is_authenticated and user.role == "ADMIN")


def is_class_owner(db, user_id, classe_id):
    return _one(db, "SELECT 1 FROM classe_professeurs WHERE classe_id=? AND professeur_id=? AND role='OWNER'", (classe_id, user_id))


def is_class_teacher(db, user_id, classe_id):
    return _one(db, "SELECT 1 FROM classe_professeurs WHERE classe_id=? AND professeur_id=?", (classe_id, user_id))


def is_class_student(db, user_id, classe_id):
    return _one(db, "SELECT 1 FROM classe_eleves WHERE classe_id=? AND eleve_id=? AND statut='ACTIVE'", (classe_id, user_id))


def is_class_responsable(db, user_id, classe_id):
    return _one(db, "SELECT 1 FROM classe_eleves WHERE classe_id=? AND eleve_id=? AND statut='ACTIVE' AND role='RESPONSABLE'", (classe_id, user_id))


def can_manage_class(db, user_id, classe_id):
    return is_class_owner(db, user_id, classe_id)


def can_manage_members(db, user_id, classe_id):
    return is_class_teacher(db, user_id, classe_id)


def can_view_assignment(db, user_id, classe_id):
    return is_class_teacher(db, user_id, classe_id) or is_class_student(db, user_id, classe_id)


def can_manage_assignment(db, user_id, classe_id):
    return is_class_teacher(db, user_id, classe_id)


def can_view_members(db, user_id, classe_id):
    if is_class_teacher(db, user_id, classe_id):
        return True
    return is_class_responsable(db, user_id, classe_id)


def is_conversation_participant(db, user_id, conversation_id):
    return _one(db, "SELECT 1 FROM conversation_participants WHERE conversation_id=? AND utilisateur_id=?", (conversation_id, user_id))
