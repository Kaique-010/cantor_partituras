from app.schemas import SingRequest


def test_sing_request_accepts_valid_voice() -> None:
    payload = SingRequest(voice="tenor")
    assert payload.voice == "tenor"


def test_omr_sanitize_removes_code_fences() -> None:
    from app.services.ocr import _sanitize_musicxml

    raw = "```xml\n<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<score-partwise></score-partwise>\n```"
    assert _sanitize_musicxml(raw).startswith("<?xml")


def test_omr_sanitize_keeps_partwise_end() -> None:
    from app.services.ocr import _sanitize_musicxml

    raw = "<?xml version=\"1.0\"?><score-partwise></score-partwise> trailing"
    assert _sanitize_musicxml(raw).endswith("</score-partwise>")
