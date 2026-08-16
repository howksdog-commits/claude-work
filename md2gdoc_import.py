#!/usr/bin/env python3
"""Markdown -> Google Doc importer with post-conversion post-processing.

背景・仕様は 学校関係/授業案/授業案タスク_引き継ぎ書.md の「2026-08-16 夜4」の記録を参照。

Driveのマークダウン→Googleドキュメント変換(files.create でmimeTypeを
application/vnd.google-apps.document にして変換させるもの)は、CommonMarkの
flanking規則により「文の途中で強調を閉じる形」(閉じ`**`の直前が「。」「）」等)
を太字化できず、`**`記号がそのまま本文に残ることがある。このスクリプトは
変換後に以下の後処理を恒久的に行う。

  1. 変換後のDocを読み直し、太字化されずに残っている `**text**` を検出して
     ①Docs APIで対象範囲を太字にし ②記号(`**`)を後ろの範囲から順に削除する。
     Googleドキュメントのインデックスは UTF-16 コード単位で数えるため
     (絵文字などBMP外の文字は1文字で2つ分)、Pythonの文字数(コードポイント数)
     をそのまま使わず、必ずUTF-16換算した位置を使う。
  2. `documents.batchUpdate` は1件でも無効な範囲があるとリクエスト全体が
     失敗するため、修正は小分けのバッチに分けて送信し、1バッチが失敗しても
     残りのバッチ・他の修正には影響させない。
  3. 変換前のマークダウンに対して、強調記号(`**`)の数が奇数の行を検出して
     警告する(このような行があると、そこから後ろの太字化がすべてずれる
     不具合が実際に発生したため)。

使い方:
    python md2gdoc_import.py 授業案.md --title "タイトル" --folder-id <ID>
    python md2gdoc_import.py 授業案.md --dry-run          # 書き込まずに検出結果のみ表示
    python md2gdoc_import.py --doc-id <ID> --confirm-existing --skip-convert
                                                            # 既存Docへの後処理のみ再実行

要 google-api-python-client / google-auth-oauthlib (post-processingを実行する場合のみ)。
"""

import argparse
import os
import re
import sys

try:
    from googleapiclient.errors import HttpError
except ImportError:  # pragma: no cover - google-api-python-client未導入の環境でも本体ロジックは読み込めるようにする
    HttpError = Exception

DEFAULT_BATCH_SIZE = 20
FLANKING_PATTERN = re.compile(r"\*\*(.+?)\*\*")
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


# ---------------------------------------------------------------------------
# ③ 前処理: 強調記号(**)が奇数個の行を警告する
# ---------------------------------------------------------------------------

def check_odd_emphasis_lines(markdown_text):
    """`**` の出現回数が奇数の行を (行番号, 行の内容, 個数) のリストで返す。

    奇数個の行は開いた `**` が閉じられていない(=変換で意図せず本文に
    記号が残る)可能性が高く、その行より後ろの太字化がすべてずれる
    不具合につながるため、変換前に警告する。
    """
    warnings = []
    for lineno, line in enumerate(markdown_text.splitlines(), start=1):
        count = line.count("**")
        if count % 2 == 1:
            warnings.append((lineno, line, count))
    return warnings


# ---------------------------------------------------------------------------
# UTF-16 コード単位の変換ヘルパー
# ---------------------------------------------------------------------------

def utf16_len(s):
    """文字列 s の長さをUTF-16コード単位で返す(絵文字などBMP外文字は2)。"""
    return len(s.encode("utf-16-le")) // 2


# ---------------------------------------------------------------------------
# Docs API のドキュメント構造を歩いて段落を集める(表のセルの中も再帰的に)
# ---------------------------------------------------------------------------

def iter_paragraphs(structural_elements):
    for el in structural_elements or []:
        if "paragraph" in el:
            yield el["paragraph"]
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    yield from iter_paragraphs(cell.get("content"))
        elif "tableOfContents" in el:
            yield from iter_paragraphs(el["tableOfContents"].get("content"))


