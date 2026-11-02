import pytest
from sqlalchemy.exc import OperationalError

from app.errors import AppError
from app.schemas import ErrorCode
from app.services import reviews

from .conftest import (
    ALL_KEYS,
    API,
    confirm,
    import_fixture,
    patch_fields,
    verify,
    verify_all,
)

AMOUNTS_X10 = {"investment_amount": "480000.00", "management_fee": "20000.00", "total_due": "500000.00"}


def field(detail, key):
    return next(f for f in detail["fields"] if f["key"] == key)


def rule(detail, rule_id):
    return next(r for r in detail["rules"] if r["id"] == rule_id)


def event_types(detail):
    return [e["event_type"] for e in detail["audit_events"]]


def get(client, doc):
    return client.get(f"{API}/documents/{doc['id']}").json()


def error(response):
    return response.json()["error"]


# --- editing ---------------------------------------------------------------------------------


def test_correcting_the_total_fixes_the_rule_but_does_not_confirm(review_client):
    doc = import_fixture(review_client, "amount-error")
    response = patch_fields(review_client, doc, {"total_due": "50000.00"}, reason="Total checked against the PDF.")
    assert response.status_code == 200
    updated = response.json()

    assert updated["version"] == 2 and updated["status"] == "REVIEW_REQUIRED"
    assert rule(updated, "R002_TOTAL")["status"] == "PASS"
    total = field(updated, "total_due")
    assert total["initial_extracted_value"] == "500000.00"
    assert total["current_value"] == "50000.00" and total["modified"] is True
    assert total["source_value"] == "50000.00" and total["source_text"] == "50,000.00"
    assert all(f["verified"] is False for f in updated["fields"])

    assert event_types(updated) == ["IMPORTED", "FIELDS_UPDATED"]
    event = updated["audit_events"][1]
    assert event["actor"] == "local-reviewer" and event["document_version"] == 2
    assert event["payload"]["reason"] == "Total checked against the PDF."
    assert event["payload"]["changes"] == [
        {"key": "total_due", "before": "500000.00", "after": "50000.00"}
    ]
    assert event["created_at"].endswith("Z")


def test_source_evidence_and_initial_values_survive_every_edit(review_client):
    doc = import_fixture(review_client, "amount-error")
    before = {f["key"]: (f["source_text"], f["source_value"], f["evidence"], f["initial_extracted_value"]) for f in doc["fields"]}
    doc = patch_fields(review_client, doc, {"total_due": "50000.00", "fund_name": "Renamed Fund"}).json()
    doc = patch_fields(review_client, doc, {"total_due": "1.00"}).json()
    after = {f["key"]: (f["source_text"], f["source_value"], f["evidence"], f["initial_extracted_value"]) for f in doc["fields"]}
    assert after == before


def test_failing_business_rules_do_not_block_saving(review_client):
    doc = import_fixture(review_client, "normal")
    saved = patch_fields(review_client, doc, {"total_due": "49000.00"}).json()
    assert field(saved, "total_due")["current_value"] == "49000.00"
    assert rule(saved, "R002_TOTAL")["status"] == "FAIL"


def test_values_are_normalised_and_blank_means_null(review_client):
    doc = import_fixture(review_client, "normal")
    saved = patch_fields(review_client, doc, {"management_fee": "2,500", "due_date": "  "}).json()
    assert field(saved, "management_fee")["current_value"] == "2500.00"
    assert field(saved, "due_date")["current_value"] is None
    assert rule(saved, "R001_REQUIRED")["status"] == "FAIL"
    saved = patch_fields(review_client, saved, {"fund_name": None}).json()
    assert field(saved, "fund_name")["current_value"] is None


def test_one_bad_value_rejects_the_whole_batch(review_client):
    doc = import_fixture(review_client, "normal")
    response = patch_fields(review_client, doc, {"fund_name": "New Name", "total_due": "1.001"})
    assert response.status_code == 422
    assert error(response)["code"] == "INVALID_FIELD_VALUE"
    assert [e["key"] for e in error(response)["details"]["errors"]] == ["total_due"]
    unchanged = get(review_client, doc)
    assert unchanged["version"] == 1
    assert field(unchanged, "fund_name")["current_value"] == "Example Growth Fund I"
    assert event_types(unchanged) == ["IMPORTED"]


@pytest.mark.parametrize("bad", ["1.001", "-1", "1e3", "NaN", "12,34", "$5", "1,000,000,000.00"])
def test_amount_boundaries_are_enforced_at_the_api(review_client, bad):
    doc = import_fixture(review_client, "normal")
    response = patch_fields(review_client, doc, {"total_due": bad})
    assert response.status_code == 422 and error(response)["code"] == "INVALID_FIELD_VALUE"


