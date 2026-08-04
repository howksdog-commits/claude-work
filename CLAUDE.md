# CLAUDE.md

このリポジトリで作業する AI アシスタント（Claude Code）向けのガイドです。

## 1. リポジトリ概要

小学校の担任業務を自動化するための個人ワークスペースです。現在このブランチに含まれる実体は
**Google Apps Script（GAS）1 ファイルのみ**です。

| ファイル | 役割 |
|---|---|
| `device-management.gs` | 端末管理スプレッドシート（児童の端末貸与台帳）の検証・検索・転出入・年度更新を行う GAS |

ビルド設定・パッケージマネージャ・テスト・CI・リンタは**一切ありません**。`package.json`、
`.clasp.json`、`appsscript.json` も存在しません。コードは Apps Script エディタへ手動で
コピー＆ペーストして使う運用です。

### 1.1 このリポジトリのブランチ構造（重要）

**`main` / `master` ブランチは存在しません。** リポジトリは「タスクごとに独立した
`claude/*` ブランチ」という構造になっており、ブランチ間で内容が大きく異なります。

| ブランチ | 内容 |
|---|---|
| `claude/teacher-task-automation-K0uu7` | `device-management.gs`（本ブランチの祖先） |
| `claude/extract-padlet-opinions-bo8rj` | 上記 + `tanoshimiwa_sheet.gs`（短歌づくりワークシート生成） |
| `claude/google-calendar-integration-F54Oe` | 行事予定 CSV 群 + カレンダー/提出物一覧の作成ルール `CLAUDE.md` |
| `claude/morning-schedule-automation-wrLal` | 「おはよう」で朝のブリーフィングを出す `CLAUDE.md` |
| `claude/organize-student-feedback-gPXLk` | 週次所見まとめのスラッシュコマンド、Excel 移行スクリプト、引き継ぎ書 |
| `claude/schedule-input-task-FgBik` | 時間割入力タスクの引継書 `CLAUDE.md` |

このため:

- **他ブランチの `CLAUDE.md` はこのファイルとは別物**です。上書き・統合しないこと。
  各ブランチの `CLAUDE.md` はそのタスク専用の手順書として独立しています。
- ブランチ間のマージやリベースは、指示がない限り行わないこと。共通の base が古く、
  無関係なファイルを巻き込みます。
- 作業は**指定されたブランチ上のみ**で行い、`git push -u origin <branch>` でそのブランチへ push します。

## 2. 前提となるスプレッドシート構造

`device-management.gs` は、それが束縛（container-bound）されているスプレッドシートの
構造に強く依存します。

- **1 シート = 1 学年**。シート名は `1年` 〜 `6年`（`CONFIG.CLASS_SHEET_REGEX = /^(\d)年$/`）。
  この正規表現に一致しないシートは、検証・検索・端末番号の重複判定すべてから除外されます。
- **1 行目はヘッダー**（`CONFIG.HEADER_ROW = 1`）。データは 2 行目から。
- **列順は A→D 固定**: `名前 / アドレス / パスワード / 端末番号`
  （`CONFIG.COL = { NAME: 1, EMAIL: 2, PASSWORD: 3, DEVICE_ID: 4 }`）。
- 端末番号の形式は `T-001`（`CONFIG.DEVICE_ID_REGEX = /^T-\d{3}$/`）。
- 生成される特殊シート: `_検証レポート`（`CONFIG.REPORT_SHEET`）、
  `卒業生_<西暦>_6年`（`CONFIG.ARCHIVE_PREFIX`）。どちらもクラス正規表現に一致しないため、
  自動的に処理対象外になります。

> **制約**: `getStudentRows()` は `getRange(..., CONFIG.COL.DEVICE_ID)` で
> **A 列から DEVICE_ID 列までを連続読み**しています。列を追加する場合は
> `COL` の値を連番のまま維持し、右端が最大値になるようにしてください。
> 飛び番にすると読み取り範囲がずれます。

## 3. `device-management.gs` の構成

