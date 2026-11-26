from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from android.build_offline_assets import build_offline_assets

ANDROID_DIR = ROOT / "android"
APP_MAIN = ANDROID_DIR / "app" / "src" / "main"
BUILD_DIR = ANDROID_DIR / "build"


def _find_tool(sdk_root: Path, sub_pattern: str, exe_name: str) -> Path:
    base = sdk_root / sub_pattern
    if base.is_dir():
        versions = sorted(base.iterdir(), reverse=True)
        for v in versions:
            cand = v / exe_name
            if cand.exists():
                return cand
    raise FileNotFoundError(f"Android SDK 도구를 찾을 수 없습니다: {base}/*/{exe_name}")


def _find_android_jar(sdk_root: Path) -> Path:
    platforms = sdk_root / "platforms"
    for p in sorted(platforms.iterdir(), reverse=True):
        jar = p / "android.jar"
        if jar.exists():
            return jar
    raise FileNotFoundError("android.jar 를 찾을 수 없습니다.")


def _find_jdk_bin() -> Path:
    javac = shutil.which("javac")
    if javac:
        return Path(javac).parent
    # Fallback to common local JDK paths on Windows
    for cand in sorted((Path.home() / ".workstation" / "runtimes" / "java").glob("*/bin"), reverse=True):
        if (cand / "javac.exe").exists():
            return cand
    raise FileNotFoundError("JDK javac를 찾을 수 없습니다.")


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    print(">>", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def build_apk(profile: str = "standard") -> Path:
    sdk_root = Path(os.environ.get("ANDROID_HOME") or (Path.home() / "AppData/Local/Android/Sdk"))
    jdk_bin = _find_jdk_bin()

    aapt2 = _find_tool(sdk_root, "build-tools", "aapt2.exe")
    d8 = _find_tool(sdk_root, "build-tools", "d8.bat")
    zipalign = _find_tool(sdk_root, "build-tools", "zipalign.exe")
    apksigner = _find_tool(sdk_root, "build-tools", "apksigner.bat")
    android_jar = _find_android_jar(sdk_root)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    gen_dir = BUILD_DIR / "gen"
    obj_dir = BUILD_DIR / "obj"
    dex_dir = BUILD_DIR / "dex"
    res_flat_dir = BUILD_DIR / "res_flat"
    assets_dir = BUILD_DIR / "assets"
    for d in (gen_dir, obj_dir, dex_dir, res_flat_dir, assets_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 0. Build embedded offline WebApp, 919-page corpus, and profile-specific PDFs
    build_offline_assets(profile=profile, out_assets_dir=assets_dir)

    # 1. Compile resources with aapt2
    res_dir = APP_MAIN / "res"
    flat_files: list[str] = []
    for f in res_dir.rglob("*"):
        if f.is_file():
            run_cmd([str(aapt2), "compile", str(f), "-o", str(res_flat_dir)])
    for fl in res_flat_dir.glob("*.flat"):
        flat_files.append(str(fl))

    # 2. Link resources & generate R.java + unaligned apk
    # (Assets are packed via Python zipfile below to stay 100% safe on non-ASCII Windows paths)
    unsigned_apk = BUILD_DIR / "unsigned.apk"
    link_cmd = [
        str(aapt2),
        "link",
        "-o",
        str(unsigned_apk),
        "-I",
        str(android_jar),
        "--manifest",
        str(APP_MAIN / "AndroidManifest.xml"),
        "--java",
        str(gen_dir),
        *flat_files,
    ]
    run_cmd(link_cmd)

    # 3. Compile Java sources with javac (Java 11 bytecode for Android API 26+)
    java_files = [str(p) for p in (APP_MAIN / "java").rglob("*.java")] + [str(p) for p in gen_dir.rglob("*.java")]
    run_cmd(
        [
            str(jdk_bin / "javac.exe"),
            "--release",
            "11",
            "-encoding",
            "UTF-8",
            "-classpath",
            str(android_jar),
            "-d",
            str(obj_dir),
            *java_files,
        ]
    )

    # 4. Convert class files to classes.dex with d8
    class_files = [str(p) for p in obj_dir.rglob("*.class")]
    run_cmd(
        [
            str(d8),
            "--min-api",
            "26",
            "--lib",
            str(android_jar),
            "--output",
            str(dex_dir),
            *class_files,
        ]
    )

    # 5. Add classes.dex and offline assets/ into unsigned APK
    with zipfile.ZipFile(unsigned_apk, "a", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(dex_dir / "classes.dex", "classes.dex")
        for asset_file in sorted(assets_dir.rglob("*")):
            if asset_file.is_file():
                rel = asset_file.relative_to(assets_dir).as_posix()
                zf.write(asset_file, f"assets/{rel}")

    # 6. Zipalign
    aligned_apk = BUILD_DIR / "aligned.apk"
    run_cmd([str(zipalign), "-f", "-p", "4", str(unsigned_apk), str(aligned_apk)])

    # 7. Generate reusable keystore if absent & sign with apksigner
    keystore = ANDROID_DIR / "church_search.keystore"
    if not keystore.exists():
        run_cmd(
            [
                str(jdk_bin / "keytool.exe"),
                "-genkeypair",
                "-v",
                "-keystore",
                str(keystore),
                "-alias",
                "churchsearch",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-storepass",
                "churchsearch2026",
                "-keypass",
                "churchsearch2026",
                "-dname",
                "CN=ChurchSearch, OU=Admin, O=MokpoSarang, L=Mokpo, C=KR",
            ]
        )

    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    apk_name = "목포사랑의교회-행정Q&A.apk" if profile == "standard" else f"목포사랑의교회-행정Q&A-{profile}.apk"
    final_apk = dist_dir / apk_name
    signed_tmp = BUILD_DIR / "signed.apk"
    run_cmd(
        [
            str(apksigner),
            "sign",
            "--ks",
            str(keystore),
            "--ks-key-alias",
            "churchsearch",
            "--ks-pass",
            "pass:churchsearch2026",
            "--key-pass",
            "pass:churchsearch2026",
            "--out",
            str(signed_tmp),
            str(aligned_apk),
        ]
    )

    # 8. Verify APK signature (on ASCII temp path to avoid cmd.exe '&' handling in apksigner.bat)
    run_cmd([str(apksigner), "verify", "--verbose", str(signed_tmp)])
    shutil.copy2(signed_tmp, final_apk)

    # Copy default standard APK to server downloads directory
    if profile == "standard":
        dl_dir = ROOT / "data" / "downloads"
        dl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_apk, dl_dir / "목포사랑의교회-행정Q&A.apk")
        shutil.copy2(final_apk, dl_dir / "church-search.apk")

    size_mb = final_apk.stat().st_size / (1024 * 1024)
    print(
        f"\nAPK [{profile}] built & verified: {final_apk} ({final_apk.stat().st_size:,} bytes / {size_mb:.2f} MB)",
        flush=True,
    )
    return final_apk


def main() -> None:
    parser = argparse.ArgumentParser(description="Build & sign hybrid offline Android APK.")
    parser.add_argument(
        "--profile",
        choices=["lite", "standard", "full"],
        default="standard",
        help="lite (~0.7MB index only), standard (~8-14MB index + 60 form PDFs, default), full (~115MB + all 4 source PDFs)",
    )
    args = parser.parse_args()
    build_apk(profile=args.profile)


if __name__ == "__main__":
    main()
