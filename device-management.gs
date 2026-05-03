/**
 * 端末管理スプレッドシート 自動化スクリプト
 *
 * 【セットアップ】
 *  1. スプレッドシートを開く → 拡張機能 → Apps Script
 *  2. このファイルの内容を貼り付けて保存
 *  3. スプレッドシートを再読み込みするとメニュー [端末管理] が追加される
 *
 * 【前提とするシート構成】
 *  - 1シート＝1クラス（例: "1年1組", "6年2組"）
 *  - 1行目はヘッダー: 名前 / アドレス / パスワード / 端末番号
 *  - 設定はこのファイル先頭の CONFIG で変更可能
 */

const CONFIG = {
  // クラスシート名のパターン（例: "1年1組"）
  CLASS_SHEET_REGEX: /^(\d)年(\d)組$/,

  // 端末番号の形式（例: "T-001"）
  DEVICE_ID_REGEX: /^T-\d{3}$/,
  DEVICE_ID_EXAMPLE: 'T-001',

  // 列の並び（A列=1）
  COL: { NAME: 1, EMAIL: 2, PASSWORD: 3, DEVICE_ID: 4 },

  // ヘッダー行
  HEADER_ROW: 1,

  // 検証レポートを出力するシート名
  REPORT_SHEET: '_検証レポート',

  // 卒業生アーカイブのシート名プレフィックス
  ARCHIVE_PREFIX: '卒業生_',

  // 担任メール送信時の件名
  MAIL_SUBJECT: '【端末管理】要確認データのお知らせ',
};

// ============================================================
// メニュー登録
// ============================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('端末管理')
    .addItem('✅ データ検証レポートを出す', 'runValidation')
    .addItem('📧 各担任に確認メールを送る', 'sendMailToHomeroomTeachers')
    .addSeparator()
    .addItem('🔍 名前・端末番号で検索', 'showSearchDialog')
    .addSeparator()
    .addItem('👤 転入生を追加', 'showTransferInDialog')
    .addItem('👤 転出生を削除', 'showTransferOutDialog')
    .addSeparator()
    .addItem('🔄 年度更新を実行', 'runYearEndUpdate')
    .addToUi();
}

// ============================================================
// 共通: クラスシートを取得
// ============================================================
function getClassSheets() {
  return SpreadsheetApp.getActive()
    .getSheets()
    .filter(s => CONFIG.CLASS_SHEET_REGEX.test(s.getName()));
}

function getStudentRows(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow <= CONFIG.HEADER_ROW) return [];
  const range = sheet.getRange(
    CONFIG.HEADER_ROW + 1, 1,
    lastRow - CONFIG.HEADER_ROW, CONFIG.COL.DEVICE_ID
  );
  return range.getValues().map((row, i) => ({
    rowNum: CONFIG.HEADER_ROW + 1 + i,
    name: String(row[CONFIG.COL.NAME - 1] || '').trim(),
    email: String(row[CONFIG.COL.EMAIL - 1] || '').trim(),
    password: String(row[CONFIG.COL.PASSWORD - 1] || '').trim(),
    deviceId: String(row[CONFIG.COL.DEVICE_ID - 1] || '').trim(),
  }));
}

// ============================================================
// 1. データ検証レポート
// ============================================================
function runValidation() {
  const issues = collectIssues();
  writeReport(issues);
  SpreadsheetApp.getUi().alert(
    `検証完了：${issues.length}件の要確認項目を「${CONFIG.REPORT_SHEET}」に出力しました。`
  );
}

function collectIssues() {
  const issues = [];
  const deviceIdMap = {}; // 端末番号 → [{className, name}]
  const emailMap = {};

  getClassSheets().forEach(sheet => {
    const className = sheet.getName();
    getStudentRows(sheet).forEach(stu => {
      if (!stu.name) return; // 空行はスキップ

      // 未記入チェック
      if (!stu.email) issues.push(makeIssue(className, stu, '未記入', 'アドレスが空欄'));
      if (!stu.password) issues.push(makeIssue(className, stu, '未記入', 'パスワードが空欄'));
      if (!stu.deviceId) issues.push(makeIssue(className, stu, '未記入', '端末番号が空欄'));

      // 形式チェック
      if (stu.deviceId && !CONFIG.DEVICE_ID_REGEX.test(stu.deviceId)) {
        issues.push(makeIssue(
          className, stu, '形式エラー',
          `端末番号「${stu.deviceId}」が形式違反（例: ${CONFIG.DEVICE_ID_EXAMPLE}）`
        ));
      }
      if (stu.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(stu.email)) {
        issues.push(makeIssue(className, stu, '形式エラー', `アドレス「${stu.email}」が形式違反`));
      }

      // 重複チェック用に記録
      if (stu.deviceId) {
        (deviceIdMap[stu.deviceId] = deviceIdMap[stu.deviceId] || []).push({ className, ...stu });
      }
      if (stu.email) {
        (emailMap[stu.email] = emailMap[stu.email] || []).push({ className, ...stu });
      }
    });
  });

  // 重複チェック
  Object.entries(deviceIdMap).forEach(([id, list]) => {
    if (list.length > 1) {
      list.forEach(s => issues.push(makeIssue(
        s.className, s, '重複',
        `端末番号「${id}」が ${list.length} 人に重複（${list.map(x => x.className + '/' + x.name).join(', ')}）`
      )));
    }
  });
  Object.entries(emailMap).forEach(([email, list]) => {
    if (list.length > 1) {
      list.forEach(s => issues.push(makeIssue(
        s.className, s, '重複',
        `アドレス「${email}」が重複`
      )));
    }
  });

  return issues;
}

