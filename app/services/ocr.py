from __future__ import annotations

import base64
import os
import re
import logging
from pathlib import Path

import fitz
from openai import OpenAI

from music21 import converter


def _b64_data_url(mime: str, data: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"


def _sanitize_musicxml(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:xml)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("<?xml")
    if start != -1:
        text = text[start:]
    end = text.rfind("</score-partwise>")
    if end != -1:
        text = text[: end + len("</score-partwise>")].strip()
    return text


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


logger = logging.getLogger("uvicorn.error")


def pdf_to_png_pages(pdf_bytes: bytes, max_pages: int = 4, dpi: int = 200) -> list[bytes]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[bytes] = []
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=dpi)
        pages.append(pix.tobytes("png"))
    return pages


def pdf_to_image_pages(
    pdf_bytes: bytes,
    max_pages: int = 3,
    dpi: int = 150,
    jpeg_quality: int = 70,
) -> list[tuple[str, bytes]]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[tuple[str, bytes]] = []
    for i in range(min(len(doc), max_pages)):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=dpi)
        images.append(("image/jpeg", pix.tobytes("jpeg", jpg_quality=jpeg_quality)))
    return images


def omr_to_musicxml(input_path: Path, output_path: Path) -> Path:
    suffix = input_path.suffix.lower()
    data = input_path.read_bytes()

    images: list[tuple[str, bytes]] = []
    if suffix == ".pdf":
        max_pages = _env_int("OPENAI_OCR_MAX_PAGES", 3)
        dpi = _env_int("OPENAI_OCR_DPI", 150)
        jpeg_quality = _env_int("OPENAI_OCR_JPEG_QUALITY", 70)
        images = pdf_to_image_pages(data, max_pages=max_pages, dpi=dpi, jpeg_quality=jpeg_quality)
        logger.info("OCR/OMR PDF: pages=%s dpi=%s quality=%s bytes=%s", max_pages, dpi, jpeg_quality, len(data))
    elif suffix in (".png", ".jpg", ".jpeg", ".webp"):
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        images.append((mime, data))
        logger.info("OCR/OMR IMG: mime=%s bytes=%s", mime, len(data))
    else:
        raise ValueError("Formato não suportado para OCR/OMR")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY não configurada para OCR/OMR")

    model = os.environ.get("OPENAI_OCR_MODEL", "gpt-4.1-mini")
    timeout_s = float(os.environ.get("OPENAI_OCR_TIMEOUT", "180"))
    client = OpenAI(api_key=api_key, timeout=timeout_s)

    prompt = (
        "Você é um sistema de OMR (Optical Music Recognition). "
        "Converta a(s) imagem(ns) de partitura para MusicXML no formato score-partwise. "
        "Regras: retornar APENAS o XML (sem markdown, sem explicações). "
        "Incluir todas as páginas fornecidas como uma única partitura. "
        "Se houver múltiplas vozes/partes, preserve-as."
    )

    content: list[dict] = [{"type": "text", "text": prompt}]
    for mime, img in images:
        content.append({"type": "image_url", "image_url": {"url": _b64_data_url(mime, img)}})

    logger.info("OCR/OMR calling OpenAI: model=%s images=%s timeout=%ss", model, len(images), timeout_s)
    try:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=0,
            )
        except Exception as e:
            msg = str(e)
            if "Unsupported value: 'temperature'" in msg or "unsupported_value" in msg:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                )
            else:
                raise
    except Exception as e:
        logger.exception("OCR/OMR OpenAI error")
        raise ValueError(f"Falha no OCR/OMR via OpenAI: {e}") from e

    text = ""
    for choice in resp.choices or []:
        if choice.message and choice.message.content:
            text = choice.message.content
            break
    logger.info("OCR/OMR OpenAI response chars=%s", len(text or ""))

    xml = _sanitize_musicxml(text)
    if not xml.startswith("<?xml"):
        raise ValueError("OCR/OMR não retornou MusicXML válido")

    try:
        converter.parseData(xml)
    except Exception as e:
        raise ValueError("OCR/OMR retornou MusicXML inválido para parsing") from e

    output_path.write_text(xml, encoding="utf-8")
    return output_path


__all__ = ["omr_to_musicxml", "pdf_to_png_pages", "pdf_to_image_pages"]