def test_cents_are_added_exactly(review_client):
    doc = import_fixture(review_client, "normal")
    saved = patch_fields(
        review_client, doc, {"investment_amount": "0.10", "management_fee": "0.20", "total_due": "0.30"}
    ).json()
    assert rule(saved, "R002_TOTAL")["status"] == "PASS"


def test_malformed_requests_are_invalid_request(review_client):
    doc = import_fixture(review_client, "normal")
    url = f"{API}/documents/{doc['id']}/fields"
    for body in (
        {},
        {"expected_version": 1, "changes": [], "reason": "r"},
        {"expected_version": 1, "changes": [{"key": "bogus", "value": "x"}], "reason": "r"},
        {"expected_version": 1, "changes": [{"key": "total_due", "value": "1"}], "reason": "  "},
        {"expected_version": "1", "changes": [{"key": "total_due", "value": "1"}], "reason": "r"},
    ):
        response = review_client.patch(url, json=body)
        assert response.status_code == 422 and error(response)["code"] == "INVALID_REQUEST", body


def test_unknown_document_is_404_for_every_write(review_client):
    ghost = {"id": "00000000-0000-4000-8000-000000000000", "version": 1}
    assert patch_fields(review_client, ghost, {"total_due": "1.00"}).status_code == 404
    assert verify(review_client, ghost, "total_due").status_code == 404
    assert confirm(review_client, ghost).status_code == 404


# --- verification and confirmation ------------------------------------------------------------


def test_six_explicit_checks_then_confirmation(review_client):
    doc = import_fixture(review_client, "normal")
    doc = verify_all(review_client, doc)
    assert doc["version"] == 7 and doc["status"] == "REVIEW_REQUIRED"
    assert all(f["verified"] and f["verified_by"] == "local-reviewer" and f["verified_at"] for f in doc["fields"])

    confirmed = confirm(review_client, doc)
    assert confirmed.status_code == 200
    detail = confirmed.json()
    assert detail["status"] == "CONFIRMED" and detail["version"] == 8
    assert detail["confirmation"]["confirmed_by"] == "local-reviewer"
    assert detail["confirmation"]["confirmed_at"].endswith("Z")
    last = detail["audit_events"][-1]
    assert last["event_type"] == "CONFIRMED" and last["document_version"] == 8
    assert last["payload"]["ruleset_version"] == "v1"
    assert [r["status"] for r in last["payload"]["rules"]] == ["PASS", "PASS", "PASS"]

    assert get(review_client, detail) == detail  # persisted, not just returned


def test_full_correction_flow_from_the_preset_error(review_client):
    doc = import_fixture(review_client, "amount-error")
    doc = patch_fields(review_client, doc, {"total_due": "50000.00"}).json()
    doc = verify_all(review_client, doc)
    done = confirm(review_client, doc).json()
    assert done["status"] == "CONFIRMED"
    assert field(done, "total_due")["initial_extracted_value"] == "500000.00"


def test_missing_extraction_is_fixed_by_the_reviewer(review_client):
    doc = import_fixture(review_client, "missing-extraction")
    assert verify(review_client, doc, "due_date").status_code == 409  # nothing to check yet
    doc = patch_fields(review_client, doc, {"due_date": "2026-11-24"}).json()
    doc = verify_all(review_client, doc)
    assert confirm(review_client, doc).json()["status"] == "CONFIRMED"


def test_editing_a_confirmed_document_revokes_the_confirmation(review_client):
    doc = import_fixture(review_client, "normal")
    doc = confirm(review_client, verify_all(review_client, doc)).json()
    assert doc["version"] == 8

    edited = patch_fields(review_client, doc, {"management_fee": "2100.00"}, reason="Fee was revised.").json()
    assert edited["version"] == 9  # one actual edit = one version, revocation included
    assert edited["status"] == "REVIEW_REQUIRED"
    assert edited["confirmation"] is None
    assert all(f["verified"] is False and f["verified_at"] is None for f in edited["fields"])
    assert rule(edited, "R002_TOTAL")["status"] == "FAIL"
    assert event_types(edited)[-3:] == ["CONFIRMED", "FIELDS_UPDATED", "CONFIRMATION_REVOKED"]
    assert edited["audit_events"][-1]["document_version"] == 9
    assert "CONFIRMED" in event_types(edited)  # the old confirmation event is kept


def test_any_actual_edit_clears_all_six_checks_even_before_confirmation(review_client):
    doc = import_fixture(review_client, "normal")
    doc = verify_all(review_client, doc, ["fund_name", "currency", "due_date"])
    edited = patch_fields(review_client, doc, {"fund_name": "Another Fund"}).json()
    assert all(f["verified"] is False for f in edited["fields"])