function makeIssue(className, stu, type, detail) {
  return {
    className,
    rowNum: stu.rowNum,
    name: stu.name || '(名前未記入)',
    type,
    detail,
  };
}

function writeReport(issues) {
  const ss = SpreadsheetApp.getActive();
  let sheet = ss.getSheetByName(CONFIG.REPORT_SHEET);
  if (sheet) sheet.clear();
  else sheet = ss.insertSheet(CONFIG.REPORT_SHEET);

  const header = ['検証日時', 'クラス', '行', '名前', '種別', '内容'];
  sheet.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
  sheet.setFrozenRows(1);

  const now = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy/MM/dd HH:mm');
  if (issues.length === 0) {
    sheet.getRange(2, 1, 1, 2).setValues([[now, '✅ 問題は見つかりませんでした']]);
    return;
  }

  const rows = issues.map(i => [now, i.className, i.rowNum, i.name, i.type, i.detail]);
  sheet.getRange(2, 1, rows.length, header.length).setValues(rows);
  sheet.autoResizeColumns(1, header.length);
}

// ============================================================
// 2. 担任への確認メール
// ============================================================
/**
 * クラス名 → 担任メールアドレスの対応表
 * スクリプトプロパティに JSON で保存しておく：
 *   キー: HOMEROOM_TEACHERS
 *   値:   {"1年1組":"tanaka@school.jp", "6年2組":"yamada@school.jp"}
 */
function getHomeroomMap() {
  const raw = PropertiesService.getScriptProperties().getProperty('HOMEROOM_TEACHERS');
  if (!raw) {
    throw new Error(
      'スクリプトプロパティ HOMEROOM_TEACHERS が未設定です。\n' +
      '例: {"1年1組":"tanaka@school.jp", ...}'
    );
  }
  return JSON.parse(raw);
}

function sendMailToHomeroomTeachers() {
  const ui = SpreadsheetApp.getUi();
  const issues = collectIssues();
  if (issues.length === 0) {
    ui.alert('問題は見つかりませんでした。メールは送信しません。');
    return;
  }

  const map = getHomeroomMap();
  const byClass = {};
  issues.forEach(i => {
    (byClass[i.className] = byClass[i.className] || []).push(i);
  });

  const result = ui.alert(
    `${Object.keys(byClass).length} クラスの担任にメールを送ります。よろしいですか？`,
    ui.ButtonSet.OK_CANCEL
  );
  if (result !== ui.Button.OK) return;

  let sent = 0;
  const skipped = [];
  Object.entries(byClass).forEach(([className, list]) => {
    const to = map[className];
    if (!to) { skipped.push(className); return; }

    const body = buildMailBody(className, list);
    MailApp.sendEmail({ to, subject: CONFIG.MAIL_SUBJECT, body });
    sent++;
  });

  let msg = `${sent} 通送信しました。`;
  if (skipped.length) msg += `\n\n担任未登録のクラス: ${skipped.join(', ')}`;
  ui.alert(msg);
}

function buildMailBody(className, issues) {
  const lines = [
    `${className} の担任の先生`,
    '',
    'お疲れさまです。端末管理データに以下の要確認項目があります。',
    'スプレッドシートで該当行を修正してください。',
    '',
    '────────────────────────────',
  ];
  issues.forEach(i => {
    lines.push(`【${i.type}】${i.rowNum}行目 ${i.name}`);
    lines.push(`  → ${i.detail}`);
  });
  lines.push('────────────────────────────');
  lines.push('');
  lines.push('（このメールは端末管理スクリプトから自動送信されています）');
  return lines.join('\n');
}

