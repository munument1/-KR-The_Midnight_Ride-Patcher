# TMR Korean Patcher Architecture

## 1. 출력 구조

패쳐는 실행 중 사용자의 기존 MO2 모드 파일을 직접 수정하지 않는다. 먼저 별도의 `Output` 트리를 만든다.

### 본편 번역

본편/공식 DLC 한국어 리소스는 다음 새 MO2 모드로 생성한다.

`Output/mods/FO4 KOREAN/`

사용자는 Output을 TMR MO2 루트에 복사한 뒤 MO2에서 `FO4 KOREAN`을 체크한다.

### TMR 모드 번역

각 번역 파일은 현재 승자(winner)를 제공하는 원본 MO2 모드의 **폴더명과 Data 상대경로**를 그대로 재현한다.

예:

`Output/mods/Previsibines Repair Pack - Full (1.11.191)/prp.esp`

`Output/mods/Complex Vendors/MCM/Config/Complex Vendors/config.json`

`Output/mods/Mod Configuration Menu 1.11.221/Interface/Translations/MCM_en.txt`

사용자가 Output을 TMR MO2 루트에 복사하면 기존 원본 모드 폴더에 번역 파일이 병합/덮어쓰기된다.

MO2 overwrite가 실제 provider인 파일은 `Output/overwrite/`를 사용한다.

## 2. 제외 플러그인

다음 플러그인은 런타임과 릴리즈 데이터 생성 단계 모두에서 명시적으로 제외한다.

- `ptrfo4001_t60pistol.esl`
- `ptrfo4002_vangraff.esl`

exact payload, direct map, fallback 결과를 생성하지 않는다.

## 3. 플러그인 적용 전략

### Exact fast path

릴리즈 시 검증한 원본 SHA-256과 사용자의 플러그인 해시가 같으면 미리 검증한 번역 payload를 사용한다.

### Updated/new fallback

해시가 달라지거나 릴리즈 이후 새 플러그인이 활성화된 경우 `TmrPluginTranslator`가 현재 플러그인을 읽고 번역을 병합한다.

우선순위:

1. 모드 전용 direct SST 매핑
2. Fallout4.esm + 공식 DLC 번역 상속

본편/DLC 상속은 owner/FormID/현재 영문 원문을 기준으로 하며, QUST/TERM처럼 같은 필드가 반복되는 레코드는 xTranslator의 REC:FIELD + rec_id 의미를 보존해 적용한다.

## 4. 본편/DLC fallback bank

개발 단계에서 다음 사전을 하나의 fallback bank로 생성한다.

- Fallout4.esm
- DLCRobot.esm
- DLCWorkshop01.esm
- DLCCoast.esm
- DLCWorkshop02.esm
- DLCWorkshop03.esm
- DLCNukaWorld.esm

SSU8 구형 SST는 마스터 인덱스를 공식 마스터 순서로 복원한다.

## 5. MCM / Interface

MCM과 Interface 번역도 각 원본 MO2 provider 폴더와 동일한 경로에 출력한다.

SimpleMcmJsonTranslator의 로컬 DB는 개발 단계에서 JSON 매핑으로 변환한다. 릴리즈 런타임은 BinaryFormatter DB를 읽지 않는다.

Custom TXT SST는 릴리즈 준비 단계에서 source → Korean JSON으로 변환한다.

## 6. 내장 본편 한국어 리소스

v1.0.1부터 `FO4_AE_1.11.191.Kor`를 릴리즈 ZIP에 포함한다.

패쳐는 실행 파일 옆의 이 폴더를 자동으로 읽고 `Output/mods/FO4 KOREAN`으로 복사한다.

복사 대상:

- `Interface`
- `Programs`
- `Strings`

영문판 런타임 호환을 위해 원래 `_en` 파일명을 유지한다.

## 7. 저장 검증

번역 정책 버전 5는 원본 바이트 보존 문자열 치환, UTF-8 저장/재읽기, 지몬자 번역 제외 및 WRLD 인덱스 제거를 포함한다.
정책 버전이 5인 catalog entry만 exact 경로로 재사용하며,
exact payload에 OFST·CLSZ가 남아 있으면 복사를 거부한다.
구형 payload는 원본과 사전을 새 백엔드에 전달해 다시 생성한다.

Mutagen의 원문/번역 비교용 사본에서 승인된 문자열 변경을 찾고 OriginalTextWriter가
그 변경만 원본 레코드에 치환한다. 비표시 필드, 원본 헤더와 필드 순서는 유지한다.
문자열 전체와 필드별 발생 순서까지 대응되지 않으면 출력을 거부한다.
그 후 WorldIndexStripper가 WRLD의 OFST·CLSZ와 해당 XXXX를 제거한다.
이는 xTranslator 1.7.3의 임시 대응을 따르며 셀 오프셋 재계산을 대체한다.
압축 WRLD는 해제·필터링·재압축하고 레코드 및 상위 그룹 크기를 갱신한다.
다른 필드 및 그 필드의 XXXX는 보존한다. TES4 인덱스는 처리하지 않는다.
소스 프리플라이트는 구조를 검사하며 유효한 WRLD 인덱스는 허용한다.
손상된 경계나 TES4 인덱스는 실패/제외한다.
번역할 내용이 없으면 저장하지 않는다. 인덱스 제거 실패 시 생성한 파일을 삭제한다.
파일 검증과 게임 내 안정성·성능 검증은 별개다.

번역 백엔드는 플러그인 저장 후 다시 읽어 다음을 확인한다.

- 레코드 FormKey 집합/개수
- 마스터 목록 및 순서
- 출력 파일 재파싱 가능 여부

## 8. 배포

릴리즈 ZIP은 다음을 포함한다.

- `TMR-Korean-Patcher.exe`
- `FO4_AE_1.11.191.Kor/`
- `TranslationData/catalog.json`
- exact plugin payloads
- direct mappings
- base/DLC fallback bank
- self-contained `TmrPluginTranslator.exe`
- MCM/Interface JSON mappings
- LICENSE / THIRD_PARTY_NOTICES

Python, .NET Runtime, xTranslator 설치는 릴리즈 사용자에게 요구하지 않는다.
