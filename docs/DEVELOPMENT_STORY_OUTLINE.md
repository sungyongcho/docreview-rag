# DocReview RAG — 개발 기록 초안

> 기록으로 확인한 진행 순서만 남긴 뼈대입니다. 사용자가 직접 수정하고 경험·설명·감상을 보충합니다.
> 에이전트는 본문·사례·학습 설명·홍보 문구를 더 작성하지 않습니다.

## 시작과 학습
- **6월:** LangChain 기초 강의를 마친 뒤 RAG 강의를 진행했다. 6월 24일 대화에서 모듈 3까지 들었다고 기록했다.
- **7월:** 강의를 따라 구현한 작업을 `lecture-tuto`, `lecture2-tuto` 브랜치로 남겼다 (`155ec8d`, `4fe6077`). 7월 8일에는 따라 친 코드를 아직 온전히 내 것으로 느끼지는 못한다고 기록했다.

## 직접 따라 만들며 개념 확인
- **8월:** `new` 완성본과 `zero` 학습용 브랜치를 분리하고, 문서의 코드를 직접 따라 치며 재구성·수정하는 흐름을 택했다.
- 파싱·표·청킹·DB 적재부터 임베딩·벡터/키워드 검색으로 이동했다. ORM을 왜 이렇게 쓰는지, 임베딩은 어디까지 이해해야 하는지, BM25를 직접 구현할지와 IDF에 로그를 쓰는 이유를 질문하며 필요한 개념을 확인했다 (`101bae7`, `df094df`).
- 검색 평가까지 진행한 뒤, **8월 말부터 `assemble`에서 다시 조립하며 검토·수정·테스트하는 과정**으로 이어갔다 (`2b47b71`, `7532b72`, `dd4cc60`).

## 개발 일지로 보충할 부분
- 각 단계의 문제 발견 → 근거 확인 → 수정 → 검증을 실제 기록에서 골라 사용자가 작성한다.
- 개념 설명 순서: 파싱 → 청킹 → 임베딩 → 키워드·벡터·하이브리드 검색 → 평가.

## AI와 함께 제품 품질 높이기
- **9월:** AI에게 UI·문서 구현을 맡기고, 직접 실행 화면을 보며 사용성·권한·도움말·로컬 연결을 수정하는 흐름으로 발전했다 (`c5bb137`, `3c83469`).
- 직접 학습·구현·판단한 부분과 AI의 도움을 받은 부분을 구분해 보충한다. 아직 작성하지 않은 경험이나 측정 결과는 덧붙이지 않는다.

## References
- [입문자를 위한 LangChain 기초](https://www.inflearn.com/course/입문자를위한-랭체인-기초) — 수강 완료를 직접 언급한 자료.
- [Retrieval Augmented Generation (RAG)](https://www.coursera.org/learn/retrieval-augmented-generation-rag) — 대화에서 진행한 모듈을 언급한 강의. 이후 DeepLearning.AI에서 수강 중이라고 설명했다.
- [KodeKloud RAG Crash Course](https://www.youtube.com/watch?v=swvzKSOEluc) — 코드베이스를 읽어 대략적인 구성을 확인했다고 기록한 자료.
- [freeCodeCamp: Learn RAG From Scratch](https://www.youtube.com/watch?v=sVcwVQRHIc8) — 앞부분 30분을 보고 멈췄다고 기록한 영상. 완강으로 적지 않는다.
- [BM25 학습 영상](https://www.youtube.com/watch?v=ziiF1eFM3_4) — 8월 24일 시청하며 공부 중이라고 직접 언급한 자료.
- [Gomoku의 Minimax·AlphaZero 문서](https://sungyongcho.com/gomoku/docs) — 개발 기록의 구성 참고.
