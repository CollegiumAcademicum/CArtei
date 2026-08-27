from app.models import (
    ASSIGNMENT_DOCUMENT_MODELS,
    AssignmentDocumentType,
    WohnungsgeberbescheinigungDocument,
)


def test_types_map_to_models():
    # Mietvertrag/Mietbedingungen moved to per-tenant documents (DOCUMENT_MODELS);
    # only Wohnungsgeberbescheinigung stays keyed on the room assignment.
    assert ASSIGNMENT_DOCUMENT_MODELS == {
        "wohnungsgeberbescheinigung": WohnungsgeberbescheinigungDocument,
    }


def test_tables_are_correct():
    assert WohnungsgeberbescheinigungDocument._meta.db_table == "wohnungsgeberbescheinigung_document"


def test_labels():
    assert AssignmentDocumentType.WOHNUNGSGEBERBESCHEINIGUNG.label == "Wohnungsgeberbescheinigung"