def test_confirm_is_refused_when_rules_fail(review_client):
    doc = import_fixture(review_client, "amount-error")
    doc = verify_all(review_client, doc)
    response = confirm(review_client, doc)
    assert response.status_code == 409
    assert error(response)["code"] == "REVIEW_BLOCKED"
    failing = {r["id"]: r["status"] for r in error(response)["details"]["rules"]}
    assert failing == {"R002_TOTAL": "FAIL"}
    assert get(review_client, doc)["status"] == "REVIEW_REQUIRED"


def test_confirm_is_refused_until_every_field_is_checked(review_client):
    doc = import_fixture(review_client, "normal")
    response = confirm(review_client, doc)
    assert response.status_code == 409 and error(response)["code"] == "REVIEW_INCOMPLETE"
    assert error(response)["details"]["unverified"] == ALL_KEYS

    doc = verify_all(review_client, doc, ALL_KEYS[:5])
    response = confirm(review_client, doc)
    assert error(response)["code"] == "REVIEW_INCOMPLETE"
    assert error(response)["details"]["unverified"] == ["total_due"]


def test_scaled_amounts_pass_the_rules_but_still_need_a_human(review_client):
    doc = import_fixture(review_client, "normal")
    scaled = patch_fields(review_client, doc, AMOUNTS_X10).json()
    assert [r["status"] for r in scaled["rules"]] == ["PASS", "PASS", "PASS"]
    assert scaled["status"] == "REVIEW_REQUIRED"
    assert all(f["verified"] is False for f in scaled["fields"])
    response = confirm(review_client, scaled)
    assert response.status_code == 409 and error(response)["code"] == "REVIEW_INCOMPLETE"


def test_missing_evidence_blocks_verification_and_confirmation(review_client):
    doc = import_fixture(review_client, "missing-source")
    assert error(verify(review_client, doc, "due_date"))["code"] == "REVIEW_BLOCKED"
    # Typing a value in does not conjure a source location.
    doc = patch_fields(review_client, doc, {"due_date": "2026-11-30"}).json()
    assert field(doc, "due_date")["evidence"] is None
    blocked = verify(review_client, doc, "due_date")
    assert blocked.status_code == 409 and error(blocked)["code"] == "REVIEW_BLOCKED"
    doc = verify_all(review_client, doc, [k for k in ALL_KEYS if k != "due_date"])
    response = confirm(review_client, doc)
    assert response.status_code == 409
    assert error(response)["code"] in {"REVIEW_BLOCKED", "REVIEW_INCOMPLETE"}
    assert get(review_client, doc)["status"] == "REVIEW_REQUIRED"


def test_a_check_can_be_withdrawn_and_is_recorded(review_client):
    doc = import_fixture(review_client, "normal")
    doc = verify(review_client, doc, "total_due").json()
    doc = verify(review_client, doc, "total_due", False).json()
    total = field(doc, "total_due")
    assert total["verified"] is False and total["verified_at"] is None and total["verified_by"] is None
    kinds = event_types(doc)
    assert kinds == ["IMPORTED", "FIELD_VERIFICATION_CHANGED", "FIELD_VERIFICATION_CHANGED"]
    assert [e["payload"]["verified"] for e in doc["audit_events"][1:]] == [True, False]
    assert doc["audit_events"][1]["payload"]["field_key"] == "total_due"


def test_checks_cannot_be_changed_on_a_confirmed_document(review_client):
    doc = import_fixture(review_client, "normal")
    doc = confirm(review_client, verify_all(review_client, doc)).json()
    for flag in (True, False):
        response = verify(review_client, doc, "total_due", flag)
        assert response.status_code == 409 and error(response)["code"] == "DOCUMENT_CONFIRMED"
    assert get(review_client, doc) == doc


def test_confirm_accepts_nothing_but_the_version(review_client):
    doc = import_fixture(review_client, "amount-error")
    response = review_client.post(
        f"{API}/documents/{doc['id']}/confirm",
        json={"expected_version": 1, "ignore_errors": True, "fields": {"total_due": "50000.00"}},
    )
    assert response.status_code == 422 and error(response)["code"] == "INVALID_REQUEST"


# --- confirm needs the original ----------------------------------------------------------


