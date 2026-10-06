# The Midnight Ride 비공식 한국어 패쳐

Fallout 4 모딩 가이드 **The Midnight Ride (TMR)** 환경에 한국어 번역을 적용하는 비공식 패쳐입니다.

패쳐는 TMR 설치 폴더를 직접 수정하지 않고 별도의 `Output`을 생성합니다. 사용자가 `Output`의 내용을 TMR MO2 루트에 복사하면, 번역 파일은 **기존 원본 모드와 동일한 폴더명·상대경로**로 들어가 기존 파일을 덮어쓰게 됩니다.

본편 한국어 리소스만 별도의 MO2 모드 **`FO4 KOREAN`**으로 생성되어 MO2에서 체크/해제할 수 있습니다.

> 이 프로젝트는 ModdingLinked 또는 The Midnight Ride 제작진의 공식 번역/도구가 아닙니다.

## v1.0.1 변경점

- `FO4_AE_1.11.191.Kor` 비공식 본편 한국어 리소스를 패쳐 ZIP에 내장
- 한국어 리소스 폴더를 따로 준비하거나 선택할 필요 없음
- 본편 번역을 `Output/mods/FO4 KOREAN`으로 생성
- TMR 모드 번역은 각 **원본 MO2 모드 폴더명과 동일한 경로**로 생성
- MCM, Interface/Translations, ESP/ESM/ESL도 원본의 Data 상대경로 유지
- `ptrfo4001_t60pistol.esl`, `ptrfo4002_vangraff.esl`은 명시적으로 패쳐 대상에서 제외

## 주요 기능

- Fallout 4 본편 + 공식 DLC 한국어 리소스를 `FO4 KOREAN` 모드로 출력
- TMR 활성 플러그인 자동 탐지
- 현재 검증 버전은 미리 생성한 번역 payload로 빠르게 적용
- 플러그인 업데이트 또는 신규 플러그인 감지 시 레코드 기반 fallback 번역
- 모드 전용 SST가 있으면 모드 전용 번역을 최우선 적용
- 나머지 override 레코드는 Fallout4.esm + 공식 DLC 번역을 상속
- PRP처럼 별도 SST가 없어도 바닐라 장소명/표시 문자열을 덮어쓰는 플러그인 대응
- MCM JSON 번역은 현재 설치된 config에 병합하여 새 옵션을 보존
- `Interface/Translations` 번역 지원
- Fallout 4 영문판 런타임에 맞춰 한국어 내용이어도 `_en` 파일명을 유지

TMR Extended 프로필 기준 비공식 플러그인 59개를 검사했습니다. 이 중 T60 Pistol/Vangraff 2개는 명시적으로 제외하고, 나머지 57개를 대상으로 현재 버전용 exact payload 41개와 모드 전용 direct 사전 17개를 준비했습니다.

## 준비물

- The Midnight Ride가 설치된 Mod Organizer 2 인스턴스
- Fallout 4 영문판 기반 환경

본편 한국어 리소스 `FO4_AE_1.11.191.Kor`는 v1.0.1부터 릴리즈 ZIP에 포함됩니다.

## 사용 방법

1. GitHub Releases에서 `TMR-Korean-Patcher-v1.0.1.zip`을 내려받아 압축을 풉니다.
2. `TMR-Korean-Patcher.exe`를 실행합니다.
3. `ModOrganizer.ini`가 있는 TMR MO2 폴더를 선택합니다.
4. **Output 생성**을 누릅니다.
5. 생성된 `Output` 안의 `mods` 및 필요한 경우 `overwrite` 내용을 **TMR MO2 루트**에 복사합니다.
6. Windows에서 같은 이름의 파일/폴더 덮어쓰기를 허용합니다.
7. MO2를 열고 새로 생긴 **`FO4 KOREAN`** 모드를 체크합니다.

기존 TMR 모드 번역 파일은 원본 모드 폴더 안으로 병합되므로 별도의 `TMR KOREAN` 모드를 체크할 필요가 없습니다.

## 출력 구조 예시

PRP:

`Output/mods/Previsibines Repair Pack - Full (1.11.191)/prp.esp`

