from __future__ import annotations

import copy
import json
import re
from typing import Any

STD_CONFIG_SETTING_KEY = "std_custom_config"

# Grounded directly in '2025년 사랑의교회 시행세칙 제53조 (제직회 각 부서 10개) + 당회·치리 + 교역자·인사'
DEFAULT_STD_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "예배선교부",
        "keywords": ["예배선교", "예배", "성찬", "성례", "세례", "입교", "유아세례", "찬양", "찬양대", "헌금위원", "장례", "결혼", "임직식", "의전", "주보", "방송", "음향", "영상"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "교육선교부",
        "keywords": ["교육선교", "교회학교", "주일학교", "유치부", "유년부", "초등부", "중등부", "고등부", "청년부", "교사", "수련회", "성경학교", "다음세대"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "목양사역선교부",
        "keywords": ["목양사역", "목양", "셀지기", "셀사역", "지체지기", "교구지기", "교구", "구역", "심방", "새가족", "등록", "정착", "행복아카데미", "확신의삶", "분가"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "장학선교부",
        "keywords": ["장학선교", "장학", "장학금", "장학생", "인재양성", "학자금", "장학추천"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "세계선교부",
        "keywords": ["세계선교", "국내선교", "해외선교", "선교사", "전도", "문서선교", "단기선교", "행복목회아카데미", "선교후원"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "사회봉사부",
        "keywords": ["사회봉사", "구제", "봉사", "기독교사랑의봉사단", "위문비", "병문안", "경조비", "지역섬김", "나눔"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "재단관리부",
        "keywords": ["재단관리", "시설", "건물", "대관", "비품", "수리", "안전", "소방", "냉난방", "청소", "관리직원", "부동산", "영선"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "차량관리부",
        "keywords": ["차량관리", "차량", "버스", "승합차", "운행", "주차", "유류비", "교통범칙금", "배차", "운전기사", "차량일지"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "주방관리부",
        "keywords": ["주방관리", "주방", "식당", "식사", "친교", "위생", "급식", "식자재", "조리", "배식"],
        "approval_preset_id": "dept_standard",
    },
    {
        "name": "재정부",
        "keywords": ["재정부", "재정", "회계", "예산", "결산", "헌금", "지출결의서", "수입결의서", "영수증", "청구서", "원회계", "감사", "사례비", "여비", "통장"],
        "approval_preset_id": "finance",
    },
    {
        "name": "당회·제직회·공동의회",
        "keywords": ["당회", "제직회", "공동의회", "노회", "총회", "청원", "권징", "회의록", "정관", "시행세칙", "위임전결", "실행위원회", "치리"],
        "approval_preset_id": "session",
    },
    {
        "name": "교역자·유급직원·인사",
        "keywords": ["교역자", "유급직원", "부목사", "강도사", "전도사", "사무직원", "휴가", "휴직", "복직", "안식월", "청빙", "사임", "근무", "출퇴근", "급여", "인사"],
        "approval_preset_id": "pastoral",
    },
]

DEFAULT_WORK_TYPES: list[str] = [
    "규정·서식 표준화",
    "시행세칙 개정안",
    "부서 업무 매뉴얼",
    "결재·공문 양식 통일",
    "위임전결·절차 점검표",
]

# Grounded directly in '2025년 사랑의교회 시행세칙 제11장 위임전결규정 (제124조·제127조 별표) 및 제65조'
DEFAULT_APPROVAL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "dept_standard",
        "name": "부서 기본 결재선 (위임전결규정 별표)",
        "slots": ["총무", "부장", "지도교역자", "당회장"],
        "basis": "시행세칙 제11장 위임전결규정 제124조·제127조 [별표]",
    },
    {
        "id": "finance",
        "name": "재정·회계 결재선 (재정집행 기준)",
        "slots": ["회계", "원회계", "재정부장", "당회장"],
        "basis": "시행세칙 제7장 제65조 (재정 집행)",
    },
    {
        "id": "pastoral",
        "name": "교역자·행정사무 결재선",
        "slots": ["기안", "지도교역자", "당회장"],
        "basis": "시행세칙 제11장 위임전결규정 제124조·제127조",
    },
    {
        "id": "session",
        "name": "당회·치리회 결재선",
        "slots": ["기안(서기)", "당회서기", "당회장"],
        "basis": "목포사랑의교회 정관 제5장 · 시행세칙 제5장",
    },
]

DEFAULT_PDF_TEMPLATE: dict[str, Any] = {
    "denomination_header": "대한예수교장로회 · 목포사랑의교회 공식 행정 표준 규정집",
    "church_name": "목포사랑의교회",
    "committee_label": "행정표준화위원회",
    "footer_left": "목포사랑의교회 행정표준화위원회",
    "footer_right": "공식 정규 행정 문서 (위임전결규정 준용)",
    "default_recipient": "목포사랑의교회 당회장 귀하",
    "default_submit_statement": "위와 같이 제출(신청)하오니 허락하여 주시기 바랍니다.",
    "accent_color": "#0f4c81",
    "default_approval_preset_id": "dept_standard",
    "show_cover_approval_box": True,
    "show_delegation_footnote": True,
    "delegation_footnote": "※ 시행세칙 제127조·제129조: 전결권자 부재 시 직무대리자가 대결하며, 타 부서 관련 사항은 해당 부서 위원장과 합의합니다.",
}


def get_default_std_config() -> dict[str, Any]:
    return {
        "categories": copy.deepcopy(DEFAULT_STD_CATEGORIES),
        "work_types": list(DEFAULT_WORK_TYPES),
        "approval_presets": copy.deepcopy(DEFAULT_APPROVAL_PRESETS),
        "pdf_template": copy.deepcopy(DEFAULT_PDF_TEMPLATE),
    }


def _sanitize_hex_color(raw: str, fallback: str = "#0f4c81") -> str:
    s = (raw or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", s):
        return s.lower()
    return fallback


def normalize_std_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = get_default_std_config()
    if not isinstance(raw, dict):
        return base

    # 1. Approval presets
    presets_in = raw.get("approval_presets")
    presets_out: list[dict[str, Any]] = []
    seen_pids: set[str] = set()
    if isinstance(presets_in, list):
        for idx, p in enumerate(presets_in):
            if not isinstance(p, dict):
                continue
            pid = re.sub(r"[^a-zA-Z0-9_-]", "", str(p.get("id") or f"preset_{idx+1}"))[:32] or f"preset_{idx+1}"
            if pid in seen_pids:
                continue
            name = str(p.get("name") or "").strip()[:60]
            slots_raw = p.get("slots")
            slots = [str(s).strip()[:18] for s in (slots_raw if isinstance(slots_raw, list) else []) if str(s).strip()]
            if not name or not slots:
                continue
            seen_pids.add(pid)
            presets_out.append(
                {
                    "id": pid,
                    "name": name,
                    "slots": slots[:7],
                    "basis": str(p.get("basis") or "").strip()[:120],
                }
            )
    if not presets_out:
        presets_out = base["approval_presets"]
    valid_preset_ids = {p["id"] for p in presets_out}
    fallback_preset_id = presets_out[0]["id"]

    # 2. Categories
    cats_in = raw.get("categories")
    cats_out: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    if isinstance(cats_in, list):
        for c in cats_in:
            if isinstance(c, str):
                name = c.strip()[:48]
                kws = [t for t in re.split(r"[·/\s,]+", name) if len(t) >= 2]
                ap_id = fallback_preset_id
            elif isinstance(c, dict):
                name = str(c.get("name") or "").strip()[:48]
                kw_raw = c.get("keywords")
                if isinstance(kw_raw, str):
                    kws = [k.strip() for k in re.split(r"[,;\n]+", kw_raw) if k.strip()]
                elif isinstance(kw_raw, list):
                    kws = [str(k).strip() for k in kw_raw if str(k).strip()]
                else:
                    kws = []
                if not kws and name:
                    kws = [t for t in re.split(r"[·/\s,]+", name) if len(t) >= 2]
                ap_id = str(c.get("approval_preset_id") or fallback_preset_id).strip()
                if ap_id not in valid_preset_ids:
                    ap_id = fallback_preset_id
            else:
                continue
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            cats_out.append(
                {
                    "name": name,
                    "keywords": kws[:24],
                    "approval_preset_id": ap_id,
                }
            )
    if not cats_out:
        cats_out = base["categories"]

    # 3. Work types
    wt_in = raw.get("work_types")
    wt_out: list[str] = []
    if isinstance(wt_in, list):
        for w in wt_in:
            s = str(w).strip()[:48]
            if s and s not in wt_out:
                wt_out.append(s)
    if not wt_out:
        wt_out = base["work_types"]

    # 4. PDF Template
    tpl_in = raw.get("pdf_template") if isinstance(raw.get("pdf_template"), dict) else {}
    tpl = copy.deepcopy(base["pdf_template"])
    for key in (
        "denomination_header",
        "church_name",
        "committee_label",
        "footer_left",
        "footer_right",
        "default_recipient",
        "default_submit_statement",
        "delegation_footnote",
    ):
        val = tpl_in.get(key)
        if isinstance(val, str) and val.strip():
            tpl[key] = val.strip()[:220]
    tpl["accent_color"] = _sanitize_hex_color(str(tpl_in.get("accent_color", tpl["accent_color"])))
    def_pid = str(tpl_in.get("default_approval_preset_id") or fallback_preset_id).strip()
    tpl["default_approval_preset_id"] = def_pid if def_pid in valid_preset_ids else fallback_preset_id
    if "show_cover_approval_box" in tpl_in:
        tpl["show_cover_approval_box"] = bool(tpl_in["show_cover_approval_box"])
    if "show_delegation_footnote" in tpl_in:
        tpl["show_delegation_footnote"] = bool(tpl_in["show_delegation_footnote"])

    return {
        "categories": cats_out,
        "work_types": wt_out,
        "approval_presets": presets_out,
        "pdf_template": tpl,
    }


def load_std_config(db: Any) -> dict[str, Any]:
    if db is None:
        return get_default_std_config()
    raw_str = db.get_setting(STD_CONFIG_SETTING_KEY, "") or ""
    if not raw_str.strip():
        return get_default_std_config()
    try:
        parsed = json.loads(raw_str)
        return normalize_std_config(parsed)
    except Exception:
        return get_default_std_config()


def save_std_config(db: Any, payload: dict[str, Any]) -> dict[str, Any]:
    norm = normalize_std_config(payload)
    db.set_setting(STD_CONFIG_SETTING_KEY, json.dumps(norm, ensure_ascii=False))
    return norm


def reset_std_config(db: Any) -> dict[str, Any]:
    db.set_setting(STD_CONFIG_SETTING_KEY, "")
    return get_default_std_config()


def resolve_approval_preset(
    std_config: dict[str, Any],
    board_category: str = "",
    preset_id: str = "",
    custom_slots: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve the active approval line slots for a board compilation or PDF form sheet."""
    presets = std_config.get("approval_presets") or DEFAULT_APPROVAL_PRESETS
    by_id = {p["id"]: p for p in presets}

    if custom_slots:
        cleaned = [str(s).strip()[:18] for s in custom_slots if str(s).strip()]
        if cleaned:
            return {
                "id": "custom",
                "name": "사용자 지정 결재선",
                "slots": cleaned[:7],
                "basis": "관리자 직접 지정 결재선",
            }

    if preset_id and preset_id in by_id:
        return by_id[preset_id]

    # Match board's category -> its linked approval preset
    cat_compact = re.sub(r"\s+", "", board_category or "").lower()
    if cat_compact:
        for cat in std_config.get("categories") or []:
            cname = re.sub(r"\s+", "", str(cat.get("name") or "")).lower()
            if cname and (cname == cat_compact or cname in cat_compact or cat_compact in cname):
                pid = str(cat.get("approval_preset_id") or "")
                if pid in by_id:
                    return by_id[pid]
        # Smart fallback keyword match (e.g. legacy '재정·회계' -> finance preset)
        if any(k in cat_compact for k in ("재정", "회계", "예산")):
            if "finance" in by_id:
                return by_id["finance"]
        if any(k in cat_compact for k in ("당회", "제직회", "공동의회", "치리")):
            if "session" in by_id:
                return by_id["session"]
        if any(k in cat_compact for k in ("인사", "교역자", "직원", "복무")):
            if "pastoral" in by_id:
                return by_id["pastoral"]

    tpl_def = str((std_config.get("pdf_template") or {}).get("default_approval_preset_id") or "")
    if tpl_def in by_id:
        return by_id[tpl_def]
    return presets[0]
