# Claude Code 設定 - 乙房小学校 6年1組担任

## 「おはよう」受信時の自動実行ルーティン

ユーザーから「おはよう」というメッセージを受け取ったら、以下の①〜⑥をすべて自動で実行し、見やすい形式でまとめて表示すること。

---

### ① Googleカレンダーの予定確認

以下の**2つのカレンダー**から本日の予定を取得し、一覧表示する。

| カレンダー名 | カレンダーID |
|------------|------------|
| 個人カレンダー（howks.dog@gmail.com） | `howks.dog@gmail.com` |
| **R8乙房　職員会・研修・連絡関係** | `c_classroomaa655c96@group.calendar.google.com` |

- 予定にURLやGoogle Meetリンクなどが含まれている場合は必ず表示する
- timeZone は `Asia/Tokyo` を指定する

---

### ② 今日の時間割

- Googleドライブのスプレッドシート「(R8年度)６年１組 時間割」（fileId: `1hfSQ7G9Iw1HJK8OBqicICNtpp21OvMWq6wk4007cXNw`）を取得する
- 今日の曜日に対応する時間割を読み取り、1限〜6限の順に表示する
- 列のずれが生じやすいため、曜日と列の対応を慎重に確認してから読み取ること
- 祝日・振替休日の場合はその旨を明示する

---

### ③ 今週の提出物・締め切り

- Googleドライブの「R8乙房　職員会・研修・連絡関係」カレンダー（`c_classroomaa655c96@group.calendar.google.com`）から今週の予定を参照する
- あわせて R8フォルダ（`18zJqfwHhm7j7RAGd_L74bJLsSaj6YqOA`）内の「1　校務分掌」→「校務部会」フォルダ（`18rDPb-8QxNnLsBJiHzt2M4iCMj8J0RCb`）内の最新ファイルも参照する
- 今週中に提出・対応が必要なものをリスト化して表示する

---

### ④ 今後1ヶ月のTODO

- ③と同じソースを参照する
- カレンダーから今後1ヶ月以内の重要予定・締め切りをリスト化して表示する

---

### ⑤ 6年生関連のTODO

- Googleドライブの「R8」フォルダ（ID: `18zJqfwHhm7j7RAGd_L74bJLsSaj6YqOA`）全体を参照する
- 6年1組として対応・準備が必要なことをリスト化して表示する

---

### ⑥ 教育トレンド情報

- Webを検索し、教育関係のトレンドや教員として知っておきたい最新情報を厳選して5つ紹介する
- 情報源（URL）も合わせて表示する
- 検索クエリ例：「2026年 教育トレンド 教員 最新情報 学校教育」

---

## Googleドライブ 主要フォルダ・ファイルID

| 名称 | ID |
|------|----|
| R8フォルダ（ルート） | `18zJqfwHhm7j7RAGd_L74bJLsSaj6YqOA` |
| 1　校務分掌 | `1kyngZwa4TUSmNbrsnQL7W78TPOHd4dkN` |
| 校務部会 | `18rDPb-8QxNnLsBJiHzt2M4iCMj8J0RCb` |
| 3　行事 | `1q5MQ_xWwj8DEUsxp5radEvd7W0WNrrrY` |
| 6　週案 | `1-HdavVjHLEB31Vlr9ieHOL0GnM-i48Gw` |
| 7　専科時間割 | `1JunnEFTDWtmf_NV1b5LeDuTPzV-znSwX` |
| 8　時間割 | `1Pwp8Zg_Z2AvgM0VSmxTnJA4gRgczTTDT` |
| (R8年度)６年１組 時間割（スプレッドシート） | `1hfSQ7G9Iw1HJK8OBqicICNtpp21OvMWq6wk4007cXNw` |

## Googleカレンダー ID

| 名称 | ID |
|------|----|
| 個人（Gmail） | `howks.dog@gmail.com` |
| 個人（学校） | `m-nakatake1028@miyakonojo-city.miyazaki-c.ed.jp` |
| R8乙房　職員会・研修・連絡関係 | `c_classroomaa655c96@group.calendar.google.com` |
| 中武家カレンダー | `d44df4fc1c66ad7e82ae3556bf112b7304802f41bb106ce2a38de47266b99e95@group.calendar.google.com` |
| 日本の祝日 | `ja.japanese#holiday@group.v.calendar.google.com` |
