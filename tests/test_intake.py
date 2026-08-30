import json
from datetime import date

from app.deadlines import ServiceMethod
from app.intake import SummonsFields, extract_summons, needs_retake
from substrate.fakes import FakeModel


def _reply(**overrides) -> str:
    payload = {
        "case_number": "24UD001234",
        "court_branch": "Superior Court of California, County of Alameda",
        "plaintiff_name": "Ridgeline Property Management LLC",
        "served_on": "2026-08-03",
        "service_method": "personal",
        "confidence": 0.94,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_extracts_all_fields():
    fields = extract_summons(FakeModel([_reply()]), image=b"png")
    assert isinstance(fields, SummonsFields)
    assert fields.case_number == "24UD001234"
    assert fields.served_on == date(2026, 8, 3)
    assert fields.service_method is ServiceMethod.PERSONAL


def test_passes_the_image_to_the_model():
    model = FakeModel([_reply()])
    extract_summons(model, image=b"photo-bytes")
    assert model.calls[0]["images"] == [b"photo-bytes"]


def test_unreadable_fields_come_back_as_none_not_guesses():
    fields = extract_summons(FakeModel([_reply(case_number=None, confidence=0.3)]), b"png")
    assert fields.case_number is None
    assert fields.confidence == 0.3


def test_malformed_reply_yields_empty_fields_with_zero_confidence():
    fields = extract_summons(FakeModel(["I can't read this clearly"]), b"png")
    assert fields.case_number is None
    assert fields.confidence == 0.0


def test_invalid_date_is_dropped_rather_than_raising():
    fields = extract_summons(FakeModel([_reply(served_on="not-a-date")]), b"png")
    assert fields.served_on is None


def test_needs_retake_when_confidence_is_low():
    fields = SummonsFields("24UD1", "Alameda", "Acme", date(2026, 8, 3), ServiceMethod.PERSONAL, 0.4)
    request = needs_retake(fields)
    assert request is not None
    assert "low_confidence" == request.reason
    assert request.guidance


def test_needs_retake_when_the_service_date_is_missing():
    fields = SummonsFields("24UD1", "Alameda", "Acme", None, ServiceMethod.PERSONAL, 0.95)
    assert needs_retake(fields).reason == "missing_served_on"


def test_a_landlord_notice_is_not_mistaken_for_a_summons():
    """The shape a three-day notice to pay rent or quit actually produced.

    Run against a real § 1161 notice, the model returned the landlord as
    "plaintiff", the notice's own service date, personal service, and high
    confidence -- everything compute_response_deadline needs to produce a
    § 1167 countdown off a document filed before any case exists. No case
    number and no court name is what separates the two, so that is what is
    checked.
    """
    fields = SummonsFields(
        None, None, "Northgate Residential Partners, LLC",
        date(2026, 8, 10), ServiceMethod.PERSONAL, 0.95,
    )
    request = needs_retake(fields)
    assert request is not None
    assert request.reason == "not_a_summons"
    assert "case number" in request.guidance


def test_a_case_number_alone_is_enough_to_be_a_summons():
    """Photographed at an angle, the court-name box can be the part that is
    cut off. One of the two identifiers is enough -- only a court issues a
    document carrying either."""
    fields = SummonsFields("24UD1", None, "Acme", date(2026, 8, 3), ServiceMethod.PERSONAL, 0.95)
    assert needs_retake(fields) is None


def test_a_blurred_photo_is_told_to_retake_before_being_called_a_notice():
    """Ordering matters. A dark photo of a real summons reads as nulls too;
    telling that tenant they photographed the wrong document sends them
    looking for a paper they are already holding."""
    fields = SummonsFields(None, None, None, None, None, 0.2)
    assert needs_retake(fields).reason == "low_confidence"


def test_no_retake_needed_for_a_clean_read():
    fields = SummonsFields("24UD1", "Alameda", "Acme", date(2026, 8, 3), ServiceMethod.PERSONAL, 0.95)
    assert needs_retake(fields) is None


# --- Edge cases the brief's implementation does not cover ---


def test_valid_json_that_is_not_an_object_is_treated_as_malformed():
    # The model can return syntactically valid JSON that is not an object --
    # a bare string, a number, a list. A naive `.get()` on that would raise
    # AttributeError uncaught. This must degrade the same as any other
    # malformed reply: empty fields, zero confidence, never a crash.
    fields = extract_summons(FakeModel([json.dumps("just a plain string")]), b"png")
    assert fields == SummonsFields(None, None, None, None, None, 0.0)


def test_valid_json_array_is_treated_as_malformed():
    fields = extract_summons(FakeModel([json.dumps([1, 2, 3])]), b"png")
    assert fields.case_number is None
    assert fields.confidence == 0.0


def test_non_numeric_confidence_is_treated_as_zero_not_a_crash():
    # A confidence field that is present but not coercible to a number must
    # not raise -- it is treated as no usable confidence, which also means
    # needs_retake will ask for a retake rather than trusting an unscored read.
    fields = extract_summons(FakeModel([_reply(confidence="very confident")]), b"png")
    assert fields.confidence == 0.0


def test_extracted_fields_with_untrustworthy_confidence_still_trigger_a_retake():
    fields = extract_summons(FakeModel([_reply(confidence="very confident")]), b"png")
    request = needs_retake(fields)
    assert request is not None
    assert request.reason == "low_confidence"


def test_unknown_service_method_string_is_dropped_not_guessed():
    fields = extract_summons(FakeModel([_reply(service_method="certified mail carrier pigeon")]), b"png")
    assert fields.service_method is None


def test_missing_confidence_key_entirely_defaults_to_zero():
    reply = json.dumps(
        {
            "case_number": "24UD001234",
            "court_branch": "Alameda",
            "plaintiff_name": "Ridgeline",
            "served_on": "2026-08-03",
            "service_method": "personal",
        }
    )
    fields = extract_summons(FakeModel([reply]), b"png")
    assert fields.confidence == 0.0


def test_markdown_fenced_json_reply_is_still_parsed():
    fenced = "```json\n" + _reply() + "\n```"
    fields = extract_summons(FakeModel([fenced]), b"png")
    assert fields.case_number == "24UD001234"
