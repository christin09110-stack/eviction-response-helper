import json
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from app.intake import SummonsFields
from substrate.telemetry import span

FORM_SPEC = json.loads(Path("corpus/ud-105-fields.json").read_text())

DISCLAIMER = (
    "PREPARED DRAFT - NOT FILED. Review every line before filing. "
    "This was prepared by an automated tool, not a lawyer."
)


@dataclass(frozen=True)
class DefenseAssessment:
    field_id: str
    selected: bool
    basis: str


def assess_defenses(facts: dict) -> list[DefenseAssessment]:
    """Rules-based on purpose. A hallucinated affirmative defence in a filed
    Answer is the worst failure this product could have."""
    habitability = bool(facts.get("reported_disrepair")) and bool(facts.get("landlord_notified"))
    complained_on, notice_on = facts.get("complained_on"), facts.get("notice_served_on")
    retaliation = bool(complained_on and notice_on and complained_on < notice_on)
    rent_accepted = bool(facts.get("rent_accepted_after_notice"))
    defective_notice = bool(facts.get("notice_defective"))

    return [
        DefenseAssessment(
            "defense_habitability", habitability,
            "Disrepair was reported to the landlord before the notice." if habitability else "",
        ),
        DefenseAssessment(
            "defense_retaliation", retaliation,
            "A complaint was made before the notice was served." if retaliation else "",
        ),
        DefenseAssessment(
            "defense_notice", defective_notice,
            "The notice was defective or improperly served." if defective_notice else "",
        ),
        DefenseAssessment(
            "defense_rent_accepted", rent_accepted,
            "Rent was accepted after the notice period expired." if rent_accepted else "",
        ),
    ]


def _label(field_id: str) -> str:
    return next(f["label"] for f in FORM_SPEC["fields"] if f["id"] == field_id)


def draft_ud105(
    fields: SummonsFields,
    defendant_name: str,
    assessments: list[DefenseAssessment],
    out_path: str,
) -> str:
    with span("navigator.draft_form", form=FORM_SPEC["form_id"]):
        # pageCompression=0: this reportlab version (5.0.1) defaults to a
        # FlateDecode-compressed content stream, which would make the raw
        # bytes assertions below (and any future text-in-PDF verification)
        # unable to find plain text in the file. The brief's claim that
        # "reportlab writes uncompressed text streams by default" does not
        # hold for this installed version -- verified empirically, the
        # default stream carries `/Filter [ /ASCII85Decode /FlateDecode ]`.
        page = canvas.Canvas(out_path, pagesize=LETTER, pageCompression=0)
        _, height = LETTER
        y = height - 72

        page.setFont("Helvetica-Bold", 14)
        page.drawString(72, y, f"{FORM_SPEC['form_id']} — {FORM_SPEC['title']}")
        y -= 28

        page.setFont("Helvetica", 10)
        for label, value in [
            ("Case number", fields.case_number or ""),
            ("Court", fields.court_branch or ""),
            ("Plaintiff", fields.plaintiff_name or ""),
            ("Defendant", defendant_name),
        ]:
            page.drawString(72, y, f"{label}: {value}")
            y -= 16

        y -= 12
        page.setFont("Helvetica-Bold", 11)
        page.drawString(72, y, "Affirmative defenses asserted")
        y -= 18

        page.setFont("Helvetica", 10)
        selected = [a for a in assessments if a.selected]
        if not selected:
            page.drawString(86, y, "None asserted.")
            y -= 16
        for assessment in selected:
            page.drawString(86, y, f"[X] {_label(assessment.field_id)}")
            y -= 14
            page.setFont("Helvetica-Oblique", 9)
            page.drawString(102, y, assessment.basis)
            page.setFont("Helvetica", 10)
            y -= 18

        page.setFont("Helvetica-Bold", 9)
        page.drawString(72, 54, DISCLAIMER)
        page.save()

    return out_path
