from app.models import (
    ASSIGNMENT_DOCUMENT_MODELS,
    AssignmentDocumentType,
    MietvertragDocument,
    MietbedingungenDocument,
    WohnungsgeberbescheinigungDocument,
)


def test_types_map_to_models():
    assert ASSIGNMENT_DOCUMENT_MODELS == {
        "mietvertrag": MietvertragDocument,
        "mietbedingungen": MietbedingungenDocument,
        "wohnungsgeberbescheinigung": WohnungsgeberbescheinigungDocument,
    }


def test_tables_are_correct():
    assert MietvertragDocument._meta.db_table == "mietvertrag_document"
    assert MietbedingungenDocument._meta.db_table == "mietbedingungen_document"
    assert WohnungsgeberbescheinigungDocument._meta.db_table == "wohnungsgeberbescheinigung_document"


def test_mietvertrag_has_signature_fields():
    fields = {f.name for f in MietvertragDocument._meta.get_fields()}
    assert {"renter_signed_at", "company_signed_at", "company_signed_by"} <= fields


def test_labels():
    assert AssignmentDocumentType.MIETVERTRAG.label == "Mietvertrag"
    assert AssignmentDocumentType.MIETBEDINGUNGEN.label == "Allgemeine Mietbedingungen"
    assert AssignmentDocumentType.WOHNUNGSGEBERBESCHEINIGUNG.label == "Wohnungsgeberbescheinigung"
