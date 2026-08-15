<p align="center">
  <img src="docs/readme-logo.png" alt="usage ロゴ" width="128">
</p>

# usage

### macOSのメニューバーとWindowsのシステムトレイでClaude Code、Codex、Antigravityのクォータを確認。

セッションの途中でクォータが尽きると大きな損失になります。特に、Claude Code に依存する長時間のリファクタリングやデバッグではなおさらです。`usage` は上限に達する*前に*5時間ごとと週ごとの上限を表示し、常に見える状態に保ちます。コマンドを実行する必要も、ページを開く必要もありません。答えは、いつも見る場所に表示されています。

[繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md) · [English](README.md) · 日本語 · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [公式サイト](https://aqua5230.github.io/usage/)

[![GitHub stars](https://img.shields.io/github/stars/aqua5230/usage?style=flat)](https://github.com/aqua5230/usage/stargazers)
[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![最新リリース](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![プラットフォーム](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)](https://github.com/aqua5230/usage/releases/latest)
[![ライセンス：AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF ベストプラクティス](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — macOSメニューバーに固定されたClaude Code、Codex、Antigravityのクォータ" width="820">
</p>

Claude CodeとCodexの数値は、すでにマシンにあるログファイルから受動的に読み取られるため、**クォータの確認で Anthropic や OpenAI の LLM API を呼び出すことはなく**、tokenを消費することもありません。唯一の例外である Antigravity のクォータは、Antigravity CLI がすでにローカルに保存しているサインイン情報を使って Google の公式クォータエンドポイントから取得されますが、これもメタデータの取得に過ぎず、モデルクォータを消費することはありません。

## クイックスタート

```bash
brew install --cask aqua5230/usage/usage
```

Applicationsフォルダに自動でインストールされます。Gatekeeperを通すために一度右クリックして **Open** を選び、その後メニューバーのアイコンをクリックしてください。直接ダウンロードしたい場合や、設定の全手順を確認したい場合は、下の[インストール](#インストール)をご覧ください。

**クイックジャンプ：** [主な機能](#主な機能) · [プライバシーとデータソース](#プライバシーとデータソース) · [必要環境](#必要環境) · [インストール](#インストール) · [ステータスライン設定](#初回起動ステータスラインを設定) · [Windows対応](#windows対応) · [テーマギャラリー](#テーマギャラリー) · [トラブルシューティング](#トラブルシューティング) · [比較](#比較) · [対象外となるケース](#対象外となるケース) · [開発](#開発)

## 主な機能

### 常時可視化

- **常時表示モニター：** クォータをメニューバーに常時表示し、緑から赤への色分けで示します。セッション、週ごと、プロジェクトごとの詳細を見たいときはクリックしてください。
- **Antigravityサポート：** Antigravity（Gemini）のセッションと週ごとのクォータが、World Cup 2026 を除くすべてのパネルで3枚目のカードとして表示されます（World Cup 2026 は2チームの HUD のままです）。数値は、Antigravity CLIがすでにあなたのマシンに保存しているサインイン情報を使って公式クォータAPIから直接取得します。数分ごとに自動更新され、リセットまでのカウントダウンもリアルタイムに減っていきます。
- **サービスステータスアラート：** Claude Code、Claude API、またはCodex APIで障害やパフォーマンス低下が発生した場合、関連パネルの底部にオレンジ赤色の警告バナーが表示されます。数値は公式の公開Statuspage.ioページからのみ読み取られ、LLM使用量APIを呼び出すことは決してありません。Antigravityは公開ステータスページがないため対象外です。
- **コンテキストの通知と通知センター：** コンテキストウィンドウが70%に達すると、ステータスラインが `/clear` または `/compact` を促し、tokenの無駄を防ぎます。クォータ上限と回復についてのシステム通知を受け取ることもできます。
- **セクションを隠す：** 一部のツールしか使わない場合は、ワンクリックでClaude Code、Codex、またはAntigravityのセクションをメニューバーとパネルから完全に隠せます。

### ワークフロー支援

- **進捗コンシェルジュ：** 新しいClaude Codeセッションを開くと、`usage` は前回のリクエスト、未コミットの変更、未完了のtodoを含む最後の進捗をそのままAIに渡します。`/resume` も振り返りも不要です。完全にローカルで動作し、デフォルトではオフです。
- **Token セーバー：** メニューバーのトグルで、Claude CodeとCodexにセッション中はより簡潔に応答するよう求めます。コードとエラーメッセージはバイト単位でそのままに、出力tokenを節約します。メッセージごとの控えめなリマインダーにより、長い会話でも回答が冗長に戻るのを防ぎます——実際のセッションでのA/Bテストでは、会話後半の回答も約40%短い状態を維持し、84%長くなるような冗長化は起きませんでした。
- **ターミナル統合：** `usage status --json` は、コマンドを実行できるあらゆるツール——Starship、tmux、または独自のスクリプト——に Claude Code および Codex のクオータを渡します。メニューバーと同じローカルファイルを読み込み、ネットワーク呼び出しは行いません。[既製のスニペット](docs/DEVELOPMENT.md#quota-status-for-other-tools-usage-status)。
- **Token浪費ヘルスチェック：** 毎日のバックグラウンド診断がログをスキャンし、ファイルの繰り返し読み込み、汚染ディレクトリ、冗長なBash出力などの無駄を検出します。問題が見つかると一行の通知を表示します。「show me」と言えば、AIが修正手順を案内します。

### AIチームワーク

- **AIタレントマーケット：** 既成のAIチームをClaude Codeに導入できます。厳選されたサブエージェントのペルソナを閲覧し、`~/.claude/agents/` にすぐインストールできます。同梱CLIにより完全にローカルで動作します。
- **AI円卓会議：** 専用ウィンドウを開き、Claude Code、Codex、Antigravityによる複数ラウンドの議論を実行できます。参加者、モデル、討論スタイルを選択でき、事前にtoken見積もりが表示されます。ラウンド間で議論を誘導でき、合意集計で誰が反対しているかを確認できるほか、全員が合意した時点で早期終了させることも可能です。席にはAIタレントマーケットのペルソナを割り当てられ、オプションの読み取り専用フォルダを介して実際の参照ファイルを含めることもできます。
- **AI更新日報：** 毎日更新される公開[ウェブページ](https://aqua5230.github.io/ai-updates/)を開き、Claude Code、Codex、Antigravityを網羅し、完全な履歴を保持します。審査済みの更新は5言語の平易な要約を、未審査のものは公式原文を表示します。

### レポートとインサイト

- **詳細HTMLレポート：** 日次・週次のtoken推移、プロジェクトランキング、コストを示す共有可能なHTML詳細レポートです。コントリビューションヒートマップおよび「Wrapped」サマリーを含むYear in Reviewを搭載しています。「最近の作業」セクションには、Claude Codeが直近の会話に付けた名前が並ぶため、数値を文脈とともに読めます。.html、.csv、または.pngとしてエクスポートでき、完全オフラインで、プロジェクト名のマスキングも任意で可能です（これらのタイトルも一緒に隠れます）。

### 体験とカスタマイズ

- **13種類のビジュアルテーマ：** Classic、Matrix、Windows 95、Newspaper、Cloud Observation、Midnight Aquarium、Prism Arcade、Black Hole、World Cup 2026、Lepidoptera（blueprint）、ステンドグラス、折り紙、Catppuccin（公式パレット、4種のflavorすべてに対応）を含むパネルスタイルを切り替えられます。
- **パネルを自由に配置：** パネルはメニューバーアイコンの下に固定されなくなりました。空白部分をドラッグして好きな場所に移動でき、次回開いたときもその位置を保持します。他のアプリにフォーカスが移っても消えず、メニューバーアイコンをもう一度クリックするかEscキーを押すと閉じます。
- **ドラッグで並べ替え：** 任意のクォータカードをつかんで上下にドラッグすると順序を入れ替えられます。並び順はクォータカードを含むすべてのテーマ（World Cup 2026 を除く）で共有され、再起動後も維持されます。
- **スピリットコンパニオン：** 使用率のそばに小さなアニメーション付きの白いシルエットが現れます。Claudeには不死鳥、Codexにはドラゴン、Antigravityにはライオンです。それぞれのツールのtoken消費率が上がると動きも動的に速くなります。
- **自動ローカライズ：** UIテキストは繁体字中国語、簡体字中国語、英語、日本語、韓国語で利用でき、システム設定に自動的に合わせます。

## プライバシーとデータソース

- Claude CodeとCodexの数値は、マシン上の**ローカルログファイルのみ**から読み取られ、それらを読み取る際に**Anthropic または OpenAI の LLM API を呼び出すことはありません**。
- Antigravityのクォータにはネットワーク接続が必要で、実際に使用している場合のみ発生します：クォータは、Antigravity CLIがサインイン後に保存したOAuth資格情報を使ってGoogleの公式クォータエンドポイントに問い合わせて取得します——CLIのバージョンにより、macOSのキーチェーン、Windowsの資格情報マネージャー、またはローカルのtokenファイルから読み取られます。`usage` はその資格情報を読み取るだけで書き戻さず、更新されたaccess tokenもメモリ内にのみ保持します。この呼び出し自体もクォータ情報を読むだけで、あなたのモデルクォータを消費することは決してありません。
- バックグラウンドのネットワーク通信は、上記のAntigravityクォータ／tokenエンドポイント、障害を知らせるためのClaudeとCodexの公開ステータスページ、コスト見積もり用の公開モデル価格表の取得（オフライン時は内蔵価格にフォールバック）、およびときどき行われるGitHubでの新バージョン確認です。Claude CodeとCodexのログ内容がアップロードされることはありません。

## 必要環境

- macOS 12（Monterey）以降、または Windows 10/11
- Claude Code、Codex、またはAntigravityを少なくとも一度使用済みであること（ローカル使用量データが存在するため）。
- （ソースから実行する場合のみ）Python 3.13。

## インストール

### 1. Homebrew（推奨）

Homebrew経由でインストールすると、`brew upgrade --cask usage` 一回で最新の状態に保てます。

```bash
brew install --cask aqua5230/usage/usage
```

*（初回起動：Finderで `usage.app` を右クリック → **Open** を選び、Gatekeeperを通します）。*

### 2. macOS版Appをダウンロード

1. [GitHub Releasesページ](https://github.com/aqua5230/usage/releases/latest)から最新の `usage.app.zip` をダウンロードします。
2. 展開し、`usage.app` をApplicationsフォルダにドラッグします。
3. 初回起動：Finderで `usage.app` を右クリック → **Open** → Openを確認します。

## 初回起動：ステータスラインを設定

Codexを使用したことがある場合、`usage` はその履歴を自動で取得します。Claude Codeの場合は、アプリのポップオーバーで **「Set Up Status Line」** ボタンをクリックし、同期hookをインストールしてください。
その後、該当するツールを再起動します（macOS では Claude Code を Cmd+Q で完全に終了してから再度開き、Windows ではターミナルを再起動するか新しいセッションを開始します）。

同じボタンで、Antigravity CLI がインストールされている場合はそのステータスラインも一緒に設定されます。インストールされていない場合は何も書き込まれません。ご自身で設定したステータスラインは事前にバックアップされ、スイッチをオフにした際に復元されます。

設定が完了すると、Claude Codeウィンドウ下部に次のようなステータスラインが表示されます。

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Codeのステータスライン表示（英語）" width="640">
</p>

## Windows対応

Windowsでも主要機能をすべてネイティブで利用できます。システムトレイUI、Claude Codeのステータスラインhook、Codex履歴の解析に対応しています。[最新のGitHub Release](https://github.com/aqua5230/usage/releases/latest)から`usage-windows.zip`をダウンロードし、展開して`usage.exe`を実行してください。インストールは不要です。システムトレイUIにはMicrosoft Edge WebView2 Runtimeが必要ですが、通常はWindows 10/11に含まれています。

システムトレイのアイコンはClaudeのクォータ率に合わせて更新され、ツールチップにはClaudeとCodexの各ウィンドウの概要が表示されます。左クリックでWebView2上にmacOSと同じ13種類のテーマパネル（Classicと他の12テーマ）を開き、右クリックでは「パネルの位置をリセット」と「終了」のみで、パネル切替、更新、ログイン時に起動、更新確認はパネル側のメニューにあります。

Windowsでの相違点：パネルはトレイアイコンの隣ではなく作業領域の右下に開きます。更新通知はシステムのYes/Noダイアログです。AI Talent MarketおよびAI円卓会議パネルはmacOS専用です。

### コード署名ポリシー

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

チームの役割：

- コミッターおよびレビュアー：[aqua5230](https://github.com/aqua5230)
- 承認者：[aqua5230](https://github.com/aqua5230)

プライバシーポリシー：本プログラムは、ユーザーまたはプログラムをインストールもしくは操作する人が明確に要求しない限り、他のネットワークシステムにいかなる情報も転送しません。`usage` があなたの代わりに行うネットワーク呼び出しと、それを避ける方法については、[プライバシーとデータソース](#プライバシーとデータソース)をご覧ください。

## テーマギャラリー

UIから直接 **13種類のビジュアルテーマ**を切り替えられます。

<p align="center">
  <img src="docs/classic.en.png" width="32%" alt="Classicテーマ" />
  <img src="docs/matrix.en.png" width="32%" alt="Matrixテーマ" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95テーマ" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaperテーマ" />
  <img src="docs/cloud_observation.en.png" width="32%" alt="Cloud Observationテーマ" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquariumテーマ" />
  <img src="docs/prism_arcade.en.png" width="32%" alt="Prism Arcadeテーマ" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Holeテーマ" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUDテーマ" />
  <img src="docs/lepidoptera.en.png" width="32%" alt="Lepidopteraテーマ" />
</p>

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
| Appが開かない | macOS Gatekeeperにブロックされた | Finderで `usage.app` を右クリック → Open |

## 比較

| 機能 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 常に画面表示 | ✅ | — | ✅ |
| macOSメニューバーとWindowsシステムトレイ | ✅ | — | macOS専用 |
| Claude CodeとCodexの使用量 | ✅ | Claudeのみ | ✅ |
| Antigravity（Gemini）の使用量 | ✅ | — | — |
| Claude CodeとCodexのサービスステータスアラート | ✅ | — | — |
| HTML詳細レポートとUI | ✅ | ✅ | — |
| AIタレントマーケット | macOS専用 | — | — |
| AI円卓会議 | macOS専用 | — | — |
| AI更新日報 | ✅ | — | — |
| 進捗コンシェルジュとToken セーバー | ✅ | — | — |
| Token浪費ヘルスチェック | ✅ | — | — |
| クォータ読取時のLLM API呼び出しなし | ✅ | ✅ | ✅ |
| オープンソースライセンス | AGPL-3.0 | MIT | — |

## 対象外となるケース

- ターミナルでのみ作業しており、バックグラウンドでメニューバーアイコンを実行したくない場合——単発で確認できる CLI ツールのほうが適しています。
- Claude Code、Codex、Antigravity のいずれも使用していない場合——`usage` が読み取るためのローカル使用量データが存在しません。
- Linux を使用している場合——現在は macOS と Windows のみサポートしています。

## 開発

ソースからのビルド、カスタムエージェントの設定、またはターミナルTUIの実行については、**[開発ドキュメント](docs/DEVELOPMENT.md)**をご覧ください。

## ライセンス

AGPL-3.0-onlyの下でライセンスされています（[LICENSE](LICENSE)を参照）。フォークまたは変更版を再配布する場合は、原作者を明記し、次へのリンクを付けてください。
https://github.com/aqua5230/usage
