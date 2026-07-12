<p align="center">
  <img src="docs/readme-logo.png" alt="usage ロゴ" width="128">
</p>

# usage

### macOSのメニューバーでClaude Code、Codex、Antigravityのクォータを確認。

作業中もClaude Code、Codex、Antigravityのクォータを確認できます。`usage` はセッション上限、週ごとの上限、コストの状況をmacOSのメニューバーに表示し、セッションが中断される前に使用量を管理できるようにします。

[繁體中文](README.zh-TW.md) · [简体中文](README.zh-CN.md) · [English](README.md) · 日本語 · [한국어](README.ko.md) &nbsp;|&nbsp; [Discussions](https://github.com/aqua5230/usage/discussions) &nbsp;|&nbsp; [公式サイト](https://aqua5230.github.io/usage/)

[![CI](https://github.com/aqua5230/usage/actions/workflows/check.yml/badge.svg)](https://github.com/aqua5230/usage/actions/workflows/check.yml)
[![最新リリース](https://img.shields.io/github/v/release/aqua5230/usage)](https://github.com/aqua5230/usage/releases/latest)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![プラットフォーム](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](https://www.apple.com/macos/)
[![ライセンス：AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![OpenSSF ベストプラクティス](https://www.bestpractices.dev/projects/13538/badge)](https://www.bestpractices.dev/projects/13538)

<p align="center">
  <img src="docs/showcase.en.png" alt="usage — macOSメニューバーに固定されたClaude CodeとCodexのクォータ" width="820">
</p>

`usage` は **Claude Code、Codex、Antigravity** のクォータを画面右上に固定し、警告レベルをひと目で判断できるよう色分けして表示します。すべての数値は、すでにマシンにあるローカルファイルから受動的に読み取られます。**Anthropic / OpenAI API を呼び出すことはなく**、**キーチェーンを読み取ることもありません**。そのため、モニター自体がtoken使用量を増やすことはありません。

## なぜusage？

セッションの途中でクォータが尽きると大きな損失になります。特に、Claude Code に依存する長時間のリファクタリングやデバッグではなおさらです。`usage` は上限に達する*前に*5時間ごとと週ごとの上限を表示し、常に見える状態に保ちます。コマンドを実行する必要も、ページを開く必要もありません。答えは、いつも見る場所に表示されています。

## クイックスタート

```bash
brew install --cask aqua5230/usage/usage
```

Applicationsフォルダに自動でインストールされます。Gatekeeperを通すために一度右クリックして **Open** を選び、その後メニューバーのアイコンをクリックしてください。直接ダウンロードしたい場合や、設定の全手順を確認したい場合は、下の[インストール](#インストール)をご覧ください。

## 主な機能

### 常時可視化

- **常時表示モニター：** クォータをメニューバーに常時表示し、緑から赤への色分けで示します。セッション、週ごと、プロジェクトごとの詳細を見たいときはクリックしてください。
- **Antigravityサポート：** Antigravity（Gemini）のセッションと週ごとのクォータが、すべてのパネルで3枚目のカードとして表示されます。数値は、Antigravity CLIがすでにあなたのマシンに保存しているサインイン情報を使って公式クォータAPIから直接取得します。数分ごとに自動更新され、リセットまでのカウントダウンもリアルタイムに減っていきます。
- **コンテキストの通知と通知センター：** コンテキストウィンドウが70%に達すると、ステータスラインが `/clear` または `/compact` を促し、tokenの無駄を防ぎます。クォータ上限と回復についてのシステム通知を受け取ることもできます。
- **セクションを隠す：** 一部のツールしか使わない場合は、ワンクリックでClaude Code、Codex、またはAntigravityのセクションをメニューバーとパネルから完全に隠せます。

### ワークフロー支援

- **進捗コンシェルジュ：** 新しいClaude Codeセッションを開くと、`usage` は前回のリクエスト、未コミットの変更、未完了のtodoを含む最後の進捗をそのままAIに渡します。`/resume` も振り返りも不要です。完全にローカルで動作し、デフォルトではオフです。
- **Token セーバー：** メニューバーのトグルで、Claude CodeとCodexにセッション中はより簡潔に応答するよう求めます。コードとエラーメッセージはバイト単位でそのままに、出力tokenを節約します。メッセージごとの控えめなリマインダーにより、長い会話でも回答が冗長に戻るのを防ぎます（A/Bテスト：会話後半の回答は約40%短い状態を維持）。
- **Token浪費ヘルスチェック：** 毎日のバックグラウンド診断がログをスキャンし、ファイルの繰り返し読み込み、汚染ディレクトリ、冗長なBash出力などの無駄を検出します。問題が見つかると一行の通知を表示します。「show me」と言えば、AIが修正手順を案内します。

### レポートとインサイト

- **詳細HTMLレポート：** 日次・週次のtoken推移、プロジェクトランキング、コストを示す、すぐに共有できるHTML詳細レポートです。最近の変更を要約する**AIツール更新ダイジェスト**と、コントリビューションヒートマップおよび「Wrapped」サマリーを含む**Year in Review**を搭載しています。ワンクリックで **.html、.csv、または.png画像**として保存でき、完全オフラインで、プロジェクト名のマスキングも任意で可能です。
- **TUIとCLI：** ターミナルを使いたいですか？ `python3 main.py --tui` で高機能なTUIダッシュボードを実行するか、`python3 usage_cli.py report` で詳細分析を生成できます。

### 体験とカスタマイズ

- **10種類のビジュアルテーマ：** Classic、Matrix、Windows 95、Newspaper、Cloud Observation、Midnight Aquarium、Prism Arcade、Black Hole、World Cup 2026、Lepidoptera（blueprint）を含むパネルスタイルを切り替えられます。
- **ドラッグで並べ替え：** 任意のクォータカードをつかんで上下にドラッグすると順序を入れ替えられます。並び順はすべてのテーマで共有され、再起動後も維持されます。
- **AIタレントマーケット：** 既成のAIチームをClaude Codeに導入できます。厳選されたサブエージェントのペルソナを閲覧し、`~/.claude/agents/` にすぐインストールできます。同梱CLIにより完全にローカルで動作します。
- **スピリットコンパニオン：** 使用率のそばに小さなアニメーション付きの白いシルエットが現れます。Claudeには不死鳥、Codexにはドラゴン、Antigravityにはライオンです。それぞれのツールのtoken消費率が上がると動きも動的に速くなります。
- **自動ローカライズ：** UIテキストは繁体字中国語、簡体字中国語、英語、日本語、韓国語で利用でき、システム設定に自動的に合わせます。

## プライバシーとデータソース

- 使用量の数値は、マシン上の**ローカルログファイルのみ**から読み取られます。
- **Anthropic / OpenAI API を呼び出すことはなく**、**キーチェーンを読み取ることもありません**（macOSのパスワード保管庫）。
- Antigravityのクォータは、Antigravity CLIがサインイン後にローカルへ保存するOAuth tokenを使って公式クォータAPIに問い合わせて取得します。`usage` はそのtokenファイルを読み取り専用として扱い、この呼び出しもクォータ情報を読むだけです——あなたのモデルクォータを消費することは決してありません。
- ネットワーク通信は、コスト見積もり用の公開モデル価格表の取得（オフライン時は内蔵価格にフォールバック）と、GitHubでの新バージョン確認をときどき行うだけです。**何もアップロードされることはありません。**

## 必要環境

- macOS
- Claude Code、Codex、またはAntigravityを少なくとも一度使用済みであること（ローカル使用量データが存在するため）。
- （ソースから実行する場合のみ）Python 3.13。

## インストール

### 1. Homebrew（推奨）

Homebrew経由でインストールすると、`brew upgrade --cask usage` 一回で最新の状態に保てます。

```bash
brew install --cask aqua5230/usage/usage
```

*（初回起動：Finderで `usage.app` を右クリック → **Open** を選び、Gatekeeperを通します）。*

### 2. Appをダウンロード

1. [GitHub Releasesページ](https://github.com/aqua5230/usage/releases/latest)から最新の `usage.app.zip` をダウンロードします。
2. 展開し、`usage.app` をApplicationsフォルダにドラッグします。
3. 初回起動：Finderで `usage.app` を右クリック → **Open** → Openを確認します。

### 初回起動：ステータスラインを設定

Codexを使用したことがある場合、`usage` はその履歴を自動で取得します。Claude Codeの場合は、アプリのポップオーバーで **「Set Up Status Line」** ボタンをクリックし、同期hookをインストールしてください。
その後、該当するツールを再起動します（Claude CodeをCmd+Qで完全に終了してから再度開きます）。

設定が完了すると、Claude Codeウィンドウ下部に次のようなステータスラインが表示されます。

<p align="center">
  <img src="docs/statusline.en.png" alt="Claude Codeのステータスライン表示（英語）" width="640">
</p>

## テーマギャラリー

UIから直接 **10種類のビジュアルテーマ**を切り替えられます。

<p align="center">
  <img src="docs/matrix.en.png" width="32%" alt="Matrixテーマ" />
  <img src="docs/win95.en.png" width="32%" alt="Windows 95テーマ" />
  <img src="docs/world_cup.en.png" width="32%" alt="World Cup HUDテーマ" />
  <img src="docs/newspaper.en.png" width="32%" alt="Newspaperテーマ" />
  <img src="docs/aquarium.en.png" width="32%" alt="Aquariumテーマ" />
  <img src="docs/black_hole.en.png" width="32%" alt="Black Holeテーマ" />
</p>

## トラブルシューティング

メニューバーに `--` と表示される場合、通常は故障ではなく、まだローカルデータがないだけです。

| 症状 | 考えられる原因 | 対処法 |
|---------|--------------|-----|
| メニューバーに `--` と表示される | データがまだない、またはClaude Code hookが更新されていない | Codexで会話を一度実行します。Claude Codeでは「Set Up Status Line」をクリックするか、`python3 main.py --setup` を実行します |
| 誤って「Quit」を選んだ | プロセスが終了した | Spotlight / Applicationsから `usage.app` を起動するか、`launchctl start com.lollapalooza.usage` を実行します |
| 状態が「N minutes stale」と表示される | Claude Codeが実行されていない | Claude Codeを開いて実行したままにします |
| Codexセクションが空 | Codex履歴が見つからない | Codexで会話を実行してログを生成します |
| 今日のコストが$0.00と表示される | モデル価格情報がない | `~/.usage/pricing_cache.json` を削除するか、`USAGE_DEBUG=1` を確認します |
| Antigravityカードが表示されない | Antigravity CLIがインストールされていない、またはサインインしていない | Antigravity CLIをインストールしてサインインします。バックグラウンドのクォータ取得が成功すると、カードが自動的に表示されます |
| Appが開かない | macOS Gatekeeperにブロックされた | Finderで `usage.app` を右クリック → Open |
| Appが即座にクラッシュする（arm64） | 以前のバージョンのpy2appバンドルbug | **v0.11.1以降**にアップグレードします |

## 比較

| 機能 | usage | ccusage | TokenTracker |
|---------|:-----:|:-------:|:------------:|
| 常に画面表示 | ✅ | — | ✅ |
| macOSメニューバー | ✅ | — | ✅ |
| Claude CodeとCodexの使用量 | ✅ | Claudeのみ | ✅ |
| Antigravity（Gemini）の使用量 | ✅ | — | — |
| HTML詳細レポートとUI | ✅ | ✅ | — |
| AIタレントマーケット | ✅ | — | — |
| 進捗コンシェルジュとToken セーバー | ✅ | — | — |
| Token浪費ヘルスチェック | ✅ | — | — |
| API呼び出しゼロ | ✅ | ✅ | ✅ |
| オープンソースライセンス | AGPL-3.0 | MIT | — |

## 開発

ターミナルTUIの実行、カスタムエージェントの設定、またはAppのビルドを自分で行いたいですか？ **[開発ドキュメント](docs/DEVELOPMENT.md)**をご覧ください。

## ライセンス

AGPL-3.0-onlyの下でライセンスされています（[LICENSE](LICENSE)を参照）。フォークまたは変更版を再配布する場合は、原作者を明記し、次へのリンクを付けてください。
https://github.com/aqua5230/usage

## Star履歴

<a href="https://star-history.com/#aqua5230/usage&Date">
  <img src="https://api.star-history.com/svg?repos=aqua5230/usage&type=Date" alt="usage Star履歴チャート" width="600">
</a>