ファイルは「`// ===` の区切りコメント + 見出し」で 5 ブロックに分かれています。
この区切りスタイルを踏襲してください。

```
CONFIG                     … 全設定を先頭に集約（マジックナンバー禁止）
onOpen()                   … カスタムメニュー [端末管理] を登録
getClassSheets()           … 共通ヘルパ: クラスシート一覧
getStudentRows(sheet)      … 共通ヘルパ: 1 シート分を {rowNum,name,email,password,deviceId}[] に整形
1. データ検証レポート        … runValidation / collectIssues / makeIssue / writeReport
2. 担任への確認メール        … getHomeroomMap / sendMailToHomeroomTeachers / buildMailBody
3. 転入・転出               … showTransferInDialog / showTransferOutDialog / suggestNextDeviceId / promptText
4. 年度更新                 … runYearEndUpdate
5. 名前・端末番号で検索       … showSearchDialog / searchStudents / jumpToRow / getSearchHtml
```

### 3.1 データフロー

すべての機能は `getClassSheets()` → `getStudentRows()` の 2 段で正規化されたオブジェクト配列を
受け取ります。**シートへの直接アクセスを新規に書かず、必ずこのヘルパを経由**してください。

検証（`collectIssues()`）が見るのは 3 種類:

1. **未記入** — アドレス / パスワード / 端末番号の空欄（`名前` が空の行は空行としてスキップ）
2. **形式エラー** — 端末番号が `DEVICE_ID_REGEX` 不一致、メールが簡易パターン不一致
3. **重複** — 端末番号・アドレスが 2 人以上で衝突（該当者**全員**に issue を立てる）

`collectIssues()` の戻り値は検証レポート（`writeReport`）とメール送信
（`sendMailToHomeroomTeachers`）の両方で共有されます。判定ロジックを追加する場合は
`collectIssues()` の 1 箇所に足せば両方に反映されます。

### 3.2 検索ダイアログ（HTML）

`getSearchHtml()` が**テンプレートリテラル内に HTML 全体を埋め込んで**返します。外部
`.html` ファイルは使いません（GAS へ単一ファイルで貼り付ける運用のため）。編集時の注意:

- テンプレートリテラル内なので、`${}` を書くと GAS 側で展開されてしまいます。
  HTML/JS 側で文字列結合が必要な場合は `+` 連結を使うこと（既存コードもそうなっています）。
- ネストした `<script>` 内のシングルクォートは `\\'` とエスケープ済みです
  （例: `onclick="jump(\\'...\\')"`）。この二重エスケープを壊さないこと。
- クライアント → サーバは `google.script.run` 経由。公開されている入口は
  **`searchStudents(keyword)` と `jumpToRow(className, rowNum)` の 2 つだけ**です。
- 表示側の XSS 対策は `esc()` 関数。テーブルにセルを追加する場合も必ず `esc()` を通すこと。

## 4. 外部設定（スクリプトプロパティ）

コードに直接メールアドレスを書かないこと。担任の宛先は Apps Script の
**スクリプトプロパティ**に JSON で保存します。

- キー: `HOMEROOM_TEACHERS`
- 値の例: `{"1年":"tanaka@school.jp", "6年":"yamada@school.jp"}`

未設定の場合 `getHomeroomMap()` は日本語メッセージ付きの `Error` を投げます。
宛先が見つからないクラスはスキップされ、実行後のアラートに「担任未登録のクラス」として
一覧表示されます。

## 5. コーディング規約

- **言語**: コメント・UI 文言・エラーメッセージはすべて**日本語**。関数名・変数名は英語 lowerCamelCase。
- **設定はすべて `CONFIG` へ**。シート名・列番号・正規表現をコード中に直書きしない。
- **インデント 2 スペース**、セミコロンあり、文字列はシングルクォート、
  日本語を含む組み立ては優先的にテンプレートリテラル。
- **ES6 は使用可**（`const`/`let`、アロー関数、スプレッド、`Object.entries`、テンプレートリテラル）。
  GAS の V8 ランタイム前提です。ただし **`import` / `export` は不可**（単一グローバルスコープ）。