// ============================================================
// 3. 転入・転出
// ============================================================
function showTransferInDialog() {
  const ui = SpreadsheetApp.getUi();
  const className = promptText(ui, '転入生を追加', 'クラス名（例: 3年1組）');
  if (!className) return;
  const sheet = SpreadsheetApp.getActive().getSheetByName(className);
  if (!sheet || !CONFIG.CLASS_SHEET_REGEX.test(className)) {
    ui.alert(`クラスシート「${className}」が見つかりません。`);
    return;
  }

  const name = promptText(ui, '転入生を追加', '名前');
  if (!name) return;
  const email = promptText(ui, '転入生を追加', 'アドレス') || '';
  const password = promptText(ui, '転入生を追加', 'パスワード') || '';

  const suggestion = suggestNextDeviceId();
  const deviceId = promptText(
    ui, '転入生を追加',
    `端末番号（空き候補: ${suggestion || 'なし'}）`
  ) || '';

  sheet.appendRow([name, email, password, deviceId]);
  ui.alert(`${className} に「${name}」を追加しました。`);
}

function showTransferOutDialog() {
  const ui = SpreadsheetApp.getUi();
  const className = promptText(ui, '転出生を削除', 'クラス名（例: 3年1組）');
  if (!className) return;
  const sheet = SpreadsheetApp.getActive().getSheetByName(className);
  if (!sheet) { ui.alert('クラスが見つかりません。'); return; }

  const name = promptText(ui, '転出生を削除', '削除する生徒の名前');
  if (!name) return;

  const rows = getStudentRows(sheet);
  const target = rows.find(r => r.name === name);
  if (!target) { ui.alert(`「${name}」が見つかりません。`); return; }

  const ok = ui.alert(
    `${className} ${target.rowNum}行目「${target.name}」（端末: ${target.deviceId || '未割当'}）を削除します。よろしいですか？`,
    ui.ButtonSet.OK_CANCEL
  );
  if (ok !== ui.Button.OK) return;

  sheet.deleteRow(target.rowNum);
  ui.alert(`削除しました。端末番号「${target.deviceId}」は空きになります。`);
}

function suggestNextDeviceId() {
  const used = new Set();
  getClassSheets().forEach(s => {
    getStudentRows(s).forEach(r => {
      const m = r.deviceId.match(/^T-(\d{3})$/);
      if (m) used.add(parseInt(m[1], 10));
    });
  });
  for (let i = 1; i <= 999; i++) {
    if (!used.has(i)) return 'T-' + String(i).padStart(3, '0');
  }
  return null;
}

function promptText(ui, title, prompt) {
  const res = ui.prompt(title, prompt, ui.ButtonSet.OK_CANCEL);
  if (res.getSelectedButton() !== ui.Button.OK) return null;
  return res.getResponseText().trim();
}

// ============================================================
// 4. 年度更新
// ============================================================
function runYearEndUpdate() {
  const ui = SpreadsheetApp.getUi();
  const ok = ui.alert(
    '年度更新を実行します：\n' +
    '  ・6年生 → 卒業生アーカイブへ\n' +
    '  ・5年→6年、4年→5年、…、1年→2年（シート名変更）\n' +
    '  ・新1年シートを空で作成\n\n' +
    '実行前に必ずスプレッドシートのコピーを取ってください。続行しますか？',
    ui.ButtonSet.OK_CANCEL
  );
  if (ok !== ui.Button.OK) return;

  const ss = SpreadsheetApp.getActive();
  const year = new Date().getFullYear();

  // 6年生をアーカイブ（シート名変更で残す）
  const sixthGraders = ss.getSheets().filter(s => /^6年\d組$/.test(s.getName()));
  sixthGraders.forEach(s => {
    const newName = `${CONFIG.ARCHIVE_PREFIX}${year}_${s.getName()}`;
    s.setName(newName);
  });

  // 5年→6年, 4年→5年, ... 1年→2年（数字が大きい順に処理して衝突回避）
  for (let g = 5; g >= 1; g--) {
    ss.getSheets().forEach(s => {
      const m = s.getName().match(/^(\d)年(\d)組$/);
      if (m && parseInt(m[1], 10) === g) {
        s.setName(`${g + 1}年${m[2]}組`);
      }
    });
  }

  // 新1年シートを既存の1年シート数だけ作成（既存の組構成を踏襲）
  const existingFirstGrade = ss.getSheets().filter(s => /^2年\d組$/.test(s.getName())).length;
  for (let i = 1; i <= existingFirstGrade; i++) {
    const name = `1年${i}組`;
    if (!ss.getSheetByName(name)) {
      const sheet = ss.insertSheet(name);
      sheet.getRange(1, 1, 1, 4).setValues([['名前', 'アドレス', 'パスワード', '端末番号']])
        .setFontWeight('bold');
      sheet.setFrozenRows(1);
    }
  }

  ui.alert('年度更新が完了しました。新1年生の名簿を入力してください。');
}

