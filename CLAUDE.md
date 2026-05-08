# カレンダー作成ルール

行事予定をGoogleカレンダー用CSVにする際は、以下の手順で行う。

1. Google Driveの「１　校務分掌」配下（生徒指導部・教務学習部・保健安全部・校務部会の各「６・７月」など対象月フォルダ）のデータを読み取る。
2. 予定を作成後、各予定に**関連するドキュメントのみ**のリンクを説明欄に記載する。関係ない予定にはリンクを付けない。
3. 完成したCSVファイルをGoogle Driveに保存する。
4. **Googleカレンダーへのアップロードはユーザー側で行う**（API経由でのイベント作成は不要）。
5. 「週案」ファイルが共有されたら、その内容を読み込んで予定を追加する（追加データはユーザーから都度提示される）。

## CSV形式
Google Calendar標準のインポート形式（Subject, Start Date, Start Time, End Date, End Time, All Day Event, Description, Location, Private）。