- **破壊的操作の前には必ず `ui.alert(..., ui.ButtonSet.OK_CANCEL)` で確認**を取る。
  行削除（転出）・年度更新・メール一斉送信はこのパターンに従っています。
- 実行結果は必ず `ui.alert()` でユーザーにフィードバックする（件数を含めるのが慣例）。
- UI 入力は `promptText(ui, title, prompt)` を使う。キャンセル時は `null` を返すので
  呼び出し側で `if (!x) return;` すること。

## 6. 開発ワークフロー

ローカルで実行・テストする手段はありません。

1. このリポジトリで `device-management.gs` を編集し、指定ブランチへコミット。
2. 動作確認は**スプレッドシート → 拡張機能 → Apps Script** に全文を貼り付け、保存 →
   スプレッドシートを再読み込み → メニュー `[端末管理]` から手動実行。
3. 初回実行時に Gmail 送信（`MailApp`）とスプレッドシート編集の認可ダイアログが出ます。

**破壊的な機能を変更したときは、必ずコピーしたスプレッドシートで先に試すよう案内すること。**
特に `runYearEndUpdate()` はシート名を書き換えるため取り消せません（コード内の確認ダイアログでも
コピー取得を促しています）。

### 6.1 コミット

- コミットメッセージは既存履歴に倣い、**簡潔な要約 1 行**。日本語・英語どちらの実績もあります
  （`Fix sheet name regex to match '◯年' format`, `引き継ぎ書を追加`）。何をなぜ変えたかを含めること。
- push は `git push -u origin <ブランチ名>`。PR は明示的に依頼されたときだけ作成します。

## 7. 既知の不整合・落とし穴

新規に作り込まないよう、また触るときに気づけるよう記録しておきます。

1. **転出入ダイアログのプロンプト文言が古い**
   `showTransferInDialog()` / `showTransferOutDialog()` は `クラス名（例: 3年1組）` と表示しますが、
   実際に受け付けるのは `3年` 形式です（`CLASS_SHEET_REGEX` が `◯年◯組` → `◯年` に変更された際の
   取り残し）。文言を触る機会があれば `例: 3年` に揃えてください。
2. **`getHomeroomMap()` の docstring の例も `1年1組` 形式のまま**で、現行のシート名と一致しません。
   実際のキーは `1年` です。
3. **転出（削除）側はクラス正規表現で検証していない**
   `showTransferOutDialog()` はシート名が存在しさえすれば削除できます（追加側は検証あり）。
   `_検証レポート` などを指定されても止まりません。
4. **`suggestNextDeviceId()` が `CONFIG` を使っていない**
   `/^T-(\d{3})$/` と上限 `999` がハードコードされています。`DEVICE_ID_REGEX` を変更しても
   ここは追従しません。
5. **`runYearEndUpdate()` の新 1 年シートのヘッダーがハードコード**
   `['名前','アドレス','パスワード','端末番号']` を直書きしています（`CONFIG.COL` と二重管理）。
6. **メール送信の割当制限**
   `MailApp.sendEmail` は 1 日あたりの送信上限（無料 Gmail アカウントで 100 通程度）があります。
   クラス数が増えても現状は問題ありませんが、ループ送信を増やす変更では留意してください。

## 8. 取り扱い上の注意（個人情報）

- このスクリプトが扱うのは**児童の氏名・メールアドレス・パスワード**です。
- 検索ダイアログは**パスワードを平文で画面表示**します。仕様として意図されたものですが、
  ログ出力（`Logger.log` / `console.log`）やレポートシートへパスワードを書き出す変更は
  行わないでください。
- 実データ（実在の児童名・アドレス・パスワード）をリポジトリにコミットしないこと。
  サンプルが必要な場合は架空の値を使います。
- **外部サービスへのデータ送信は禁止**です。`UrlFetchApp` で外部 API へ台帳データを送るような
  実装は追加しないこと。処理はスプレッドシート・Google Workspace 内で完結させます。
