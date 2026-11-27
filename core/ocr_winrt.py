from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import pymupdf

from core.config import get_ocr_cache_dir

_PS_OCR_WORKER_SCRIPT = r"""
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null

$lang = [Windows.Globalization.Language]::new("ko")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    Write-Output '{"error":"WinRT OCR engine unavailable"}'
    exit 1
}

Write-Output '{"ready":true}'
[Console]::Out.Flush()

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    $path = $line.Trim()
    if ($path -eq "__EXIT__") { break }
    if ($path -eq "") { continue }
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines = @()
        foreach ($l in $res.Lines) { $lines += $l.Text }
        $joined = ($lines -join "`n")
        $stream.Dispose()
        $obj = @{ path = $path; text = $joined; ok = $true }
        Write-Output ($obj | ConvertTo-Json -Compress)
    } catch {
        $obj = @{ path = $path; text = ""; ok = $false; error = $_.Exception.Message }
        Write-Output ($obj | ConvertTo-Json -Compress)
    }
    [Console]::Out.Flush()
}
"""


def postprocess_ocr_text(text: str) -> str:
    """Clean common Korean scan OCR spacing and punctuation artifacts."""
    if not text:
        return ""
    text = text.replace("\x01", " ").replace("\r\n", "\n").replace("\r", "\n")
    # Fix spaced year/date digits like "2 0 1 2 년" -> "2012년"
    text = re.sub(r"(?<=\d)\s+(?=\d\s*[년월일조장편호항])", "", text)
    text = re.sub(r"(\d)\s+(\d)\s+(\d)\s+(\d)\s*년", r"\1\2\3\4년", text)
    # Normalize "제 10 조" -> "제10조" (keeps spacing after 조)
    text = re.sub(r"제\s*(\d+)\s*([편장절조항관])", r"제\1\2", text)
    # Normalize "문 10 ." -> "문 10."
    text = re.sub(r"문\s*(\d+)\s*\.", r"문 \1.", text)
    # Collapse excessive spaces on each line
    lines = [re.sub(r"[ \t]{2,}", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]


def _run_ps_ocr_batch(script_path: Path, image_paths: list[Path]) -> dict[str, str]:
    """Spawn one persistent PowerShell WinRT worker and process a slice of PNGs."""
    results: dict[str, str] = {}
    if not image_paths:
        return results

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    assert proc.stdin is not None and proc.stdout is not None

    ready_line = proc.stdout.readline().strip()
    if not ready_line or '"ready":true' not in ready_line:
        err = proc.stderr.read() if proc.stderr else ready_line
        proc.kill()
        raise RuntimeError(f"WinRT OCR worker failed to start: {err}")

    try:
        for img in image_paths:
            proc.stdin.write(str(img) + "\n")
            proc.stdin.flush()
            out_line = proc.stdout.readline().strip()
            if not out_line:
                continue
            try:
                data = json.loads(out_line)
                results[str(img)] = postprocess_ocr_text(data.get("text", ""))
            except json.JSONDecodeError:
                results[str(img)] = ""
        proc.stdin.write("__EXIT__\n")
        proc.stdin.flush()
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return results


def ocr_pdf_pages(
    pdf_path: Path,
    page_numbers_1based: list[int],
    dpi: int = 260,
    workers: int = 6,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict[int, str]:
    """OCR specified 1-based pages of a PDF using persistent WinRT Korean OCR workers with disk cache."""
    if not page_numbers_1based:
        return {}

    cache_key = f"{_file_sha1(pdf_path)}_dpi{dpi}"
    cache_file = get_ocr_cache_dir() / f"{cache_key}.json"
    cached: dict[str, str] = {}
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cached = {}

    results: dict[int, str] = {}
    missing: list[int] = []
    for pno in page_numbers_1based:
        k = str(pno)
        if k in cached and cached[k] is not None:
            results[pno] = cached[k]
        else:
            missing.append(pno)

    total = len(page_numbers_1based)
    done_count = len(results)
    if progress_cb and done_count > 0:
        progress_cb(done_count, total, f"OCR 캐시 {done_count}/{total}쪽 불러옴")

    if not missing:
        return results

    with tempfile.TemporaryDirectory(prefix="church_ocr_") as tmp:
        tmp_dir = Path(tmp)
        script_path = tmp_dir / "winrt_ocr_worker.ps1"
        script_path.write_text(_PS_OCR_WORKER_SCRIPT, encoding="utf-8-sig")

        # Render missing pages in batches of 36 to keep disk usage modest
        batch_size = 36
        doc = pymupdf.open(str(pdf_path))
        try:
            for start in range(0, len(missing), batch_size):
                chunk_pages = missing[start : start + batch_size]
                img_to_pno: dict[str, int] = {}
                img_paths: list[Path] = []
                for pno in chunk_pages:
                    page = doc[pno - 1]
                    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
                    img_path = tmp_dir / f"p_{pno:04d}.png"
                    pix.save(str(img_path))
                    img_paths.append(img_path)
                    img_to_pno[str(img_path)] = pno

                n_workers = max(1, min(workers, len(img_paths)))
                slices: list[list[Path]] = [img_paths[i::n_workers] for i in range(n_workers)]
                slices = [s for s in slices if s]

                with ThreadPoolExecutor(max_workers=len(slices)) as ex:
                    futs = [ex.submit(_run_ps_ocr_batch, script_path, sl) for sl in slices]
                    for fut in as_completed(futs):
                        part = fut.result()
                        for img_str, txt in part.items():
                            pno = img_to_pno[img_str]
                            results[pno] = txt
                            cached[str(pno)] = txt
                            done_count += 1
                            if progress_cb:
                                progress_cb(done_count, total, f"OCR 진행 중 ({done_count}/{total}쪽)")

                # Clean up batch PNGs and persist cache checkpoint
                for img_path in img_paths:
                    try:
                        img_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                cache_file.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        finally:
            doc.close()

    return results


def ocr_image_file(image_path: Path, max_dim: int = 2600) -> str:
    """Run Windows WinRT Korean OCR on a standalone image file (PNG/JPG/WEBP/BMP/GIF/TIFF) with disk cache."""
    if not image_path.exists() or not image_path.is_file():
        return ""

    cache_key = f"img_{_file_sha1(image_path)}"
    cache_file = get_ocr_cache_dir() / f"{cache_key}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("text"), str):
                return cached["text"]
        except Exception:
            pass

    try:
        from PIL import Image, ImageOps
    except Exception:
        return ""

    try:
        with tempfile.TemporaryDirectory(prefix="church_img_ocr_") as tmp:
            tmp_dir = Path(tmp)
            script_path = tmp_dir / "winrt_ocr_worker.ps1"
            script_path.write_text(_PS_OCR_WORKER_SCRIPT, encoding="utf-8-sig")

            norm_png = tmp_dir / "input.png"
            with Image.open(str(image_path)) as im:
                im = ImageOps.exif_transpose(im)
                if getattr(im, "is_animated", False):
                    im.seek(0)
                gray = im.convert("L")
                w, h = gray.size
                # Upscale small screenshots slightly for cleaner Korean glyph recognition; cap oversized photos
                if max(w, h) < 900 and max(w, h) > 0:
                    scale = min(2.0, 1200.0 / float(max(w, h)))
                    gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
                elif max(w, h) > max_dim:
                    scale = float(max_dim) / float(max(w, h))
                    gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
                gray.save(str(norm_png), format="PNG")

            res = _run_ps_ocr_batch(script_path, [norm_png])
            text = res.get(str(norm_png), "").strip()
            try:
                cache_file.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return text
    except Exception:
        return ""


def ocr_image_bytes(raw_bytes: bytes, ext_hint: str = ".png") -> str:
    """Run Windows WinRT Korean OCR on in-memory image bytes (e.g., embedded PPTX slide images)."""
    if not raw_bytes or len(raw_bytes) < 64:
        return ""
    h = hashlib.sha1(raw_bytes).hexdigest()[:16]
    cache_file = get_ocr_cache_dir() / f"imgb_{h}.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("text"), str):
                return cached["text"]
        except Exception:
            pass

    suffix = ext_hint if ext_hint.startswith(".") else f".{ext_hint}"
    try:
        with tempfile.TemporaryDirectory(prefix="church_imgb_ocr_") as tmp:
            p = Path(tmp) / f"embedded{suffix}"
            p.write_bytes(raw_bytes)
            text = ocr_image_file(p)
            try:
                cache_file.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return text
    except Exception:
        return ""
