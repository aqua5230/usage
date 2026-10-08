<p align="center">
  <img src="readme-logo.png" alt="usage ロゴ" width="128">
</p>

# usage

### Claude Code、Codex、Antigravity、Grok CLIのクォータを、いつでも画面に。

`usage` は5時間と週ごとの上限を macOS のメニューバーや Windows のシステムトレイに表示し、緑から赤への色で示します。長いリファクタリングの途中で上限に達して残量不足に気づくのは、痛いものです。これなら事前に把握できます。コマンドを実行する必要も、ページを開く必要もありません。

[繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md) · [English](../README.md) · 日本語 · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [公式サイト](https://aqua5230.github.io/usage/)

[![GitHub stars](https://img.shields.io/github/stars/aqua5230/usage?style=flat)](https://github.com/aqua5230/usage/stargazers)
[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![最新リリース](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/usage-cli)](https://pypi.org/project/usage-cli/)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![プラットフォーム](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/aqua5230/usage/releases/latest)
[![ライセンス：AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](../LICENSE)
[![OpenSSF ベストプラクティス](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="showcase-v3.en.png" alt="usage — macOSメニューバーに固定されたClaude Code、Codex、Antigravityのクォータ" width="820">
</p>

- **すべてのクォータを一目で把握：** Claude Code、Codex、Antigravity のセッションおよび週間上限をリセットまでのカウントダウンとともに表示し、さらに Grok CLI の週間クレジットも確認できます。
- **マシン上の既存データを読み取り：** Claude Code、Codex、Grok CLI の数値はローカルログから読み取ります。Antigravity のクォータは、その CLI が保存しているサインイン情報を使って Google の公式エンドポイントから取得されます。
- **tokenが無駄になる前に警告：** Claude Code のステータスラインがコンテキストウィンドウの膨張や prompt cache の冷えを警告します。バナーで Claude や Codex の障害も表示します。
- **Claude Code 内の支援機能：** サイドパネル、簡潔な回答、新しいセッションへの進捗引き継ぎ、クォータを意識した計画立案。すべて任意です。
- **レポートと16種類のテーマ：** token推移とコストのHTMLレポート、および選べる16種類のパネルテーマ。

## インストール

macOS 12 以降および Windows 10/11 で動作します。

**macOS（Homebrew、推奨）：**

```bash
brew install --cask aqua5230/usage/usage
```

Applications フォルダにインストールされ、`brew upgrade --cask usage` で最新の状態に保てます。直接ダウンロードしたい場合は、[最新リリース](https://github.com/aqua5230/usage/releases/latest)から `usage.app.zip` を入手し、展開して `usage.app` を Applications フォルダにドラッグしてください。

**macOSでの初回起動：** macOS 15 以降でブロックされたら「システム設定」→「プライバシーとセキュリティ」を開き、下へスクロールして**「このまま開く」**をクリックします。macOS 14 以前ではFinderで `usage.app` を右クリック → **「開く」** を一度実行します。その後、メニューバーのアイコンをクリックしてください。

**Windows：** [最新リリース](https://github.com/aqua5230/usage/releases/latest)から `usage-windows.zip` をダウンロードし、展開して `usage.exe` を実行してください。インストールは不要です。SmartScreenに**「WindowsによってPCが保護されました」**が表示されたら、**「詳細情報」**→**「実行」**をクリックします。[Windows対応](#windows対応)をご覧ください。

**ターミナルのみ、全OS対応（Linux含む）：** `uvx usage-cli` でインストール不要でターミナルインターフェースを開けます。uvが独自にPython 3.13を準備します。`usage` コマンドを常設したい場合は `uv tool install usage-cli` を実行してください。Linuxでは `usage setup` でClaude Codeのステータスラインもインストールされます。この方法にはメニューバーやトレイアプリは含まれません。

`usage` を利用するには、Claude Code、Codex、Antigravity、Grok CLI のうち少なくとも1つのデータ、または実行中の Claude デスクトップアプリが必要です。

## 初回起動：ステータスラインを設定

Codexを使用したことがある場合、`usage` はその履歴を自動で取得します。Claude Codeの場合は、アプリのポップオーバーで **「Set Up Status Line」** ボタンをクリックし、同期hookをインストールしてください。
その後、該当するツールを再起動します（macOS では Claude Code を Cmd+Q で完全に終了してから再度開き、Windows ではターミナルを再起動するか新しいセッションを開始します）。

同じボタンで、Antigravity CLI と Grok CLI がインストールされている場合はそれらのステータスラインも一緒に設定されます。インストールされていない場合は何も書き込まれません。ご自身で設定したステータスラインは事前にバックアップされ、スイッチをオフにした際に復元されます。

設定が完了すると、Claude Codeウィンドウ下部に次のようなステータスラインが表示されます。

<p align="center">
  <img src="statusline.ja.gif" alt="Claude Codeのステータスライン表示（日本語）" width="900">
</p>

## 主な機能

### 画面表示

- **メニューバーモニター：** クォータを緑から赤への色分けで表示。セッション、週ごと、プロジェクトごとの詳細を見たいときはクリックしてください。
- **Antigravityカード：** 既定でGeminiプールを表示します。`Gemini ⇄` タグをタップすると独立したClaude / GPTプールに切り替わり、選択は記憶されます。
- **Grok CLIカード：** Grok CLI自身のローカルデバッグログから週ごとのクレジット割合を表示。そのtoken使用量もコストやプロジェクト合計にカウントされます。
- **Muse Codeの利用額：** トークンと費用が今日の費用、プロジェクト合計、レポート、CLIに反映されます。Museにはローカルのクォータデータがないため、カードはありません。
- **障害アラート：** Claude Code、Claude API、またはCodex APIで障害やパフォーマンス低下が発生した場合、公開ステータスページから読み取ってオレンジ赤色のバナーを表示します。
- **コンテキストとキャッシュの警告：** コンテキストウィンドウが膨らむ前にステータスラインが `/clear` または `/compact` を促し、prompt cache が外れた理由も表示します。
- **使わない項目を非表示：** ワンクリックでClaude Code、Codex、Grok CLI、またはAntigravityのセクションをメニューバーとパネルから完全に隠せます。

### Claude Code 内

- **進捗コンシェルジュ：** 新しいセッションを開始すると、前回のリクエスト、未コミットの変更、未完了のtodoがすでにAIに引き継がれた状態で始まります。`/resume` も振り返りも不要です。デフォルトではオフです。
- **Token セーバー：** コードとエラーメッセージはバイト単位でそのままに、Claude CodeとCodexにより簡潔で平易な言葉で応答するよう求めます。実際のセッションでのA/Bテストでは、会話後半の回答も約40%短い状態を維持し、84%長くなるような冗長化は起きませんでした。
- **サイドパネル：** 作業のすぐ横で使用量、他の会話、バックグラウンド作業を確認。[サイドパネルの紹介](#claude-code-サイドパネル)。
- **初心者モード：** 各回答から専門用語を最大3つ選び、一行のやさしい説明を付けて表示し、後から復習できるようにします。初期設定はオフ。Claudeのクォータを少し使います。
- **クォータ認識モード：** クォータが少なくなると、クォータを消費する大きな作業を始める前にClaudeがそれを知らせ、小さな作業を先にやるかリセットを待つかを選ばせてくれます。初期設定はオフ。追加のモデル呼び出しはありません。
- **5 時間セッションを自動開始：** 5時間枠がリセットされた直後に各ツールへごく小さなメッセージを1通送信し、次のカウントをすぐに開始します。デフォルトはオフです。
- **Token浪費ヘルスチェック：** 毎日の診断でログをスキャンし、ファイルの繰り返し読み込みや冗長な出力を検出します。「show me」と言えば、AIが修正手順を案内します。

### レポートとその他

- **HTMLレポート：** 日次・週次のtoken推移、プロジェクトランキング、コスト、およびコントリビューションヒートマップ付きのYear in Review。完全オフラインで.html、.csv、または.pngとしてエクスポートでき、プロジェクト名のマスキングも任意で可能です。
- **ターミナル統合：** `usage status --json` は、Starship、tmux、または独自のスクリプトに Claude Code、Codex、Antigravity、Grok のクォータを渡します。[既製のスニペット](DEVELOPMENT.md#quota-status-for-other-tools-usage-status)。
- **AI更新日報：** Claude Code、Codex、Antigravityの変更点を毎日更新する公開[ウェブページ](https://aqua5230.github.io/ai-updates/)。5言語の平易な要約付き。
- **好みに合わせたレイアウト：** パネルを好きな場所にドラッグし、クォータカードをドラッグして並べ替え、16種類のテーマを切り替えられます。UIはシステム言語（繁体字中国語、簡体字中国語、英語、日本語、韓国語）に自動的に追従します。

<details>
<summary>しきい値、バージョン、詳細情報</summary>

- **コンテキストの色：** コンテキストの数値は 50% または 200K トークンで黄色、80% または 400K トークンで赤色になり、先に達した条件を使います。促しの通知は70%（埋まるのが速い場合はもっと早く）で表示されます。色が変わると、ステータスラインに画像数と「ファイルとコマンド出力」の推定割合を表示します。
- **Prompt cache：** ヒット率の表示には Claude Code 2.1.251 以降が必要です。キャッシュが外れてから10分間は、ステータスラインにその理由（モデルの変更、ツールの変更、5分以上のTTL超過など）が表示されます（2.1.260 以降が必要）。古いバージョンではこれらは表示されません。
- **通知：** クォータ上限と回復についてのシステム通知を受け取ることもできます。
- **Antigravityカード：** 数分ごとに自動更新されます。World Cup 2026（2チームの HUD のまま）を除くすべてのテーマで表示されます。
- **障害アラート：** Antigravityは公開ステータスページがないため対象外です。
- **Token浪費ヘルスチェック：** 汚染ディレクトリや冗長なBash出力も検出します。
- **Linux：** CIがUbuntu上で `usage setup` を検証しています。
- **進捗コンシェルジュ：** キャッシュが切れるほど放置した会話を `/resume` で再開すると、次のメッセージで再送信されるトークン数を知らせ、先に `/compact` するよう勧めます。
- **初心者モード（macOS／Windows）：** UIと同じ言語で用語が入力欄の上に表示されます。9を押すと「わかった」になります。スキップした用語は1日、3日、7日後にまた出てきます。わかった用語は7日、21日、60日後に1問の選択式クイズとして出題されます（1日最大1問まで）。間違えるとその用語はヒントに戻ります。`/terms` で用語の履歴を開けます。用語選びは Claude Code 経由で Claude Haiku に頼むため、5時間クォータが90%以上のあいだは自動で一時停止します。
- **クォータ認識モード（macOS／Windows）：** 5時間クォータが80%、90%、95%を超えたとき、または週間クォータが95%を超えたとき、Claude Codeに残量とリセット時刻を一行で伝えます。Claude Code、Codex、Antigravityを対象とし、各段階は1つの会話で一度だけ伝えます。各クォータとモデルグループは個別に扱われるため、使い切ったクォータはその上で実行される作業にのみ影響します。
- **5 時間セッションを自動開始：** ClaudeはHaiku、AntigravityはGemini 3.8 Flash Low、Codexは最も低コストなモデルを使用します。消費されるクォータはごくわずかです。普段の使用量の確認ではメッセージを送信することはなく、このスイッチをオンにしたときのみ送信されます。
- **パネル：** 他のアプリにフォーカスが移っても消えず、メニューバーアイコンをもう一度クリックするかEscapeキーを押すと閉じます。カードの並び順はクォータカードを含むすべてのテーマ（World Cup 2026 を除く）で共有され、再起動後も維持されます。
- **HTMLレポート：** 「最近の作業」セクションにはClaude Codeが直近の会話に付けた名前が並び、マスキング機能はそれらのタイトルも対象とします。
- **AI更新日報：** 未審査の項目は公式原文を表示します。完全な履歴が保持されます。
- **更新後の変更内容：** 更新後の初回起動時に、そのバージョンの変更内容を UI の言語で一度だけ表示します。新規インストールでは表示しません。

</details>

## Claude Code サイドパネル

Claude Code を離れずに、使用量、他の会話、バックグラウンド作業を確認できます。macOS・Windows 対応。

<p align="center"><img src="side-pane.png" alt="使用量、会話、バックグラウンド作業を表示する Claude Code サイドパネル" width="637"></p>

**表示されるもの**

- **使用量：** 5時間と週間の上限。
- **Claude の会話：** 権限の確認や MCP への入力を待つ会話は黄色で表示されます。
- **会話の通知：** 他の Claude の会話が完了したときや、あなたの入力を待ち始めたときに、プロジェクト名で始まる通知を表示します。
- **最新の回答：** 各会話の2行目に最新の回答を表示します。
- **バックグラウンド作業：** Claude が Agent ツールで起動したサブエージェントと、その状態も表示します。

**有効にする手順**

1. usage のメニューバーメニュー（macOS）またはシステムトレイメニュー（Windows）で、**Claude Code** サブメニューの **サイドペイン** にチェックを入れます。
2. 新しい会話を開くか `/reload-plugins` を実行します。
3. ターミナル幅が144列以上なら右側に自動で開きます。狭い場合は `/usage-dash` を入力します。

<details>
<summary>互換性と更新</summary>

- mod 対応の新しい Claude Code が必要です。2.1.289 で確認済みです。
- パネルが右側に表示されるのは Claude Code のフルスクリーン表示のときだけで、それ以外は入力欄の上に表示されます。Windows 版ではパネルを有効にするとフルスクリーン表示も有効になり、パネルをオフにすると元に戻ります。
- macOS 標準の Terminal は256色のみ対応し、灰色の背景が出る場合があります。`/config` で ANSI ダークテーマを選んでください。
- usage アプリの起動時に、有効なパネルをアプリ内のバージョンへ自動更新します。

</details>

## プライバシーとデータソース

- **ローカルログ：** Claude Code、Codex、Grok CLI、Muse Codeの数値はマシン上のログファイルから読み取られます。その内容がアップロードされることはありません。
- **Claude デスクトップ：** Claude Code CLI やステータスラインがなくても、Claude デスクトップを開いたままにしておけば、`usage` がローカルのプラン利用履歴を読み取ります。Cookie、ログイントークン、API呼び出しは不要です。リセット時刻はローカルキャッシュで確認できた場合のみ表示され、推測されることはありません。
- **Antigravity** は実際に使用している場合のみネットワーク接続が必要です：クォータは、Antigravity CLIがサインイン後に保存したOAuth資格情報を使ってGoogleの公式クォータエンドポイントから取得します——CLIのバージョンにより、macOSのキーチェーン、Windowsの資格情報マネージャー、またはローカルのtokenファイルから読み取られます。`usage` はその資格情報を書き戻すことはなく、更新されたaccess tokenもメモリ内にのみ保持します。この呼び出し自体はクォータメタデータを読み取ります。
- **その他のバックグラウンドネットワーク通信：** 障害を知らせるためのClaudeとCodexの公開ステータスページ、コスト見積もり用の公開モデル価格表の取得（オフライン時は内蔵価格を使用）、およびときどき行われるGitHubでの新バージョン確認です。
- **初心者モード** はオンにしたときだけ通信します。あなた自身の Claude Code のログインを使い、Claude Code の最新の回答を Claude Haiku に送って用語を選びます。用語の履歴は `~/.usage/glossary.json` に保存されます。

<details>
<summary>Claude デスクトップの利用枠読み取り方法</summary>

Claude Code の利用枠ファイルがない場合、`usage` はローカルの `plan-usage-history.json` を読み取ります（Windows の Microsoft Store 版も対応）。ローカルの Chromium ブロック形式 HTTP キャッシュに新しい応答があり、組織が一致する場合は、セッションと週間の正確なリセット時刻も読み取ります。新しいキャッシュを履歴のサンプリングより優先し、古いキャッシュは割合が一致する場合だけ使用します。キャッシュがない、形式が未対応、古い、またはデータが一致しない場合はカウントダウンを不明とします。

デスクトップのサンプルは通常5〜15分ごとに更新されます。パネルにデータの経過時間を表示し、30分を超えると古いデータとマークされ、2時間を超えると非表示にします。最新の組織の記録を使用し、カスタムプロファイルは検索しません。これらの利用枠キャッシュにプロジェクト別のトークン数はありません。デスクトップのセッションが `~/.claude/projects/` 配下に互換性のある Claude Code ログも書き込む場合、既存のプロジェクト・トークンレポートで集計されます。

</details>

## Windows対応

Windowsでも主要機能をすべてネイティブで利用できます：macOSと同じ16種類のテーマを備えたシステムトレイUI、Claude Codeのステータスラインhook、Codex履歴の解析に対応しています。システムトレイUIにはMicrosoft Edge WebView2 Runtimeが必要ですが、通常はWindows 10/11に含まれています。

<details>
<summary>トレイアイコン、タスクバーラベル、その他の相違点</summary>

システムトレイのアイコンにはClaudeまたはCodexのセッションクォータの残量がパーセントで表示されます。右クリックメニューまたはパネルメニューの **トレイの表示元 → Claude Code / Codex** で切り替えると、即座に反映され、再起動後も保持されます（初期値：Claude）。Codexにセッション枠がない場合は週間クォータを使用し、ツールチップにもその枠を表示します。データがない場合は `--` を表示します。ツールチップには両方の概要を表示し、選択した表示元を先頭にします。左クリックでWebView2上にクォータテーマを開きます。右クリックには「パネルの位置をリセット」と「終了」もあり、パネル切替、更新、ログイン時に起動、更新確認はパネル側のメニューにあります。

メニューで **タスクバーにクォータを表示** を有効にすると、通知領域の左側に透明な `Codex: 92%` ラベルを表示します。タスクバーの位置、画面倍率、明暗テーマに追従し、全画面表示やタスクバーの自動非表示時には隠れます。クリックするとパネルが開きます。ボタンの空き領域が足りない場合はタスクバーの外側に移動します。通常のアプリアイコンはメニュー用に残り、ラベルは選択した表示元とクォータ期間に連動します。 ラベルを右クリックすると、トレイアイコンと同じメニューが開きます。

パネルはトレイアイコンの隣ではなく作業領域の右下に開き、更新通知はシステムのYes/Noダイアログです。

</details>

### コード署名ポリシー

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

チームの役割：

- コミッターおよびレビュアー：[aqua5230](https://github.com/aqua5230)
- 承認者：[aqua5230](https://github.com/aqua5230)

プライバシーポリシー：本プログラムは、ユーザーまたはプログラムをインストールもしくは操作する人が明確に要求しない限り、他のネットワークシステムにいかなる情報も転送しません。`usage` があなたの代わりに行うネットワーク呼び出しと、それを避ける方法については、[プライバシーとデータソース](#プライバシーとデータソース)をご覧ください。

## テーマギャラリー

UIから直接 **16種類のビジュアルテーマ**を切り替えられます。

<p align="center">
  <img src="classic.en.png" width="24%" alt="Classicテーマ" />
  <img src="matrix.en.png" width="24%" alt="Matrixテーマ" />
  <img src="win95.en.png" width="24%" alt="Windows 95テーマ" />
  <img src="newspaper.en.png" width="24%" alt="Newspaperテーマ" />
</p>

<details>
<summary>他の12テーマを見る</summary>

<p align="center">
  <img src="cloud_observation.en.png" width="24%" alt="Cloud Observationテーマ" />
  <img src="aquarium.en.png" width="24%" alt="Aquariumテーマ" />
  <img src="prism_arcade.en.png" width="24%" alt="Prism Arcadeテーマ" />
  <img src="stained_glass.en.png" width="24%" alt="Stained Glassテーマ" />
  <img src="origami.en.png" width="24%" alt="Origamiテーマ" />
  <img src="black_hole.en.png" width="24%" alt="Black Holeテーマ" />
  <img src="world_cup.en.png" width="24%" alt="World Cup 2026テーマ" />
  <img src="lepidoptera.en.png" width="24%" alt="Lepidopteraテーマ" />
  <img src="migration.png" width="24%" alt="渡り鳥テーマ" />
  <img src="catppuccin.en.png" width="24%" alt="Catppuccinテーマ" />
  <img src="sketchbook.en.png" width="24%" alt="手描きノートテーマ" />
  <img src="heart_monitor.en.png" width="24%" alt="心電図モニターテーマ" />
</p>

</details>

## トラブルシューティング

メニューバーに `--` と表示される場合、通常は故障ではなく、まだローカルデータがないだけです。

| 症状 | 考えられる原因 | 対処法 |
|---------|--------------|-----|
| メニューバーに `--` と表示される | データがまだない、またはClaude Code hookが更新されていない | Codexで会話を一度実行します。Claude Codeでは「ステータスラインを設定」をクリックします（ソースから実行する場合は `python3 main.py --setup`） |
| `usage.app` 内の `main.py` を実行すると `ImportError` | バンドル版の `main.py` はアプリ内蔵のインタプリタが必要で、手動では実行できません | そのファイルは実行しないでください。アプリの「ステータスラインを設定」をクリックするか、リポジトリを clone してソースから実行します |
| 誤って「Quit」を選んだ | プロセスが終了した | SpotlightまたはApplicationsから `usage.app` を再起動してください（`launchctl start com.lollapalooza.usage` はログイン時に起動を有効にしている場合のみ機能します）。 |
| 状態が「N minutes stale」と表示される | Claude Codeが実行されていない | Claude Codeを開いて実行したままにします |
| Codexセクションが空 | Codex履歴が見つからない | Codexで会話を実行してログを生成します |
| 今日のコストが$0.00と表示される | モデル価格情報がない | `~/.usage/pricing_cache.json` を削除するか、`USAGE_DEBUG=1` を確認します |
| Antigravityカードが表示されない | Antigravity CLIがインストールされていない、またはサインインしていない | Antigravity CLIをインストールしてサインインします。バックグラウンドのクォータ取得が成功すると、カードが自動的に表示されます |
| Appが開かない | macOS Gatekeeperにブロックされた | [macOSでの初回起動](#インストール)をご覧ください |
| Windowsで「WindowsによってPCが保護されました」と表示される | SmartScreenがまだこのダウンロードを認識していない | 「詳細情報」→「実行」をクリック |

## 比較

| 機能 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 常に画面表示 | ✅ | — | ✅ |
| macOSメニューバーとWindowsシステムトレイ | ✅ | — | macOS専用 |
| Claude CodeとCodexの使用量 | ✅ | ✅ | ✅ |
| Antigravityの使用量（GeminiとClaude / GPT） | ✅ | — | — |
| Grok CLIの使用量 | ✅ | — | — |
| Muse Codeのトークン利用額 | ✅ | — | — |
| Claude CodeとCodexのサービスステータスアラート | ✅ | — | — |
| HTML詳細レポートとUI | ✅ | ✅ | — |
| Claude Code 支援機能（Token セーバー、進捗コンシェルジュ、初心者モードとクォータ認識モード、ヘルスチェック） | ✅ | — | — |
| AI更新日報 | ✅ | — | — |
| オープンソースライセンス | AGPL-3.0 | MIT | — |

## 対象外となるケース

- ターミナルでのみ作業しており、バックグラウンドでメニューバーアイコンを実行したくない場合——単発で確認できる CLI ツールのほうが適しています。
- Claude Code、Codex、Antigravity、Grok CLI、Claude デスクトップのいずれも使用していない場合——`usage` が読み取るための使用量データが存在しません。
- Linux でメニューバーを使いたい場合。現在メニューバーがあるのは macOS と Windows のみですが、ターミナルインターフェース（`uvx usage-cli`）なら Linux でも動作します。

## 開発

ソースからのビルド、カスタムエージェントの設定、またはターミナルTUIの実行については、**[開発ドキュメント](DEVELOPMENT.md)**をご覧ください。

## ライセンス

AGPL-3.0-onlyの下でライセンスされています（[LICENSE](../LICENSE)を参照）。フォークまたは変更版を再配布する場合は、原作者を明記し、次へのリンクを付けてください。
https://github.com/aqua5230/usage