MCM:

`Output/mods/Complex Vendors/MCM/Config/Complex Vendors/config.json`

Interface:

`Output/mods/Mod Configuration Menu 1.11.221/Interface/Translations/MCM_en.txt`

본편 번역:

`Output/mods/FO4 KOREAN/Interface/...`

`Output/mods/FO4 KOREAN/Strings/...`

즉 패쳐 결과를 TMR MO2 루트에 복사하면 기존 모드의 동일한 상대경로에 번역 파일이 들어갑니다.

## 번역 적용 우선순위

1. 현재 버전과 입력 해시가 일치하고, UTF-8 저장 및 텍스트 재읽기 검증이 기록된 exact payload 사용
2. 모드 전용 direct 번역 사전
3. Fallout 4 본편/공식 DLC의 동일 레코드 번역 상속
4. 안전하게 매칭되지 않는 문자열은 변경하지 않음

Fallback은 현재 영문 원문까지 확인하므로, 모드가 의도적으로 문구를 바꾼 경우 과거 바닐라 번역을 강제로 덮어쓰지 않습니다.

검증 정보가 없는 기존 exact payload나 누락된 파일은 사용하지 않고 direct/fallback 사전으로 처리합니다. `exact payload 41개`와 `direct 사전 17개`는 서로 겹치는 목록이며, direct 사전이 없는 플러그인도 원본 게임/DLC fallback 사전으로 번역할 수 있습니다.

## 한국어 저장 형식 및 기존 손상 파일

ESP/ESM의 번역 문자열과 localized 플러그인의 `_en.STRINGS` 파일은 UTF-8로 저장합니다. `Interface/Translations/*_en.txt`는 UTF-16 LE(BOM 포함)로 저장합니다. 입력 영문 파일의 CP1252 특수문자는 읽을 때 보존하며, 제작용 메모·식별자 등 비번역 필드는 번역하지 않습니다.

저장 후 변경된 문자열을 다시 읽어 기대한 번역과 일치하는지 검사합니다. 이미 `???`가 저장된 설치 파일은 깨끗한 영문 원본으로 복구한 뒤 Output을 다시 생성해야 합니다. `direct-maps`에 없는 플러그인도 fallback 적용 대상이므로 복구 범위를 이 폴더의 파일 이름만으로 판단하지 마세요.

개발자용 재현·테스트 방법과 payload 재생성 정책은 [번역 인코딩 문서](docs/translation-encoding.md)를 참고하세요.

## MCM / Interface

지원되는 MCM 번역 사전:

- Complex Vendors
- Crafting Highlight Fix
- Legendaries They Can Use
- Unlimited Survival Mode
- Upscaling (활성화된 경우)

지원되는 `Interface/Translations`:

- Mod Configuration Menu
- Safe Travels

## 제외 대상

다음 플러그인은 패쳐가 번역 파일을 생성하지 않습니다.

- `ptrfo4001_t60pistol.esl`
- `ptrfo4002_vangraff.esl`

## 안전 원칙

- 게임 `Data` 폴더 직접 수정 안 함
- Output 생성 과정에서 기존 MO2 모드 직접 수정 안 함
- 결과 파일은 원본 모드의 폴더명/상대경로를 그대로 재현
- 사용자가 Output을 복사할 때만 기존 모드 파일을 덮어씀
- 번역된 플러그인은 저장 후 다시 읽어 레코드 수와 마스터 목록을 검증
- 원본 마스터 순서를 유지

## 라이선스 / 출처

프로그램 소스는 GPL-3.0으로 배포합니다. 자세한 내용은 `LICENSE`와 `THIRD_PARTY_NOTICES.md`를 확인하세요.

- Mutagen: GPL-3.0
- xTranslator: MPL-2.0 — SST 형식과 매칭 동작을 개발 참고용으로 사용
- `FO4_AE_1.11.191.Kor`: 재배포 가능한 비공식 한국어 패치 리소스로 v1.0.1 릴리즈에 포함

Fallout, Fallout 4 및 관련 상표와 게임 데이터의 권리는 각 권리자에게 있습니다.
