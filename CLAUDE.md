# STUDY_IN_UNIV

대학 과목을 유형으로 판정하고, 유형별 파이프라인 단계마다 사용자의 수업 PDF로 학습 자료를 만들어주는 웹서비스 (1인 개발, MVP 목표 2026-12 첫째 주).

**세션을 시작하면 `PROGRESS.md`를 먼저 읽는다.** 결정, 진행 상황, 파일 지도, 남은 일이 모두 거기 있다.

- 사이트: https://study-in-univ.onrender.com (Render, GitHub `main`에 push하면 자동 배포)
- 저장소: https://github.com/kjyilj0707/STUDY_IN_UNIV (공개)
- 데이터: Supabase (로그인·DB·PDF). 표 구조는 `supabase/*.sql`

## 작업 규칙
- 사용자와는 한국어로 대화한다. 설명은 쉽고 직관적으로 (사용자는 개발 입문 단계).
- 산출 문서는 `docs/templates/`의 생성 규칙을 따른다 (A1 강의 노트, B1 장별 노트). 공통: 누락·요약 금지, 필기 여백, 원본에 없는 내용 금지, `[p.N]` 출처, 원본 오타는 `⚠ 원본 표기` 메모.
- PDF는 텍스트 추출 → 부족하거나 수식이 있으면 페이지 이미지로 읽는다 (`PROGRESS.md` 4·5절 명령 참고).
- Windows: Python은 `python -I -X utf8`로 실행한다. 단, `app` 패키지·Supabase를 쓰는 명령은 `-I` 없이 (`packaging` 등이 사용자 site-packages에 있음).
- `data/`는 개인정보·저작권 자료다. 외부 서비스에 올리거나 git에 커밋하지 않는다.
- 키(`.env`, Render Environment)는 출력하지 않는다. 사용자가 붙여넣어야 하면 PowerShell `Set-Clipboard`로 클립보드에 넣어 준다.
- **GitHub push = 사이트 재배포**다. push 전에 생성 중인 노트(`lectures.status = 'running'`)가 없는지 확인한다. 친구 테스트 중이면 사용자에게 먼저 묻는다.
- DB 표를 바꾸면 `supabase/`에 번호 붙은 SQL 파일을 추가하고, 사용자가 Supabase SQL Editor에서 실행하게 안내한다.
- 시험은 로컬 시험 서버(포트 8020, `INVITE_CODE=test-invite`)와 시험 계정으로 하고, 끝나면 시험 계정·데이터를 지운다. 실제 생성 시험은 PDF 몇 장만 잘라서 비용을 줄인다.
- 외부 공개 터널(cloudflared) 실행은 보안 규칙상 Claude가 하지 않는다 (사용자가 직접).
- 진행이 바뀌면 `PROGRESS.md`와 Notion "idea 2" 페이지의 "정리본" DB(`collection://069ef4f4-5f17-4cf8-9216-3b3fbc16de1e`)에 날짜별 행으로 함께 기록한다.