def test_confirm_checks_the_original_file(review_client, settings):
    doc = import_fixture(review_client, "normal")
    doc = verify_all(review_client, doc)
    stored = settings.originals_dir / f"{doc['sha256']}.pdf"
    original = stored.read_bytes()

    stored.write_bytes(original + b"tampered")
    response = confirm(review_client, doc)
    assert response.status_code == 409 and error(response)["code"] == "SOURCE_INTEGRITY_MISMATCH"

    stored.unlink()
    response = confirm(review_client, doc)
    assert response.status_code == 409 and error(response)["code"] == "SOURCE_UNAVAILABLE"
    assert get(review_client, doc)["status"] == "REVIEW_REQUIRED"

    stored.write_bytes(original)
    assert confirm(review_client, doc).status_code == 200


# --- versions and idempotency -----------------------------------------------------------------


def test_stale_versions_are_rejected_by_every_write(review_client):
    doc = import_fixture(review_client, "amount-error")
    newer = patch_fields(review_client, doc, {"total_due": "50000.00"}).json()  # now version 2

    for response in (
        patch_fields(review_client, doc, {"fund_name": "Late Edit"}),
        verify(review_client, doc, "fund_name"),
        confirm(review_client, doc),
    ):
        assert response.status_code == 409
        assert error(response)["code"] == "VERSION_CONFLICT"
        assert error(response)["details"] == {"expected_version": 1, "actual_version": 2}
    assert get(review_client, doc) == newer


def test_version_conflict_beats_idempotent_confirm(review_client):
    doc = import_fixture(review_client, "normal")
    confirmed = confirm(review_client, verify_all(review_client, doc)).json()
    stale = confirm(review_client, confirmed, version=confirmed["version"] - 1)
    assert stale.status_code == 409 and error(stale)["code"] == "VERSION_CONFLICT"


def test_repeating_an_operation_changes_neither_version_nor_history(review_client):
    doc = import_fixture(review_client, "normal")

    same = patch_fields(review_client, doc, {"total_due": "50,000"}).json()  # normalises to the same value
    assert same == doc

    once = verify(review_client, doc, "total_due").json()
    twice = verify(review_client, once, "total_due").json()
    assert twice == once and twice["version"] == 2
    noop_edit = patch_fields(review_client, once, {"total_due": "50000.00"}).json()
    assert field(noop_edit, "total_due")["verified"] is True  # a no-op edit keeps checks

    withdrawn_twice = verify(review_client, verify(review_client, once, "total_due", False).json(), "total_due", False).json()
    assert withdrawn_twice["version"] == 3

    done = verify_all(review_client, withdrawn_twice)
    first = confirm(review_client, done).json()
    again = confirm(review_client, first)
    assert again.status_code == 200 and again.json() == first
    assert event_types(first).count("CONFIRMED") == 1


# --- failures leave nothing half-written ------------------------------------------------------


def snapshot(client, doc):
    return client.get(f"{API}/documents/{doc['id']}").json()


@pytest.mark.parametrize("operation", ["patch", "verify", "confirm"])
def test_a_failure_while_writing_history_rolls_everything_back(review_client, monkeypatch, operation):
    doc = import_fixture(review_client, "normal")
    if operation == "confirm":
        doc = verify_all(review_client, doc)
    before = snapshot(review_client, doc)

    def boom(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("disk I/O error"))

    monkeypatch.setattr(reviews, "add_event", boom)
    if operation == "patch":
        response = patch_fields(review_client, doc, {"total_due": "49000.00"})
    elif operation == "verify":
        response = verify(review_client, doc, "total_due")
    else:
        response = confirm(review_client, doc)
    monkeypatch.undo()

    assert response.status_code == 500 and error(response)["code"] == "STORAGE_ERROR"
    assert snapshot(review_client, doc) == before


def test_a_failed_revocation_restores_the_confirmed_state(review_client, monkeypatch):
    doc = import_fixture(review_client, "normal")
    doc = confirm(review_client, verify_all(review_client, doc)).json()
    real = reviews.add_event
    calls = []

    def fail_second(session, document, event_type, payload):
        calls.append(event_type)
        if len(calls) == 2:  # FIELDS_UPDATED written, CONFIRMATION_REVOKED fails
            raise OperationalError("INSERT", {}, Exception("disk I/O error"))
        return real(session, document, event_type, payload)

    monkeypatch.setattr(reviews, "add_event", fail_second)
    response = patch_fields(review_client, doc, {"management_fee": "2100.00"})
    monkeypatch.undo()
    assert response.status_code == 500
    assert snapshot(review_client, doc) == doc
    assert doc["status"] == "CONFIRMED"


def test_services_raise_app_errors_when_called_directly(review_client, session_factory, settings):
    doc = import_fixture(review_client, "normal")
    with session_factory() as session:
        with pytest.raises(AppError) as exc:
            reviews.confirm_document(doc["id"], doc["version"], session, settings)
    assert exc.value.code is ErrorCode.REVIEW_INCOMPLETE