// ============================================================
// 5. 名前・端末番号で検索
// ============================================================
function showSearchDialog() {
  const html = HtmlService.createHtmlOutput(getSearchHtml())
    .setWidth(720).setHeight(520);
  SpreadsheetApp.getUi().showModalDialog(html, '🔍 検索');
}

/**
 * HTML側から呼び出される検索本体
 * keyword: 名前の一部 / アドレス / 端末番号 のいずれかで部分一致
 */
function searchStudents(keyword) {
  keyword = String(keyword || '').trim();
  if (!keyword) return [];
  const lower = keyword.toLowerCase();

  const hits = [];
  getClassSheets().forEach(sheet => {
    const className = sheet.getName();
    getStudentRows(sheet).forEach(stu => {
      if (!stu.name && !stu.deviceId && !stu.email) return;
      const blob = (stu.name + ' ' + stu.email + ' ' + stu.deviceId).toLowerCase();
      if (blob.indexOf(lower) !== -1) {
        hits.push({
          className,
          rowNum: stu.rowNum,
          name: stu.name,
          email: stu.email,
          password: stu.password,
          deviceId: stu.deviceId,
        });
      }
    });
  });
  return hits;
}

/**
 * 該当行にジャンプ（HTML側からのリンク用）
 */
function jumpToRow(className, rowNum) {
  const ss = SpreadsheetApp.getActive();
  const sheet = ss.getSheetByName(className);
  if (!sheet) return false;
  ss.setActiveSheet(sheet);
  sheet.setActiveRange(sheet.getRange(rowNum, 1, 1, CONFIG.COL.DEVICE_ID));
  return true;
}

function getSearchHtml() {
  return `
<!DOCTYPE html>
<html>
<head>
<base target="_top">
<style>
  body { font-family: -apple-system, "Hiragino Sans", sans-serif; margin: 12px; font-size: 13px; }
  .search-box { display: flex; gap: 8px; margin-bottom: 10px; }
  input[type="text"] { flex: 1; padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; }
  button { padding: 8px 16px; font-size: 14px; background: #1a73e8; color: white; border: none; border-radius: 4px; cursor: pointer; }
  button:hover { background: #1558b0; }
  .hint { color: #666; font-size: 11px; margin-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
  th { background: #f5f5f5; font-weight: bold; }
  tr:hover { background: #f0f8ff; }
  .jump { color: #1a73e8; cursor: pointer; text-decoration: underline; font-size: 11px; }
  .empty { color: #888; padding: 20px; text-align: center; }
  .count { margin-top: 8px; color: #555; font-size: 12px; }
  .password { font-family: monospace; background: #fffae6; padding: 1px 4px; }
</style>
</head>
<body>
  <div class="search-box">
    <input type="text" id="kw" placeholder="名前・アドレス・端末番号の一部を入力..." autofocus>
    <button onclick="doSearch()">検索</button>
  </div>
  <div class="hint">部分一致で検索します（例：「田中」「T-045」「tanaka@」）</div>
  <div id="result"></div>

<script>
  document.getElementById('kw').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doSearch();
  });

  function doSearch() {
    const kw = document.getElementById('kw').value;
    document.getElementById('result').innerHTML = '<div class="empty">検索中...</div>';
    google.script.run
      .withSuccessHandler(render)
      .withFailureHandler(err => {
        document.getElementById('result').innerHTML =
          '<div class="empty">エラー: ' + err.message + '</div>';
      })
      .searchStudents(kw);
  }

  function render(hits) {
    const div = document.getElementById('result');
    if (!hits || hits.length === 0) {
      div.innerHTML = '<div class="empty">該当する生徒が見つかりませんでした。</div>';
      return;
    }
    let html = '<div class="count">' + hits.length + '件ヒット</div>';
    html += '<table><thead><tr>' +
      '<th>クラス</th><th>名前</th><th>端末番号</th>' +
      '<th>アドレス</th><th>パスワード</th><th></th>' +
      '</tr></thead><tbody>';
    hits.forEach(h => {
      html += '<tr>' +
        '<td>' + esc(h.className) + '</td>' +
        '<td>' + esc(h.name) + '</td>' +
        '<td>' + esc(h.deviceId) + '</td>' +
        '<td>' + esc(h.email) + '</td>' +
        '<td><span class="password">' + esc(h.password) + '</span></td>' +
        '<td><span class="jump" onclick="jump(\\'' + esc(h.className) + '\\',' + h.rowNum + ')">該当行へ</span></td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    div.innerHTML = html;
  }

  function jump(className, rowNum) {
    google.script.run
      .withSuccessHandler(() => google.script.host.close())
      .jumpToRow(className, rowNum);
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
</script>
</body>
</html>
  `;
}
