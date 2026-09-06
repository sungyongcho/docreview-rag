# M1.2 검증

> 명세: [02-spec.md](02-spec.md) · 코드: `app/ingestion/tables.py`

## 한 번에 전부 돌리기

```bash
uv run pytest tests/ingestion/test_09_tables.py     # 33 tests
uv run pytest                                        # full project suite
```

눈으로 보기:

```bash
uv run python -m app.ingestion.tables --doc NVDA-FY2024
uv run python -m app.ingestion.tables --doc MU-FY2024 --contains "Total current assets"
```

## 무엇을 검증하는가

**"변환했다"가 아니라 "레이아웃을 걷어냈다"를 검증한다.** 마크다운이 나오는 것만 보면 중앙값 기준 63.6%가 빈 넓은 격자도 통과한다.

| 지표 | 잡는 것 | **못** 잡는 것 |
|---|---|---|
| ① 붕괴 비율 (골든값) | 레이아웃이 덜 걷힘 / 내용이 지워짐 | 셀 **안**의 내용이 틀린 것 |
| ② 대표 표 전문 대조 | 헤더 결합·단위 병합·열 순서 | 다른 회사 조판 |
| ③ 마크다운 폭 일치 | 렌더링 깨짐 | 의미 |
| ④ 퇴화 입력 | 크래시 | — |

①이 양방향인 게 요점이다. 셀 수가 **오르면** 붕괴가 덜 된 것이고, **내려가면** 내용을 지운 것이다.

## 골든값

`tests/ingestion/golden.py`의 `TABLES` — **유일한 출처다.** 문서의 숫자는 사람이 읽으라고 옮겨 적은 사본이다.

```
(표블록, 빈 markdown, 전개 후 셀, 붕괴 후 셀)
```

전체 합계: **221,730 → 69,241 → 66,575셀 (30.0%)** · 빈 표 **26개**

빈 표 26개는 내용이 아예 없는 순수 스페이서다. AMD(10개)·INTC(16개)에만 있고 **MU·NVDA는 0개** — 회사별 조판 차이지 버그가 아니다.

아래 명령은 위 합계와 문서별 `TABLES` tuple을 모두 다시 출력한다.

```bash
uv run python -m scripts.measure_tables
```

## 테스트 대응표

| 테스트 | 대응 | 코퍼스 |
|---|---|---|
| `test_grid_is_rectangular` | L2 — ragged 80개가 직사각형으로 | ✅ |
| `test_rowspan_carries_down_without_duplicating_text` | L2 — 텍스트 복제 금지 | ✗ |
| `test_colspan_keeps_text_in_first_cell_only` | L2 | ✗ |
| `test_collapse_matches_golden` | **L3·L4 — 붕괴 비율 ★** | ✅ |
| `test_collapse_never_widens_a_table` | L3·L4 — 단조 감소 | ✅ |
| `test_unit_columns_are_folded_in_reading_order` | L4 — `$`앞 / `%`뒤 | ✗ |
| `test_header_is_inferred_from_shape_not_from_th` | **L5 — `<th>` 0개 전제** | ✅ |
| `test_header_rows_are_the_leading_rows_with_an_empty_label_column` | L5 | ✗ |
| `test_no_header_shape_returns_everything_as_body` | L5 — 헤더 지어내기 금지 | ✗ |
| `test_income_statement_renders_as_expected` | **L6 — 대표 사례 전문 대조** | ✅ |
| `test_parenthesized_negatives_survive_verbatim` | L7 — 원문 보존 | ✅ |
| `test_markdown_rows_all_have_the_same_width` | L6 — 렌더링 가능 | ✅ |
| `test_degenerate_input_never_raises` | L7 — 크래시 금지 | ✗ |
| `test_cell_pipes_are_escaped` | L6 | ✗ |

`test_header_is_inferred_from_shape_not_from_th`는 구현이 아니라 **코퍼스 사실**을 지킨다. `<th>`를 읽는 구현으로 되돌아가면 이 단언이 먼저 깨진다 — 그리고 그 구현은 헤더를 하나도 못 찾는다.

## 직접 구현하기

`app/ingestion/tables.py`를 직접 만들면 같은 테스트가 정식 구현을 채점한다:

```bash
uv run pytest tests/ingestion/test_09_tables.py
```

아직 만들지 않은 함수를 쓰는 테스트는 **실패가 아니라 건너뛰기**이므로 출력이 그대로 진행 상황판이 된다. 빈 스텁 상태의 실측:

```
1 passed, 32 skipped
```

통과하는 1개는 `test_header_is_inferred_from_shape_not_from_th`다 — 구현을 안 부르고 코퍼스만 보므로 처음부터 켜져 있다.

## 레이어를 하나씩 채우면 몇 개가 켜지나

레퍼런스 코드를 레이어별로 넣어가며 직접 재본 값이다. **자기 위치를 여기서 확인하면 된다.**

```
누적 구현                    통과 / 33   비고
────────────────────────────────────────────────────────────
(빈 스텁)                        1      코퍼스 사실만
+L2 to_grid                      4      전개 3개가 켜진다
+L3 drop_empty                   4      ★0개 늘어난다 — 아래 주의
+L4 merge_unit_columns           6      단위 병합 + 단조감소
+L5 split_header                 8      헤더 2개
+L6 to_markdown                  8      ★여기도 0개
+L7 table_to_markdown           33      전부
```

**L3와 L6은 테스트 피드백이 0이다.** 붕괴를 보는 테스트가 둘 다 `merge_unit_columns`까지 필요하고(L4에서 한꺼번에 +2), 직렬화를 보는 테스트는 전부 `table_to_markdown`을 거친다. 그래서 그 둘을 짜는 동안은 채점이 안 된다. 눈으로 확인해야 한다:

```bash
uv run python -c "
from bs4 import BeautifulSoup
from app.ingestion.tables import to_grid, drop_empty
html = open('data/corpus/NVDA/2024-02-21_0001045810-24-000029.html').read()
t = BeautifulSoup(html, 'lxml').find_all('table')[40]
g = to_grid(t)
print('before', len(g[0]), 'x', len(g))
c = drop_empty(g)
print('after ', len(c[0]), 'x', len(c))
"
```

**마지막 25개가 `table_to_markdown` 하나에 걸려 있다.** L6까지 다 하고도 8개뿐이라고 실망할 것 없다 — 진입점을 잇는 순간 33으로 간다.

## 틀렸을 때 의심할 곳

| 증상 | 원인 |
|---|---|
| 붕괴 후 셀 수가 **골든보다 많다** | 빈 열 판정이 `strip()`을 빼먹었다. `&nbsp;`가 남아 빈 열이 안 지워진다 |
| 붕괴 후 셀 수가 **골든보다 적다** | `colspan` 확장에서 텍스트를 복제했거나, 빈 행 제거가 헤더 행까지 지웠다 |
| 숫자가 두 배로 보인다 | L2에서 병합된 셀 텍스트를 전 구간에 복제했다 |
| 헤더가 전부 비어 있다 | `<th>`를 찾고 있다. 이 코퍼스엔 0개다 |
| 첫 데이터 행이 헤더로 올라갔다 | `split_header`가 `([], grid)`를 못 돌려주고 있다 |
| 마크다운 렌더링이 깨진다 | 셀 안의 `|`를 이스케이프하지 않았다 |
