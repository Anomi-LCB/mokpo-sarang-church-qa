from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import APP_NAME, APP_VERSION, DEFAULT_UPDATE_REPO

APP_EXEC_NAME = "목포사랑의교회 행정Q&A"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def sync_version_files(version: str) -> None:
    clean = version.strip().lstrip("vV")
    cfg_path = ROOT / "core" / "config.py"
    cfg_txt = cfg_path.read_text(encoding="utf-8")
    cfg_new = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{clean}"', cfg_txt, count=1)
    if cfg_new != cfg_txt:
        cfg_path.write_text(cfg_new, encoding="utf-8")

    iss_path = ROOT / "packaging" / "windows" / "installer.iss"
    if iss_path.exists():
        iss_txt = iss_path.read_text(encoding="utf-8-sig")
        iss_new = re.sub(r"AppVersion=[^\r\n]+", f"AppVersion={clean}", iss_txt)
        iss_new = re.sub(r"AppVerName=[^\r\n]+", f"AppVerName={APP_NAME} {clean}", iss_new)
        if iss_new != iss_txt:
            iss_path.write_text(iss_new, encoding="utf-8-sig")


def build_patch_zip(version: str, out_dir: Path) -> Path:
    """Create a lean app-only Windows update ZIP (EXE + _internal + readme, ZERO user data/)."""
    app_dir = ROOT / "dist" / APP_EXEC_NAME
    exe_file = app_dir / f"{APP_EXEC_NAME}.exe"
    internal_dir = app_dir / "_internal"
    if not exe_file.exists() or not internal_dir.exists():
        raise FileNotFoundError(f"빌드된 EXE 폴더를 찾을 수 없습니다: {app_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"mokpo-sarang-qa-win64-update-v{version}.zip"
    zip_path = out_dir / zip_name
    if zip_path.exists():
        zip_path.unlink()

    embedded_meta = json.dumps(
        {
            "version": version,
            "app_name": APP_NAME,
            "built_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
        indent=2,
    )

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("update-manifest.json", embedded_meta.encode("utf-8"))
        zf.write(exe_file, arcname=exe_file.name)
        readme = app_dir / "사용안내.txt"
        if readme.exists():
            zf.write(readme, arcname=readme.name)
        for f in sorted(internal_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(app_dir).as_posix()
                zf.write(f, arcname=rel)

    print(
        f"[release] Patch ZIP ready: {zip_path.name} ({zip_path.stat().st_size / (1024*1024):.2f} MB)",
        flush=True,
    )
    return zip_path


def write_manifest(
    version: str,
    notes_md: str,
    repo: str,
    patch_zip: Path,
    out_path: Path,
    installer_exe: Path | None = None,
    apk_file: Path | None = None,
    base_download_url: str | None = None,
) -> dict:
    base_url = (base_download_url or f"https://github.com/{repo}/releases/download/v{version}").rstrip("/")
    highlights = []
    for ln in notes_md.splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            item = re.sub(r"^[-*•]\s+", "", s).strip()
            item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
            if item and len(highlights) < 6:
                highlights.append(item[:140])

    assets: dict[str, dict | None] = {
        "win_patch_zip": {
            "name": patch_zip.name,
            "url": f"{base_url}/{patch_zip.name}",
            "sha256": _sha256(patch_zip),
            "size_bytes": patch_zip.stat().st_size,
        },
        "win_installer_exe": None,
        "android_apk": None,
    }
    if installer_exe and installer_exe.exists():
        assets["win_installer_exe"] = {
            "name": installer_exe.name,
            "url": f"{base_url}/{installer_exe.name}",
            "sha256": _sha256(installer_exe),
            "size_bytes": installer_exe.stat().st_size,
        }
    if apk_file and apk_file.exists():
        assets["android_apk"] = {
            "name": apk_file.name,
            "url": f"{base_url}/{apk_file.name}",
            "sha256": _sha256(apk_file),
            "size_bytes": apk_file.stat().st_size,
        }

    manifest = {
        "version": version,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "title": f"{APP_NAME} v{version}",
        "highlights": highlights,
        "notes_md": notes_md.strip(),
        "release_url": f"https://github.com/{repo}/releases/tag/v{version}",
        "assets": assets,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def publish_to_github(
    repo: str,
    version: str,
    notes_md: str,
    files: list[Path],
) -> None:
    tag = f"v{version}"
    title = f"{APP_NAME} {tag}"
    gh = shutil.which("gh")
    if not gh:
        raise FileNotFoundError("GitHub CLI (gh) 가 설치되어 있지 않습니다.")

    notes_tmp = ROOT / "build" / f"release_notes_{version}.md"
    notes_tmp.parent.mkdir(parents=True, exist_ok=True)
    notes_tmp.write_text(notes_md.strip() + "\n", encoding="utf-8")

    # Check if release already exists
    check = subprocess.run([gh, "release", "view", tag, "--repo", repo], capture_output=True, text=True)
    if check.returncode == 0:
        print(f"[release] Updating existing GitHub Release {tag} on {repo}...", flush=True)
        subprocess.run(
            [gh, "release", "edit", tag, "--repo", repo, "--title", title, "--notes-file", str(notes_tmp)],
            check=True,
        )
        subprocess.run(
            [gh, "release", "upload", tag, "--repo", repo, "--clobber", *[str(f) for f in files]],
            check=True,
        )
    else:
        print(f"[release] Creating GitHub Release {tag} on {repo}...", flush=True)
        subprocess.run(
            [
                gh,
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--title",
                title,
                "--notes-file",
                str(notes_tmp),
                *[str(f) for f in files],
            ],
            check=True,
        )
    print(f"[release] Published! https://github.com/{repo}/releases/tag/{tag}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="목포사랑의교회 행정Q&A 원클릭 릴리즈 빌드 & GitHub 발행기")
    ap.add_argument("--version", default=APP_VERSION, help="릴리즈 버전 (예: 2.4.0)")
    ap.add_argument("--repo", default=DEFAULT_UPDATE_REPO, help="GitHub 저장소 (owner/repo)")
    ap.add_argument("--notes", default="", help="한국어 업데이트 내용 마크다운")
    ap.add_argument("--notes-file", default="", help="업데이트 내용 마크다운 파일 경로")
    ap.add_argument("--skip-build", action="store_true", help="프론트엔드/EXE 재빌드 생략")
    ap.add_argument("--local-only", action="store_true", help="GitHub 업로드 생략 (로컬 data/releases/ 만 갱신)")
    args = ap.parse_args()

    version = args.version.strip().lstrip("vV")
    sync_version_files(version)

    if args.notes_file:
        notes_md = Path(args.notes_file).read_text(encoding="utf-8")
    elif args.notes:
        notes_md = args.notes
    elif (ROOT / "RELEASE_NOTES.md").exists():
        notes_md = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    else:
        notes_md = f"### {APP_NAME} v{version}\n- 최신 기능 개선 및 안정성 업데이트"

    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py if venv_py.exists() else sys.executable)

    if not args.skip_build:
        print("[release] Building frontend...", flush=True)
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
        subprocess.run([npm, "run", "build"], cwd=str(ROOT / "frontend"), check=True)
        print("[release] Building Windows EXE...", flush=True)
        subprocess.run([py, "-X", "utf8", str(ROOT / "packaging" / "windows" / "build_exe.py")], cwd=str(ROOT), check=True)

    release_out = ROOT / "dist" / "releases"
    patch_zip = build_patch_zip(version, release_out)

    manifest_path = release_out / "update-manifest.json"
    write_manifest(
        version=version,
        notes_md=notes_md,
        repo=args.repo,
        patch_zip=patch_zip,
        out_path=manifest_path,
    )

    # Also mirror into local data/releases/ so Tailscale/LAN custom update feed works immediately
    local_rel = ROOT / "data" / "releases"
    local_rel.mkdir(parents=True, exist_ok=True)
    shutil.copy2(patch_zip, local_rel / patch_zip.name)
    write_manifest(
        version=version,
        notes_md=notes_md,
        repo=args.repo,
        patch_zip=local_rel / patch_zip.name,
        out_path=local_rel / "update-manifest.json",
        base_download_url="/api/updates/local-assets",
    )

    if not args.local_only:
        publish_to_github(args.repo, version, notes_md, [patch_zip, manifest_path])


if __name__ == "__main__":
    main()
