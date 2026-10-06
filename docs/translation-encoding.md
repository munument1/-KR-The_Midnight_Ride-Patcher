# 번역 문자열 저장과 검증

## 수정한 오류

기본 영문 CP1252 인코딩으로 ESP/ESM 번역 문자열을 저장하면 한국어가 실제 `?` 바이트로 바뀝니다. 레코드 수와 마스터 목록만 검사하면 이 손상을 성공으로 보고할 수 있습니다.

또한 영문 원문이 대사와 제작용 메모에 동일하게 들어 있는 INFO 레코드에서는 범용 문자열 치환이 `NAM1` 대사뿐 아니라 `NAM2` ScriptNotes까지 번역했습니다. 메모는 번역 문자열로 정의된 필드가 아니므로 한국어 저장 과정에서 손상될 수 있습니다. 이제 Mutagen의 `TranslatedString`만 번역하며 일반 문자열은 변경하지 않습니다.

## 인코딩 정책

| 대상 | 읽기/쓰기 정책 |
|---|---|
| ESP/ESM 번역 문자열 | 입력은 엄격한 UTF-8을 우선 시도하고 실패하면 CP1252로 읽음. 출력은 엄격한 UTF-8 |
| localized `_en.STRINGS` 등 | 같은 읽기 정책과 UTF-8 쓰기 적용 |
| 비번역 문자열 | 기존 CP1252 저장 정책 유지, 번역 사전으로 치환하지 않음 |
| Interface/Translations | `_en` 이름을 유지하고 UTF-16 LE BOM(`FF FE`)으로 저장 |
| MCM JSON | 기존 UTF-8 정책 유지 |

저장 후 플러그인을 새로 읽어 변경된 FormKey 및 객체 경로별 텍스트를 기대값과 비교합니다. 일치하지 않으면 예외로 중단하며 성공 보고를 생성하지 않습니다. 기존 레코드와 마스터 검증도 유지합니다.

## exact payload와 릴리즈 재생성

기존 catalog에 입력 해시와 payload 해시만 있어도 텍스트가 정상이라는 보장은 없습니다. 새 payload는 다음 검증 정보를 함께 기록해야 합니다.

```json
{
  "payload_encoding": "utf-8",
  "text_roundtrip_verified": true
}
```

런타임은 이 정보가 없거나 파일이 누락된 경우 direct/fallback으로 전환합니다. 검증 정보가 있는 파일의 해시가 일치하지 않으면 기존과 같이 오류로 처리합니다.

`tools/prepare_release_data.py`는 UTF-8 및 텍스트 재읽기 검증 결과가 없는 번역 payload를 거부합니다. 릴리즈를 다시 만들 때는 수정된 백엔드로 깨끗한 영문 입력을 번역해 payload와 catalog를 재생성하고, GUI 및 백엔드 실행 파일도 다시 빌드해야 합니다. 기존 손상된 payload나 사용자의 게임 파일은 소스 변경에 포함하지 않습니다.

이미 설치 파일에 `?`가 저장된 경우 사전은 영문 원문을 매칭할 수 없습니다. 영문 원본을 복구한 뒤 다시 실행해야 합니다. `updated_no_match`는 변경 0개를 뜻하며 원본 정상 여부를 보증하지 않습니다.

## 회귀 테스트 실행

저장소 루트에서 .NET 9 이상 SDK와 Python 3.12로 실행합니다. ESP 테스트는 실제 백엔드를 실행하고 별도의 바이너리 파서로 저장 바이트를 확인합니다. 게임 또는 번역 데이터 다운로드가 필요하지 않습니다.

```powershell
dotnet build tools/TmrPluginTranslator/TmrPluginTranslator.csproj -c Release
$env:TMR_TRANSLATOR = (Resolve-Path tools/TmrPluginTranslator/bin/Release/net9.0/TmrPluginTranslator.dll).Path
python -m unittest discover -s tests -v
```

`TMR_TRANSLATOR`가 없고 배포 백엔드도 없으면 ESP 테스트가 건너뛰어지므로, 백엔드 경로를 지정하여 전체 테스트를 실행해야 합니다.

검사 범위는 direct/fallback의 한국어 UTF-8 저장, CP1252 문장부호, 압축 레코드, 기존 한국어 입력, 반복 퀘스트 목표, localized STRINGS, 대사와 같은 문장을 가진 ScriptNotes/Edits/AlternateLipText 보존, exact payload 검증, Interface UTF-16 LE BOM 및 줄바꿈 보존입니다.
