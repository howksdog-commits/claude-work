#!/usr/bin/env python3
"""md2gdoc_import.py の後処理ロジックに対するオフラインの単体テスト。

Google APIへの実接続なしで、①UTF-16位置計算 ②バッチ分割時の一部失敗の
切り分け ③強調記号が奇数個の行の警告、の3点を検証する。
(実Docへの適用検証は google-api-python-client / OAuth資格情報がある環境
 =デスクトップ版で別途行う)
"""

import unittest

from md2gdoc_import import (
    apply_requests_in_batches,
    build_requests,
    check_odd_emphasis_lines,
    find_flanking_bold_fixes,
    utf16_len,
    verify_document,
)


class Utf16LenTest(unittest.TestCase):
    def test_bmp_only(self):
        self.assertEqual(utf16_len("ab"), 2)
        self.assertEqual(utf16_len("日本語"), 3)

    def test_astral_emoji_counts_as_two(self):
        # 絵文字(サロゲートペア)は1文字でUTF-16コード単位2つ分になる
        self.assertEqual(utf16_len("\U0001f600"), 2)
        self.assertEqual(utf16_len("a\U0001f600b"), 4)


class OddEmphasisLineTest(unittest.TestCase):
    def test_detects_only_odd_lines(self):
        markdown = "\n".join(
            [
                "普通の行",
                "**太字**の行",
                "**壊れた行",
                "これは**1個**と**2個**",
            ]
        )
        warnings = check_odd_emphasis_lines(markdown)
        self.assertEqual([w[0] for w in warnings], [3])
        self.assertEqual(warnings[0][2], 1)


class FindFlankingBoldFixesTest(unittest.TestCase):
    def _paragraph_document(self, content, start_index=1):
        return {
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [
                                {
                                    "startIndex": start_index,
                                    "endIndex": start_index + utf16_len(content),
                                    "textRun": {"content": content, "textStyle": {}},
                                }
                            ]
                        }
                    }
                ]
            }
        }

    def test_positions_use_utf16_units_not_python_char_count(self):
        # 絵文字(サロゲートペア)の後ろに **強調** が続くケース。
        # Python文字数で計算すると絵文字の分だけ1つ後ろにずれてしまうため、
        # UTF-16換算した位置と一致することを確認する。
        content = "\U0001f600テスト**大事**です。"
        document = self._paragraph_document(content, start_index=1)

        fixes = find_flanking_bold_fixes(document)

        self.assertEqual(len(fixes), 1)
        fix = fixes[0]
        self.assertEqual(fix["matched_text"], "大事")
        # 絵文字は2ユニット, テスト=3, ** = 2 -> open_start = 1 + 2+3+2 = 8... ではなく
        # 実際の期待値を明示的に計算して固定する
        self.assertEqual(fix["open_start"], 6)
        self.assertEqual(fix["inner_start"], 8)
        self.assertEqual(fix["inner_end"], 10)
        self.assertEqual(fix["close_end"], 12)

    def test_no_match_when_no_markers(self):
        document = self._paragraph_document("普通の文章です。")
        self.assertEqual(find_flanking_bold_fixes(document), [])

    def test_multiple_matches_in_one_paragraph(self):
        content = "**a**と**b**"
        document = self._paragraph_document(content, start_index=1)
        fixes = find_flanking_bold_fixes(document)
        self.assertEqual([f["matched_text"] for f in fixes], ["a", "b"])

    def test_recurses_into_table_cells(self):
        content = "**表の中**です"
        document = {
            "body": {
                "content": [
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {
                                                    "paragraph": {
                                                        "elements": [
                                                            {
                                                                "startIndex": 5,
                                                                "endIndex": 5 + utf16_len(content),
                                                                "textRun": {"content": content},
                                                            }
                                                        ]
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        }
        fixes = find_flanking_bold_fixes(document)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["matched_text"], "表の中")


class BuildRequestsOrderingTest(unittest.TestCase):
    def test_delete_requests_are_sorted_back_to_front(self):
        fixes = [
            {"open_start": 6, "inner_start": 8, "inner_end": 10, "close_end": 12, "matched_text": "x"},
            {"open_start": 20, "inner_start": 22, "inner_end": 24, "close_end": 26, "matched_text": "y"},
        ]
        bold_requests, delete_requests = build_requests(fixes)

        self.assertEqual(len(bold_requests), 2)
        starts = [r["deleteContentRange"]["range"]["startIndex"] for r in delete_requests]
        # 後ろの(位置が大きい)ものから順に並んでいる = 記号を後ろから消す
        self.assertEqual(starts, sorted(starts, reverse=True))
        self.assertEqual(starts, [24, 20, 10, 6])


class FakeDocsService:
    """batchUpdateの一部失敗をシミュレートするフェイクのDocs APIクライアント。"""

    def __init__(self, bad_start_indices):
        self.bad_start_indices = set(bad_start_indices)
        self.executed_batches = []

    def documents(self):
        return self

    def batchUpdate(self, documentId, body):  # noqa: N802 - Google API命名規則に合わせる
        requests = body["requests"]
        return _FakeExecutable(lambda: self._run(requests))

    def get(self, documentId):  # noqa: N802
        return _FakeExecutable(lambda: {"body": {"content": []}})

    def _run(self, requests):
        for r in requests:
            range_ = next(iter(r.values()))["range"]
            if range_["startIndex"] in self.bad_start_indices:
                raise RuntimeError(f"invalid range starting at {range_['startIndex']}")
        self.executed_batches.append(requests)
        return {}


class _FakeExecutable:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class ApplyRequestsInBatchesTest(unittest.TestCase):
    def _delete_request(self, start):
        return {"deleteContentRange": {"range": {"startIndex": start, "endIndex": start + 2}}}

    def test_one_bad_request_does_not_fail_the_others(self):
        requests = [self._delete_request(s) for s in (30, 24, 20, 10, 6)]
        service = FakeDocsService(bad_start_indices={20})

        applied, failed = apply_requests_in_batches(service, "doc123", requests, batch_size=3, label="記号削除")

        self.assertEqual(applied, 4)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["request"]["deleteContentRange"]["range"]["startIndex"], 20)

    def test_all_succeed_when_no_bad_requests(self):
        requests = [self._delete_request(s) for s in (30, 24, 20, 10, 6)]
        service = FakeDocsService(bad_start_indices=set())

        applied, failed = apply_requests_in_batches(service, "doc123", requests, batch_size=2, label="記号削除")

        self.assertEqual(applied, 5)
        self.assertEqual(failed, [])


class VerifyDocumentTest(unittest.TestCase):
    def test_counts_tables_paragraphs_and_remaining_markers(self):
        document = {
            "body": {
                "content": [
                    {"paragraph": {"elements": [{"textRun": {"content": "普通の段落"}}]}},
                    {"paragraph": {"elements": [{"textRun": {"content": "まだ**残っている**行"}}]}},
                    {
                        "table": {
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {
                                            "content": [
                                                {"paragraph": {"elements": [{"textRun": {"content": "セル"}}]}}
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    },
                ]
            }
        }
        summary = verify_document(document)
        self.assertEqual(summary["tables"], 1)
        self.assertEqual(summary["paragraphs"], 3)
        self.assertEqual(summary["remaining_markers"], 2)


if __name__ == "__main__":
    unittest.main()