def build_paragraph_index(paragraph):
    """段落内のtextRunを連結した文字列と、各文字がどのrunの何文字目かの対応表を作る。"""
    text_parts = []
    index_map = []  # 連結文字列の各位置 -> (run開始index(UTF-16), runのcontent, run内でのpython文字位置)
    for el in paragraph.get("elements", []):
        run = el.get("textRun")
        if not run:
            continue
        content = run.get("content", "")
        start = el.get("startIndex")
        if start is None:
            continue
        for local_idx, ch in enumerate(content):
            text_parts.append(ch)
            index_map.append((start, content, local_idx))
    return "".join(text_parts), index_map


def char_pos_to_doc_index(index_map, pos):
    """連結文字列上のPython位置posを、Docs APIのUTF-16インデックスに変換する。"""
    if not index_map:
        return None
    if pos < len(index_map):
        start, content, local_idx = index_map[pos]
        return start + utf16_len(content[:local_idx])
    # 段落末尾(最後の文字の直後)を指す場合
    start, content, local_idx = index_map[-1]
    return start + utf16_len(content[: local_idx + 1])


# ---------------------------------------------------------------------------
# ① flanking規則で取りこぼされた **text** を検出する
# ---------------------------------------------------------------------------

def find_flanking_bold_fixes(document):
    """変換後のDocに残っている `**text**` を検出し、修正すべき範囲のリストを返す。

    各要素: {open_start, inner_start, inner_end, close_end, matched_text}
    すべてUTF-16コード単位のDocs APIインデックス。
    """
    fixes = []
    body_content = document.get("body", {}).get("content", [])
    for paragraph in iter_paragraphs(body_content):
        text, index_map = build_paragraph_index(paragraph)
        if "**" not in text:
            continue
        for m in FLANKING_PATTERN.finditer(text):
            if not m.group(1):
                continue  # "****" のような中身が空のケースは対象外(安全側)
            s, e = m.start(), m.end()
            open_start = char_pos_to_doc_index(index_map, s)
            inner_start = char_pos_to_doc_index(index_map, s + 2)
            inner_end = char_pos_to_doc_index(index_map, e - 2)
            close_end = char_pos_to_doc_index(index_map, e)
            if None in (open_start, inner_start, inner_end, close_end):
                continue
            if inner_start >= inner_end:
                continue
            fixes.append(
                {
                    "open_start": open_start,
                    "inner_start": inner_start,
                    "inner_end": inner_end,
                    "close_end": close_end,
                    "matched_text": m.group(1),
                }
            )
    return fixes


def build_requests(fixes):
    """fixesから (太字化リクエスト一覧, 記号削除リクエスト一覧) を作る。

    太字化は文字位置をずらさないので順不同。
    記号削除は範囲を消すと後ろの位置がずれるため、必ず開始位置が大きい方
    (=文書の後ろの方)から先に実行できるよう降順に並べて返す
    (①太字にする→②記号を後ろから消す、の②に対応)。
    """
    bold_requests = []
    delete_items = []  # (ソート用の開始位置, リクエスト)
    for f in fixes:
        bold_requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": f["inner_start"], "endIndex": f["inner_end"]},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            }
        )
        # 閉じる方の記号(位置が大きい)を先に、開く方(位置が小さい)を後に並べる
        delete_items.append(
            (
                f["inner_end"],
                {"deleteContentRange": {"range": {"startIndex": f["inner_end"], "endIndex": f["close_end"]}}},
            )
        )
        delete_items.append(
            (
                f["open_start"],
                {"deleteContentRange": {"range": {"startIndex": f["open_start"], "endIndex": f["inner_start"]}}},
            )
        )
    delete_items.sort(key=lambda item: item[0], reverse=True)
    delete_requests = [item[1] for item in delete_items]
    return bold_requests, delete_requests


# ---------------------------------------------------------------------------
# ② batchUpdateを小分けに送る
# ---------------------------------------------------------------------------

