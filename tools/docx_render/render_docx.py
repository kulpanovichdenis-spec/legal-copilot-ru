#!/usr/bin/env python3
"""Render DOCX to page PNGs for visual QA without modifying the source file.

Windows uses Microsoft Word COM. Other platforms, or Windows when Word is
unavailable, use LibreOffice if ``soffice`` is on PATH. PDF pages are rendered
with pypdfium2, which is already part of the project's OCR dependency set.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pypdfium2 as pdfium


def _word_to_pdf(source: Path, pdf_path: Path) -> None:
    helper = Path(__file__).with_name("word_to_pdf.ps1")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-InputPath",
        str(source),
        "-OutputPath",
        str(pdf_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Word COM conversion failed: {detail}") from exc


def _soffice_to_pdf(source: Path, output_dir: Path) -> Path:
    executable = shutil.which("soffice")
    if not executable:
        raise RuntimeError("LibreOffice soffice is not available on PATH")
    try:
        subprocess.run(
            [executable, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(source)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"LibreOffice conversion failed: {detail}") from exc
    generated = output_dir / f"{source.stem}.pdf"
    if not generated.is_file():
        raise RuntimeError(f"LibreOffice did not create {generated}")
    return generated


def _convert_to_pdf(source: Path, pdf_path: Path) -> None:
    errors: list[str] = []
    if sys.platform == "win32":
        try:
            _word_to_pdf(source, pdf_path)
            return
        except Exception as exc:  # Word errors vary by installed Office build.
            errors.append(f"Word COM: {exc}")

    try:
        generated = _soffice_to_pdf(source, pdf_path.parent)
        if generated != pdf_path:
            shutil.move(str(generated), str(pdf_path))
        return
    except Exception as exc:
        errors.append(f"LibreOffice: {exc}")

    raise RuntimeError("; ".join(errors))


def render(source: Path, output_dir: Path, *, dpi: int, emit_pdf: bool) -> list[Path]:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise ValueError(f"Input must be an existing DOCX: {source}")
    if dpi < 72 or dpi > 600:
        raise ValueError("DPI must be between 72 and 600")

    output_dir.mkdir(parents=True, exist_ok=True)
    occupied = list(output_dir.glob("page-*.png"))
    output_pdf = output_dir / f"{source.stem}.pdf"
    if occupied or (emit_pdf and output_pdf.exists()):
        raise FileExistsError("Output directory already contains render artifacts; use a fresh directory")

    with tempfile.TemporaryDirectory(prefix="legal-copilot-docx-render-") as temp_name:
        temp_dir = Path(temp_name)
        temp_pdf = temp_dir / f"{source.stem}.pdf"
        _convert_to_pdf(source, temp_pdf)

        document = pdfium.PdfDocument(str(temp_pdf))
        pages: list[Path] = []
        try:
            scale = dpi / 72.0
            for index in range(len(document)):
                page = document[index]
                try:
                    image = page.render(scale=scale).to_pil()
                    page_path = output_dir / f"page-{index + 1}.png"
                    image.save(page_path, format="PNG")
                    pages.append(page_path)
                finally:
                    page.close()
        finally:
            document.close()

        if emit_pdf:
            shutil.copy2(temp_pdf, output_pdf)

    if not pages:
        raise RuntimeError("Renderer produced no page images")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a DOCX to page PNGs for visual QA")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--dpi", type=int, default=144)
    parser.add_argument("--emit-pdf", action="store_true")
    args = parser.parse_args()

    try:
        pages = render(args.input, args.output_dir, dpi=args.dpi, emit_pdf=args.emit_pdf)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: rendered {len(pages)} page(s) to {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
