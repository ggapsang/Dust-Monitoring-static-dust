# 현장 화면 시안 (동결)

에코프로비엠 포항 현장에 가져갈 화면의 시안이다. **앞으로 수정하지 않는다.**

- `index.html` — 화면 시안. `dashboard/data.js` 를 읽어 그린다
- `dashboard/` — 시안이 쓰는 판독 결과와 이미지. `make_dashboard.py` 가 만든 것이다
- `make_dashboard.py` — `assets/samples/` 를 판독해 위 데이터를 만드는 생성기

실증 단계의 실제 도구는 `padlab` 이다. 이쪽은 현장 화면이 어떤 모양이어야
하는지를 남겨 둔 참고물이고, 판독 모듈이 바뀌어도 여기를 따라 고치지 않는다.
그래서 `src/` 밖으로 빼 두었다 — 패키지에 들어가면 판독 모듈이 바뀔 때마다
같이 깨지고, 깨진 것을 고치게 된다.

생성기를 다시 돌릴 일이 생기면 저장소 루트에서 실행한다.

    PYTHONPATH=reader/src python ref/make_dashboard.py