def chunked(seq, size):
    size = max(1, size)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def apply_requests_in_batches(docs_service, doc_id, requests, batch_size, label):
    """requestsを小分けのbatchUpdateで順番に送信する。

    1件でも無効な範囲があるとbatchUpdate全体が失敗する仕様のため、まずは
    batch_size件ずつのチャンクで送り、チャンクが失敗したら1件ずつに切り
    分けて再送し、本当に無効なリクエストだけを特定してスキップする。
    (他の正常な修正まで巻き添えで失敗させない)
    """
    applied = 0
    failed = []
    for batch in chunked(list(requests), batch_size):
        try:
            docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": batch}).execute()
            applied += len(batch)
            continue
        except Exception as e:  # noqa: BLE001 - APIエラーは種類を問わず1件ずつの切り分けに回す
            if len(batch) == 1:
                failed.append({"request": batch[0], "error": str(e)})
                print(f"[error] {label}: 1件の修正が失敗しました: {e}", file=sys.stderr)
                continue
        # チャンクが失敗した場合は1件ずつ切り分けて再送する
        for single in batch:
            try:
                docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": [single]}).execute()
                applied += 1
            except Exception as e2:  # noqa: BLE001
                failed.append({"request": single, "error": str(e2)})
                print(f"[error] {label}: 1件の修正が失敗しました: {e2}", file=sys.stderr)
    return applied, failed


def postprocess_flanking_bold(docs_service, doc_id, batch_size=DEFAULT_BATCH_SIZE, dry_run=False):
    """Docを読み直し、flanking規則で残った**記号を検出して恒久的に修正する。"""
    document = docs_service.documents().get(documentId=doc_id).execute()
    fixes = find_flanking_bold_fixes(document)
    result = {
        "fixes_found": len(fixes),
        "bold_applied": 0,
        "bold_failed": [],
        "delete_applied": 0,
        "delete_failed": [],
    }
    if not fixes:
        return result
    bold_requests, delete_requests = build_requests(fixes)
    if dry_run:
        result["dry_run_fixes"] = fixes
        return result
    # ①太字にする(位置がずれないので先に全部やってよい)
    result["bold_applied"], result["bold_failed"] = apply_requests_in_batches(
        docs_service, doc_id, bold_requests, batch_size, "太字化"
    )
    # ②記号を後ろから消す
    result["delete_applied"], result["delete_failed"] = apply_requests_in_batches(
        docs_service, doc_id, delete_requests, batch_size, "記号削除"
    )
    return result


# ---------------------------------------------------------------------------
# 書き込み後の検証(化けゼロ・記号の残り0を確認するための集計)
# ---------------------------------------------------------------------------

