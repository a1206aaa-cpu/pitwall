# 피트월 노트 — F1 관전 노트

F1을 보면서 쓰는 개인용 웹앱. **GitHub Actions가 매일 F1 데이터를 받아와 자동으로 갱신**하므로,
한 번 올려두면 손대지 않아도 라운드가 끝날 때마다 결과·순위·랩차트가 따라 들어온다.

---

## 올리는 법 (터미널 없이, 5분)

### 1. 저장소 만들기
GitHub에서 **New repository** → 이름 `pitwall` → **Public** → Create.
(Private으로도 되지만, GitHub Pages 무료 공개는 Public이 확실하다.)

### 2. 파일 올리기
저장소 첫 화면의 **uploading an existing file** 링크 클릭 →
이 폴더 안의 내용물을 **전부** 드래그 → Commit.

> `.github` 폴더가 드래그로 안 올라가면(숨김 폴더라 가끔 그렇다),
> **Add file → Create new file** 을 누르고 파일 이름 칸에
> `.github/workflows/update-f1-data.yml` 를 그대로 입력한 뒤
> `update-f1-data.yml` 내용을 붙여넣으면 폴더까지 같이 만들어진다.

### 3. Actions 권한 켜기
**Settings → Actions → General → Workflow permissions** 에서
**Read and write permissions** 선택 → Save.
(이게 꺼져 있으면 수집한 데이터를 저장소에 커밋하지 못한다.)

### 4. GitHub Pages 켜기
**Settings → Pages → Source: Deploy from a branch** → Branch `main` / `/ (root)` → Save.
1~2분 뒤 `https://<아이디>.github.io/pitwall/` 로 열린다.

### 5. 데이터 한 번 돌리기
**Actions 탭 → "F1 데이터 자동 갱신" → Run workflow**.
1분쯤 뒤 `data/live.json` 이 생기고, 사이트 상단 배지가
회색 `저장된 데이터` 에서 초록색 `자동 갱신 ○/○ ○○:○○` 로 바뀐다.

### 6. 폰 홈 화면에 올리기
폰 브라우저로 주소를 열고
- **iPhone(Safari)**: 공유 → 홈 화면에 추가
- **Android(Chrome)**: 메뉴 → 홈 화면에 추가 / 앱 설치

아이콘 누르면 주소창 없이 전체화면으로 뜬다. 한 번 연 뒤에는 오프라인에서도 열린다.

---

## 자동으로 갱신되는 것 / 아닌 것

| 자동 (API) | 수동 (직접 쓴 글) |
|---|---|
| 캘린더·세션 시각(KST 자동 환산) | 라운드별 관전 포인트·리뷰 |
| 라운드 결과, 그리드, 리타이어 | 드라이버 비화, 드라이빙 스타일 |
| 드라이버·팀 순위표 | 머신·엔진 평가와 개량 타임라인 |
| 랩별 순위변화 차트 | 서킷 도면·설명, 룰북, 전략 시뮬레이터 |
| 드라이버별 라운드 성적·메달 | 역대 명경기 |

새 라운드가 들어오면 관전 포인트 자리에는 "아직 글이 없습니다" 안내가 들어간다.
글을 채우고 싶으면 Claude에게 부탁해서 `index.html` 을 받아 교체하면 된다.

**데이터가 안 들어와도 화면은 멀쩡하다.** API가 멈추거나 비행기 모드여도
`index.html` 안에 들어 있는 마지막 데이터로 그대로 동작하고, 배지만 회색으로 바뀐다.

---

## 구성

```
index.html                      앱 본체 (이 파일 하나에 다 들어있다)
manifest.json, icon-*.png       홈 화면 앱 아이콘·설정
sw.js                           오프라인 캐시
data/live.json                  Actions가 만들어 넣는 데이터 (처음엔 없음)
tools/fetch_f1.py               데이터 수집기
.github/workflows/update-f1-data.yml   매일 13:17(KST) 실행
.nojekyll                       GitHub Pages가 파일을 건드리지 않게
```

데이터 출처: [Jolpica F1 API](https://github.com/jolpica/jolpica-f1) (구 Ergast, 무료·비영리).
자원봉사로 운영되므로 수집기는 하루 한 번만 돌고, 랩차트는 한 번에 3라운드씩만 새로 받는다.

## 알아둘 것

- GitHub은 **60일 동안 저장소에 아무 활동이 없으면 예약 실행을 자동으로 끈다.**
  시즌 중엔 매주 커밋이 생기니 문제없지만, 비시즌이 길어지면 Actions 탭에서 한 번 눌러 다시 켜면 된다.
- 시즌이 바뀌면 수집기가 그 해 일정을 자동으로 잡는다. 다만 GP 한글 이름은
  라운드 번호로 매칭하므로, 캘린더가 바뀌면 영어 이름으로 표시될 수 있다. 그때 한 번 손보면 된다.
- 수집기를 내 컴퓨터에서 직접 돌려보려면: `python tools/fetch_f1.py --out data/live.json`
