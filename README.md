# 목포사랑의교회 행정Q&A

목포사랑의교회 교역자·행정팀을 위한 **근거 전용 법규·행정 검색기, AI 서식 자동 작성 스튜디오, 협업 행정 표준화실** 통합 데스크톱·모바일 솔루션입니다.

> **개인정보·교회 내부 자료 보호 원칙**: 이 공개 저장소에는 프로그램 소스코드와 자동 빌드·업데이트 워크플로우만 포함됩니다. 교회 내부 법규 PDF·SQLite DB·PIN·대화 기록·서명 키는 `.gitignore`로 100% 제외되어 있습니다.

## 주요 기능
- **근거 전용 Q&A (Hallucination Gate + 이중 원문 재대조)**: `자율 | 실무 정리 | 원문 엄격 | 적용·제안` 4가지 모드 + 인터넷/AI 미연결 시 0.05초 PC 내장 오프라인 원문 검색 자동 전환
- **AI 연결 방식 자유 선택**: 구독 CLI(`Claude`, `Codex`, `Gemini`) · 직접 API 키(`Anthropic`, `OpenAI`, `Google Gemini`, `로컬 Ollama / OpenAI 호환`) · 자동 전환 지원 (API 키는 Windows DPAPI로 로컬 암호화 저장)
- **협업 「행정 표준화실」**: 다중 분류·작업형태 게시판, AI 교차 분류 기억(`이동 · 병행 복사 · 통합 병합 · 되돌리기`), 실명/익명 1인 1표 투표, 4역할 전문가 위원회 출판급 A4 PDF/DOCX 편찬 및 Q&A 원클릭 등재
- **내 기본 정보 프로필 & 실시간 A4 서식 작성 스튜디오**: 기기 전용 프로필 자동 매핑 + 실시간 A4 미리보기 + 맑은 고딕 Word(`.docx`) 출력
- **어디서든 발행 · 사용자 선택형 안전 업데이트**: GitHub Actions 클라우드 자동 빌드 또는 `scripts/publish_release.py`로 어디서든 새 버전 발행 → 모든 설치 PC에 변경 내역 안내 + SHA-256 검증 + 사전 DB 백업 + 자동 롤백

## 어디서든 새 버전 업데이트 배포하는 법
1. **GitHub Actions 자동 빌드 (어느 PC·노트북·웹에서든 가능)**:
   - 코드 수정 후 `RELEASE_NOTES.md`에 변경 내역을 적고 태그를 푸시합니다:
     ```bash
     git add -A && git commit -m "v2.4.1 개선"
     git tag v2.4.1 && git push origin main --tags
     ```
   - 또는 GitHub 저장소 **Actions → Build & Publish Release → Run workflow**에서 버전과 변경 내역을 입력하면 클라우드에서 자동 빌드·발행됩니다.
2. **내 PC에서 즉시 원클릭 발행**:
   ```powershell
   .venv\Scripts\python.exe -X utf8 scripts\publish_release.py --version 2.4.1 --notes-file RELEASE_NOTES.md
   ```
