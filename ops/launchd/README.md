# launchd templates

このディレクトリには、公開リポジトリ向けの `launchd` テンプレートを置きます。

方針:
- 実運用に使う `.plist` をそのまま tracked しない
- マシン固有の絶対パスは repo に含めない
- 各マシンでは `scripts/render-launchd-plists.sh` で実際の `.plist` を生成する

含まれるテンプレート:
- `com.forme.jobhub.mail-sync.plist.in` -> `scripts/sync-mail.sh`
- `com.forme.jobhub.source-scan.plist.in` -> `scripts/scan-sources.sh`
- `com.forme.jobhub.digest-morning.plist.in` -> `scripts/build-digest.sh morning`
- `com.forme.jobhub.digest-evening.plist.in` -> `scripts/build-digest.sh evening`

生成例:

```bash
cd /path/to/forme-local
./scripts/render-launchd-plists.sh
```

既定の出力先:

```text
~/Library/LaunchAgents
```

別の出力先を使う場合:

```bash
./scripts/render-launchd-plists.sh /tmp/launchagents
```

生成後の読み込み例:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.mail-sync.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.source-scan.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.digest-morning.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.forme.jobhub.digest-evening.plist
```
