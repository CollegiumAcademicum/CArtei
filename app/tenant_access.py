from collections import namedtuple

from django.conf import settings

Field = namedtuple("Field", "name label visible_to editable_by")
Section = namedtuple("Section", "key title fields")

SYSTEM_ID_FIELDS = frozenset({"intranet_username", "intranet_uuid"})

# Role shorthands
_PUBLIC = frozenset({"public"})
_OWNER = frozenset({"owner"})
_OWN_MV = frozenset({"owner", "mietverwaltung"})
_MV = frozenset({"mietverwaltung"})
_ADMIN = frozenset({"admin"})

def _f(name, label, visible_to, editable_by):
    return Field(name, label, frozenset(visible_to), frozenset(editable_by))


SECTIONS = [
    Section("personal", "Persönliche Informationen", [
        _f("preferred_name", "Rufname", _PUBLIC, _OWNER),
        _f("pronouns", "Pronomen", _PUBLIC, _OWNER),
        _f("first_name", "Vorname", _OWN_MV, _ADMIN),
        _f("last_name", "Nachname", _OWN_MV, _ADMIN),
        _f("email", "E-Mail", _OWN_MV, _OWN_MV),
        _f("phone", "Telefon", _OWN_MV, _OWN_MV),
        _f("is_flinta", "FLINTA", _OWN_MV, _OWN_MV),
        _f("mailbox_list_opt_in", "Ich möchte, dass mein Name bei den Briefkästen steht", _OWN_MV, _OWN_MV),
        _f("date_of_birth", "Geburtsdatum", _OWN_MV, _MV),
        _f("barrier_free_needed", "Barrierefreiheit benötigt", _OWN_MV, _MV),
        _f("soli_miete_wunsch", "Soli-Miete-Wunsch", _OWNER, _OWNER),
    ]),
    Section("housing", "Wohnen", [
        _f("move_in", "Ersteinzug", _OWN_MV, _MV),
        _f("move_out", "Auszug", _OWN_MV, _MV),
    ]),
    Section("legal", "Rechtliches", [
        _f("data_priv_signed_at", "Datenschutz unterschrieben", _OWN_MV, _MV),
        _f("photo_allowance_signed_at", "Fotoerlaubnis unterschrieben", _OWN_MV, _MV),
        _f("comments", "Admin-Kommentare", _ADMIN, _ADMIN),
    ]),
]

_OWN_MV_ADMIN = frozenset({"owner", "mietverwaltung", "admin"})
_MV_ADMIN = frozenset({"mietverwaltung", "admin"})
_OWN_CLUSTER_ADMIN = frozenset({"owner", "cluster", "admin"})
_CLUSTER_ADMIN = frozenset({"cluster", "admin"})

# Non-field access rules shown in the permission matrix (not form fields).
RESOURCE_SECTIONS = [
    Section("rooms", "Zimmer & Mietverträge", [
        _f("room_assignments_view", "Zimmer-Zuweisungen (aktuell + vergangen)", _OWN_MV_ADMIN, _MV_ADMIN),
        _f("room_assignments_new", "Neues Zimmer zuweisen", frozenset(), _MV_ADMIN),
    ]),
    Section("engagement", "AG-Engagement & Cluster-Notizen", [
        _f("engagement_results", "AG-Abfrage-Ergebnisse", _OWN_CLUSTER_ADMIN, frozenset()),
        _f("cluster_notes", "Cluster-Notizen", _CLUSTER_ADMIN, _CLUSTER_ADMIN),
    ]),
]

# All Tenant columns that any role may edit (admin override edits these too).
EDITABLE_COLUMNS = sorted({
    f.name for s in SECTIONS for f in s.fields if f.editable_by
})

_ALL_FIELDS = [f for s in SECTIONS for f in s.fields]


def global_roles(user) -> set[str]:
    """Roles a user holds regardless of which tenant they look at — everything
    except 'owner', which is per-self. Used to gate columns in the tenant list."""
    roles = {"public"}
    group_names = set(user.groups.values_list("name", flat=True))
    if "admins" in group_names:
        roles.add("admin")
    for role, cns in settings.TENANT_ROLE_GROUPS.items():
        if group_names.intersection(cns):
            roles.add(role)
    return roles


def viewer_roles(user, tenant, current_tenant) -> set[str]:
    roles = global_roles(user)
    if current_tenant is not None and current_tenant.pk == tenant.pk:
        roles.add("owner")
    return roles


def visible_fields(roles: set[str]) -> set[str]:
    if "admin" in roles:
        return {f.name for f in _ALL_FIELDS}
    r = frozenset(roles)
    return {f.name for f in _ALL_FIELDS if r & f.visible_to}


def editable_fields(roles: set[str]) -> set[str]:
    if "admin" in roles:
        return {f.name for f in _ALL_FIELDS} - SYSTEM_ID_FIELDS
    r = frozenset(roles)
    return {f.name for f in _ALL_FIELDS if r & f.editable_by}
