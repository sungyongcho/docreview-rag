"""테스트 패키지.

`__init__.py`를 두는 이유: 테스트 디렉터리가 `app/` 구조를 그대로 미러링하므로
`tests/ingestion/test_config.py`와 `tests/api/test_config.py`처럼 **파일 이름이
겹치는 일이 생긴다**. 패키지가 아니면 pytest가 "import file mismatch"로 죽는다.
"""
