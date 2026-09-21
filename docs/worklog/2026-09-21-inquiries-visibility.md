# Worklog — 문의함 가시성 개선 · 2026-09-21

## 한 일

문의함 대시보드 가시성 개선 세션. Slack 전화 메모의 원문 마크업이 그대로 노출되고
제목·본문이 중복되던 문제를 백엔드 정제 + 프론트 재설계로 해결했다. `ff9a535`로
커밋하고 서버 웹루트에 배포 + 백엔드 재시작까지 마쳤다.

## 결정과 왜

| 결정 | 버린 대안 | 왜 |
|------|----------|----|
| 백엔드+프론트 이중 정제 | 백엔드만 정제 | 이미 쌓인 raw payload가 그대로 오므로, 프론트 fallback 없이는 구 데이터가 계속 지저분 |
| 전화번호 tel: 칩 + 통화기록 버튼 분리 | 본문 속 URL 텍스트 유지 | 긴 URL이 줄바꿈 없이 레이아웃을 뭉개는 주범. URL은 텍스트에서 숨기고 액션으로 승격 |
| lead-strip은 경계에서만 제거 | prefix 일치하면 무조건 제거 | 제목이 중간에 잘린 경우 토큰을 반토막냄 (아래 삽질 2) |
| 타인의 미커밋 변경 2건은 손대지 않고 내 4파일만 커밋 | 함께 커밋 | 귀속 불명 변경을 섞지 않기 위해 |

## 삽질·실수 → 교훈

- 이탤릭 unwrap 정규식 `_(?=\S)(.+?)(?<=\S)_`이 이메일 밑줄과 뒤쪽 마커를 쌍으로
  묶어 `a_b@example.com` → `ab@example.com`으로 망가뜨림. 검증 스크립트 실행에서
  발견 (`apps/inquiries/backend/test_inquiries.py`, `apps/inquiries/web/test.sh`).
  → 교훈: Slack식 `_강조_`는 토큰 경계에서만 성립한다. 여는·닫는 마커 모두에
  `(^|\s)` · `($|\s|punct)` 가드를 추가. backend `inquiries_slack.py`와
  `web/index.html` `cleanSlackText`에 동일 패치.
- 제목 중복 제거(lead-strip)가 잘린 제목(`...smtp`) + 본문(`...smtp-test@...`)을
  반토막내 `test@example.com` 조각을 남김 → 경계 판정 추가. 하이픈은 단어 내부
  (`smtp-test`)와 구분자(`- `)를 구분한다: `-` 뒤에 공백이 올 때만 경계로 인정.
- 배포 후 Gmail health가 `ok:false/HTTPError`라 재시작을 의심했으나, Gmail API에
  읽기 전용 GET 2방(labels → 401, tokeninfo → 400)으로 토큰 만료를 확정. 내 변경과
  무관. → 교훈: 재배포 후 외부 연동 실패는 코드보다 자격증명 유효성부터 확인한다.

## 배운 것

- 잘린 마크업(dangling `_요약율` 같은 것)은 별도 후처리로 제거: `*` 전면 삭제 +
  `_`는 토큰 경계에서만 (`apps/inquiries/backend/inquiries_slack.py`).
- 프론트 `summarizeItem` 병합 규칙: 둘 중 하나가 다른 쪽의 prefix면 긴 쪽 채택,
  40자 probe로 잘린 중복도 흡수 (`apps/inquiries/web/index.html`).

## 남긴 것

- Gmail 토큰 만료: Gmail 토큰 갱신 후 백엔드 서비스 재시작 필요 (OAuth 플로우라
  이번 범위 밖. UI에는 연동 경고 배너가 노출됨).
- 커밋 `ff9a535` 미푸시 상태 (푸시 요청 없었음).
- 세션 중반에 보였던 타 미커밋 변경 2건(`airlock-app.toml`, `render.sh`)이 후반에
  사라져 있었음. 원인은 모름. 건드리지 않음.

## 결과·검증

- `apps/inquiries/backend/test_inquiries.py` 39 tests OK,
  `apps/inquiries/web/test.sh` OK, `apps/inquiries/tests/parity.sh` OK,
  `test/no-internal-names.sh` clean.
- 운영 확인: `GET /health` slack ok, items 44건 정제 subject 반환 확인,
  배포 파일 일치 확인(`diff -q`).
- 미검증: 실제 브라우저 렌더 (사용자가 URL에서 직접 확인 예정).