def verify_document(document):
    body_content = document.get("body", {}).get("content", [])
    summary = {"tables": 0, "paragraphs": 0, "remaining_markers": 0}

    def walk(elements):
        for el in elements or []:
            if "paragraph" in el:
                summary["paragraphs"] += 1
                text = "".join(
                    e.get("textRun", {}).get("content", "") for e in el["paragraph"].get("elements", [])
                )
                summary["remaining_markers"] += text.count("**")
            elif "table" in el:
                summary["tables"] += 1
                for row in el["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        walk(cell.get("content"))
            elif "tableOfContents" in el:
                walk(el["tableOfContents"].get("content"))

    walk(body_content)
    return summary


# ---------------------------------------------------------------------------
# Google API呼び出し部分(google-api-python-client等が必要な処理はここに閉じ込める)
# ---------------------------------------------------------------------------

def get_credentials(token_path="token.json", credentials_path="credentials.json"):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def convert_markdown_to_doc(drive_service, markdown_path, title, folder_id=None):
    """マークダウンファイルをDriveにアップロードし、Googleドキュメントとして変換する。"""
    from googleapiclient.http import MediaFileUpload

    file_metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        file_metadata["parents"] = [folder_id]
    media = MediaFileUpload(markdown_path, mimetype="text/markdown", resumable=False)
    created = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return created["id"]


def build_services(token_path, credentials_path):
    from googleapiclient.discovery import build

    creds = get_credentials(token_path, credentials_path)
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)
    return drive_service, docs_service


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Markdown -> Google Doc 変換 + 後処理")
    parser.add_argument("markdown_file", nargs="?", help="変換元のマークダウンファイル(--skip-convert時は不要)")
    parser.add_argument("--title", help="Docのタイトル(省略時はファイル名)")
    parser.add_argument("--folder-id", help="作成先のDriveフォルダID")
    parser.add_argument("--doc-id", help="新規作成せず、指定したDoc IDに対して後処理のみ実行する")
    parser.add_argument(
        "--confirm-existing",
        action="store_true",
        help="--doc-id 指定時、既存Docへの書き込みになることを理解した上で許可する安全確認フラグ",
    )
    parser.add_argument("--skip-convert", action="store_true", help="変換をスキップし、--doc-idの後処理のみ行う")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="batchUpdateの1回あたり件数")
    parser.add_argument("--dry-run", action="store_true", help="実際には書き込まず、検出した修正内容のみ表示する")
    parser.add_argument("--credentials", default="credentials.json", help="OAuthクライアントシークレットJSON")
    parser.add_argument("--token", default="token.json", help="保存済みOAuthトークンJSON")
    args = parser.parse_args(argv)

    if args.doc_id and not args.confirm_existing:
        parser.error(
            "--doc-id を指定する場合は、既存Docへの上書きになることを理解した上で --confirm-existing を付けてください。"
        )
    if not args.doc_id and not args.skip_convert and not args.markdown_file:
        parser.error("markdown_file を指定するか、--doc-id --skip-convert で既存Docの後処理のみ実行してください。")

    if args.markdown_file and not args.skip_convert:
        with open(args.markdown_file, encoding="utf-8") as f:
            markdown_text = f.read()
        odd_lines = check_odd_emphasis_lines(markdown_text)
        if odd_lines:
            print(f"[warning] 強調記号(**)の数が奇数の行が{len(odd_lines)}件あります(この行から後ろで太字化がずれる可能性があります):")
            for lineno, line, count in odd_lines:
                print(f"  L{lineno} (**が{count}個): {line.strip()[:80]}")

    drive_service, docs_service = build_services(args.token, args.credentials)

    if args.doc_id:
        doc_id = args.doc_id
        print(f"[info] 既存Doc {doc_id} に対して後処理を実行します(--confirm-existing指定ずみ)")
    else:
        title = args.title or os.path.splitext(os.path.basename(args.markdown_file))[0]
        doc_id = convert_markdown_to_doc(drive_service, args.markdown_file, title, args.folder_id)
        print(f"[info] 新規Docを作成しました: https://docs.google.com/document/d/{doc_id}/edit")

    result = postprocess_flanking_bold(docs_service, doc_id, batch_size=args.batch_size, dry_run=args.dry_run)
    print(f"[info] flanking規則の影響を受けた箇所: {result['fixes_found']}件")

    if args.dry_run:
        for f in result.get("dry_run_fixes", []):
            print(
                f"  [dry-run] \"{f['matched_text']}\" を太字化して記号を削除"
                f" (open={f['open_start']}, close_end={f['close_end']})"
            )
        return 0

    if result["fixes_found"]:
        print(f"[info] 太字化: {result['bold_applied']}件適用 / {len(result['bold_failed'])}件失敗")
        print(f"[info] 記号削除: {result['delete_applied']}件適用 / {len(result['delete_failed'])}件失敗")
        if result["bold_failed"] or result["delete_failed"]:
            print("[warning] 一部の修正が失敗しました。Docを直接確認してください。", file=sys.stderr)

    document_after = docs_service.documents().get(documentId=doc_id).execute()
    summary = verify_document(document_after)
    print(
        f"[info] 検証: 表{summary['tables']}個 / 段落{summary['paragraphs']}個"
        f" / 強調記号の残り{summary['remaining_markers']}件"
    )
    if summary["remaining_markers"] > 0:
        print("[warning] まだ **記号 が残っています。手動で確認してください。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
