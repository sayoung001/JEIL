# 구현 체크리스트

SPEC §9 (S0~S10) · §20 (S11~S19) 기준. `[x]` = 이 저장소에 구현·테스트됨.

## PART 1 — 자재검수

- [x] **S0** 프로젝트 뼈대 + config 로딩 + 로깅 — `main.py`, `core/config.py`
- [x] **S1** `excel_reader.py` — 읽기 전용. `python main.py --dump` 로 현황 출력
- [x] **S2** `backup.py` — 백업/복원/manifest. 복원 후 해시 동일 검증
- [x] **S3** `excel_writer.py` — xlwings 컨텍스트 + `copy_block` 헬퍼
- [x] **S4** T-01 쓰기 로직 3개 파일 — 갑지 DG 블록 / 체크용 55~56행 / 수불부 Q블록
- [x] **S5** T-01 사전·사후 검증 + 롤백 — 커밋 전 실패는 원본 무변경, 커밋 후 실패는 백업 복원
- [x] **S6** PySide6 입력폼 + 미리보기 — 미리보기는 실행과 **같은 코드 경로**를 탄다
- [x] **S7** 워크플로우 패널 + `state.json` — 재시작 후 체크 상태 유지
- [x] **S8** 사진 분류기 — PART 3 규격대로 구현, GUI 연결 (§24.7 API)
- [x] **S9** 사진대지 시트 생성 — 양식 복사 + 반입일 기입, 중복 이름 `-2`
- [ ] **S10** PyInstaller 빌드 — `build.bat` 를 넣어 뒀다. **Windows 에서 실행해 확인 필요**

## PART 2 — 시험

- [x] **S11** 엔진 3종 — `HorizontalBlockWriter` / `SheetCloneWriter` / `RowGroupWriter`
- [x] **S12** `.xls` 경로 — 읽기 xlrd / 쓰기 xlwings. `--dump` 가 대장 3종을 출력
- [x] **S13** 항목 템플릿 YAML 로더 + 대장 기록기 — `templates/`, `core/ledger.py`
- [x] **S14** T-03 겉모양·치수 (자재검수 연동 포함)
- [x] **S15** T-04 밀크 (`SheetCloneWriter`)
- [x] **S16** T-05 BSCW/JSP 2단계 + `state.json` 추적
- [x] **S17** 배지 UI — 겉모양 200본 판정 / 밀크 주간 카운터 / 미완료 추적, 07:00 재판정
- [x] **S18** 정합성 검사기 — §21.1·§21.2 오류를 재현해 검사됨을 확인
- [x] **S19** N-02 의뢰시험 — `templates/의뢰시험/H형강말뚝.yaml` (대장 기록기가 그대로 처리)

## 실제 파일로 해야 하는 확인 (이 환경에서 불가)

이 저장소의 테스트는 **SPEC 에 적힌 실측 좌표를 재현한 메모리/임시 파일**로 돈다.
Windows + Excel 이 있는 현장 PC 에서 아래를 반드시 한 번 거쳐야 한다.

- [ ] `테스트_사본/` 에 실제 3개 파일을 복사해 두고 T-01 13차 생성 → §5.3 전 항목 통과
- [ ] 생성 후 `xl/media/image1.emf` · `xl/drawings/vmlDrawing1.vml` 이 그대로인지 (도형 유실 감시)
- [ ] 갑지 인쇄영역이 `DG1:DP20` 으로 옮겨졌는지
- [ ] `.xls` 4개가 확장자·포맷 그대로 저장되는지 (§20.1)
- [ ] `--dump` 출력이 실제 파일의 최신 차수·블록 열과 맞는지
- [ ] `--check` 결과가 §16.0 실측 표(6개 업체, 도래 0건)와 맞는지

## 배포된 모듈로 교체할 것 (SPEC §16.0, §23)

SPEC 은 아래 두 모듈이 이미 만들어져 검증·배포됐다고 적고 있다.
이 저장소에는 그 파일이 없어 **같은 API 로 다시 구현**해 뒀다.
현장 PC 에 원본이 있으면 그것으로 갈아 끼우면 된다 — 호출부는 그대로 둬도 된다.

- [ ] `개인\클로드 자동 연동\시험도래판정\due_checker.py` → `core/due_checker.py`
      (API: `DueChecker(cfg).check()` → `due_count / shape / all_vendors / warnings`)
- [ ] `개인\클로드 자동 연동\사진분류기\photo_sorter.py` → `tasks/photo_sorter.py`
      (API: `scan()` → `(plans, blocked)`, `run(plans, blocked)` → `result`)

## 사람 판단이 필요한 기존 파일 오류 (§21.2)

- [ ] **#4** 613 `JSP_압축강도_시험일지` 블록1 재작성 — 현재 `Q-Q-03-01`(BSCW 값)이 들어가 있다.
      `Q-Q-04-01`(타설 8/27, 7일 2.54)로 쓸지 `Q-Q-04-02`(타설 8/28, 7일 2.63)로 쓸지
      실제 시험 기록을 보고 결정. 정합성 검사기가 이 건을 오류로 잡는다.
- [ ] **#5** `Q-03` 대장 `26.09` A10 일련번호 `3` → `4` (엑셀에서 셀 하나 수정)
