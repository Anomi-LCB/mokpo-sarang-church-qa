; 목포사랑의교회 행정Q&A — 공식 Windows 설치 마법사 (Inno Setup 6)

#ifndef ProjectRoot
  #define ProjectRoot "..\.."
#endif
#ifndef SeedDir
  #define SeedDir "..\..\build\installer_seed"
#endif
#ifndef HasKoreanIsl
  #define HasKoreanIsl "1"
#endif

[Setup]
AppId={{8D6E4921-7C31-4F92-9A0E-C81D2B4F9102}
AppName=목포사랑의교회 행정Q&A
AppVersion=4.3.1
AppVerName=목포사랑의교회 행정Q&A 4.3.1
AppPublisher=목포사랑의교회 행정·법규 검색 시스템
DefaultDirName={autopf}\목포사랑의교회 행정Q&A
DefaultGroupName=목포사랑의교회 행정Q&A
DisableProgramGroupPage=yes
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=목포사랑의교회 행정Q&A 설치
SetupIconFile={#ProjectRoot}\packaging\windows\app_icon.ico
UninstallDisplayIcon={app}\목포사랑의교회 행정Q&A.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=yes

[Languages]
#if HasKoreanIsl == "1"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Types]
Name: "full"; Description: "전체 설치 (권장 — 프로그램 + 4대 법규 기본 자료 + Tailscale 원격 연결)"
Name: "nodata"; Description: "빈 라이브러리 설치 (기본 자료 제외 — 새 문서만 직접 올려서 사용)"
Name: "custom"; Description: "사용자 지정 설치"; Flags: iscustom

[Components]
Name: "core"; Description: "목포사랑의교회 행정Q&A 본체 (오프라인 검색 엔진 + 하이브리드 Android APK)"; Types: full nodata custom; Flags: fixed
Name: "churchdata"; Description: "목포사랑의교회 4대 법규·행정 기본 자료 (헌법·해설서·정관·시행세칙 919쪽 + 서식 60종)"; Types: full
Name: "tailscale"; Description: "Tailscale 원격 연결 도구 자동 설치 (외부 스마트폰 HTTPS 접속용 · 미설치 시 오프라인 설치)"; Types: full nodata

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 작업:"
Name: "startup"; Description: "Windows 시작 시 백그라운드 팀 서버 자동 실행"; GroupDescription: "추가 작업:"; Flags: unchecked

[Dirs]
Name: "{app}\data"; Permissions: users-modify
Name: "{app}\data\downloads"; Permissions: users-modify
Name: "{app}\data\notebooks"; Permissions: users-modify
Name: "{app}\data\exports"; Permissions: users-modify
Name: "{app}\data\backups"; Permissions: users-modify
Name: "{app}\data\updates"; Permissions: users-modify
Name: "{app}\data\models"; Permissions: users-modify

[Files]
Source: "{#ProjectRoot}\dist\목포사랑의교회 행정Q&A\목포사랑의교회 행정Q&A.exe"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#ProjectRoot}\dist\목포사랑의교회 행정Q&A\사용안내.txt"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#ProjectRoot}\dist\목포사랑의교회 행정Q&A\_internal\*"; DestDir: "{app}\_internal"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

; Branded Hybrid Offline Android APK (served automatically from [연결] modal)
Source: "{#ProjectRoot}\dist\목포사랑의교회-행정Q&A.apk"; DestDir: "{app}\data\downloads"; Components: core; Flags: ignoreversion
Source: "{#ProjectRoot}\dist\목포사랑의교회-행정Q&A.apk"; DestDir: "{app}\data\downloads"; DestName: "church-search.apk"; Components: core; Flags: ignoreversion

; Optional default 4-book church dataset — installed ONLY when user explicitly consents on DataConsentPage
Source: "{#SeedDir}\church_search.db"; DestDir: "{app}\data"; Components: churchdata; Check: ShouldInstallChurchData; Flags: onlyifdoesntexist
Source: "{#SeedDir}\notebooks\*"; DestDir: "{app}\data\notebooks"; Components: churchdata; Check: ShouldInstallChurchData; Flags: ignoreversion recursesubdirs createallsubdirs

; Bundled 100% offline Tailscale 64-bit Windows MSI
Source: "{#ProjectRoot}\packaging\windows\redist\tailscale-setup-amd64.msi"; DestDir: "{tmp}"; Components: tailscale; Flags: deleteafterinstall

[Icons]
Name: "{group}\목포사랑의교회 행정Q&A"; Filename: "{app}\목포사랑의교회 행정Q&A.exe"; AppUserModelID: "MokpoSarangChurch.AdminQA"
Name: "{group}\사용 안내"; Filename: "{app}\사용안내.txt"
Name: "{group}\목포사랑의교회 행정Q&A 제거"; Filename: "{uninstallexe}"
Name: "{autodesktop}\목포사랑의교회 행정Q&A"; Filename: "{app}\목포사랑의교회 행정Q&A.exe"; AppUserModelID: "MokpoSarangChurch.AdminQA"; Tasks: desktopicon
Name: "{commonstartup}\목포사랑의교회 행정Q&A"; Filename: "{app}\목포사랑의교회 행정Q&A.exe"; Parameters: "--headless"; AppUserModelID: "MokpoSarangChurch.AdminQA"; Tasks: startup

[Run]
Filename: "msiexec.exe"; Parameters: "/i ""{tmp}\tailscale-setup-amd64.msi"" /qn /norestart"; StatusMsg: "Tailscale 원격 연결 도구를 오프라인으로 설치하고 있습니다..."; Components: tailscale; Check: NeedsTailscaleInstall; Flags: waituntilterminated
Filename: "{app}\목포사랑의교회 행정Q&A.exe"; Description: "목포사랑의교회 행정Q&A 지금 실행"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
var
  DataConsentPage: TInputOptionWizardPage;
  AiModePage: TInputOptionWizardPage;
  ApiProviderPage: TInputOptionWizardPage;
  ApiKeyPage: TInputQueryWizardPage;

function ShouldInstallChurchData: Boolean;
begin
  Result := (DataConsentPage.SelectedValueIndex = 0) and WizardIsComponentSelected('churchdata');
end;

function NeedsTailscaleInstall: Boolean;
begin
  Result := not FileExists(ExpandConstant('{pf64}\Tailscale\tailscale.exe'))
            and not FileExists(ExpandConstant('{pf32}\Tailscale\tailscale.exe'));
end;

function JsonEscape(const S: String): String;
var
  R: String;
begin
  R := S;
  StringChangeEx(R, '\', '\\', True);
  StringChangeEx(R, '"', '\"', True);
  StringChangeEx(R, #13, '', True);
  StringChangeEx(R, #10, '', True);
  Result := R;
end;

procedure InitializeWizard;
begin
  DataConsentPage := CreateInputOptionPage(
    wpWelcome,
    '목포사랑의교회 4대 법규 기본 자료 포함 설치 안내 및 이용 동의',
    '설치 시 기본 법규·행정 자료(919쪽 · 서식 60종)를 함께 설치할지 선택해 주세요.',
    '기본 자료(대한예수교장로회 헌법 · 헌법해설서 · 목포사랑의교회 정관 · 2025년 시행세칙 및 공문 서식 60종)는 목포사랑의교회 내부 행정·사역 용도로 제공됩니다.' + #13#10 +
    '• 동의하고 함께 설치하면 설치 직후 인터넷 없이도 0.05초 원문 검색을 바로 사용할 수 있습니다.' + #13#10 +
    '• 동의하지 않으시면 기본 자료 파일이 전혀 복사되지 않으며 깨끗한 빈 라이브러리로 시작합니다.' + #13#10 +
    '• 대화 기록은 항상 빈 상태로 시작하며, 그룹 초대나 공유를 받을 때만 공동 대화가 표시됩니다.',
    True,
    False
  );
  DataConsentPage.Add('동의하고 목포사랑의교회 4대 기본 자료 함께 설치 (권장)');
  DataConsentPage.Add('동의하지 않음 — 기본 자료 없이 깨끗한 빈 라이브러리로 설치');
  DataConsentPage.SelectedValueIndex := 0;

  AiModePage := CreateInputOptionPage(
    wpSelectTasks,
    'AI 연결 방식 선택 (선택 사항)',
    '설치 후 사용할 AI 엔진 연결 방식을 선택하세요.',
    '지금 설정하지 않아도 앱 안의 [설정 → 화면 · AI 엔진]에서 언제든 CLI 또는 API로 자유롭게 변경할 수 있으며, 미연결 시에도 100% 오프라인 원문 검색이 동작합니다.',
    True,
    False
  );
  AiModePage.Add('자동 전환 / 나중에 앱에서 설정 (권장 — CLI 자동 감지 · 오프라인 즉시 사용)');
  AiModePage.Add('구독 CLI 연결 (Claude Code / Codex / Gemini CLI)');
  AiModePage.Add('API 키 직접 연결 (Anthropic · OpenAI · Gemini · 로컬 Ollama)');
  AiModePage.SelectedValueIndex := 0;

  ApiProviderPage := CreateInputOptionPage(
    AiModePage.ID,
    'API 공급자 선택',
    '사용할 AI API 서비스를 선택하세요.',
    '선택한 공급자의 API 키는 첫 실행 시 Windows DPAPI로 이 PC에만 로컬 암호화 저장됩니다.',
    True,
    False
  );
  ApiProviderPage.Add('Google Gemini API — 무료 티어 추천 (카드 불필요 · gemini-2.5-flash)');
  ApiProviderPage.Add('로컬 무료 AI Ollama (평생 0원 · 완전 오프라인 · gemma3:4b)');
  ApiProviderPage.Add('Anthropic Claude API (claude-sonnet-4-5)');
  ApiProviderPage.Add('OpenAI API (gpt-4.1-mini)');
  ApiProviderPage.SelectedValueIndex := 0;

  ApiKeyPage := CreateInputQueryPage(
    ApiProviderPage.ID,
    'API 키 및 세부 설정 (선택)',
    'API 키를 지금 입력하거나 비워 두고 나중에 앱 설정에서 입력할 수 있습니다.',
    '입력된 키는 첫 실행 직후 Windows 암호화 저장소로 이관되며 임시 설정 파일은 자동 삭제됩니다.'
  );
  ApiKeyPage.Add('API 키 (로컬 Ollama는 비워도 됨):', True);
  ApiKeyPage.Add('모델명 (선택 — 비우면 권장 기본 모델 사용):', False);
  ApiKeyPage.Add('커스텀 Base URL (선택 — Ollama 예: http://localhost:11434/v1):', False);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = DataConsentPage.ID then
  begin
    if WizardForm.ComponentsList.Items.Count > 1 then
    begin
      WizardForm.ComponentsList.Checked[1] := (DataConsentPage.SelectedValueIndex = 0);
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = ApiProviderPage.ID) or (PageID = ApiKeyPage.ID) then
  begin
    Result := (AiModePage.SelectedValueIndex <> 2);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ModeStr, ApiProvStr, ApiKeyStr, ApiModelStr, ApiBaseStr, JsonText, OutPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    if AiModePage.SelectedValueIndex = 1 then
      ModeStr := 'cli'
    else if AiModePage.SelectedValueIndex = 2 then
      ModeStr := 'api'
    else
      ModeStr := 'auto';

    if ModeStr <> 'auto' then
    begin
      case ApiProviderPage.SelectedValueIndex of
        0: ApiProvStr := 'gemini_api';
        1: ApiProvStr := 'openai_compatible';
        2: ApiProvStr := 'anthropic';
        3: ApiProvStr := 'openai';
      else
        ApiProvStr := 'gemini_api';
      end;

      ApiKeyStr := Trim(ApiKeyPage.Values[0]);
      ApiModelStr := Trim(ApiKeyPage.Values[1]);
      ApiBaseStr := Trim(ApiKeyPage.Values[2]);

      JsonText := '{' + #13#10 +
        '  "ai_connection_mode": "' + JsonEscape(ModeStr) + '",' + #13#10 +
        '  "ai_api_provider": "' + JsonEscape(ApiProvStr) + '",' + #13#10 +
        '  "ai_api_key": "' + JsonEscape(ApiKeyStr) + '",' + #13#10 +
        '  "ai_api_model": "' + JsonEscape(ApiModelStr) + '",' + #13#10 +
        '  "ai_api_base_url": "' + JsonEscape(ApiBaseStr) + '"' + #13#10 +
        '}';

      OutPath := ExpandConstant('{app}\data\initial_ai_config.json');
      SaveStringToFile(OutPath, JsonText, False);
    end;
  end;
end;
