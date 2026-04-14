# launchd templates

このディレクトリには、公開リポジトリ向けの `launchd` テンプレートを置きます。

方針:
- 実運用に使う `.plist` をそのまま tracked しない
- マシン固有の絶対パスは repo に含めない
- 各マシンでは `scripts/render-launchd-plists.sh` で実際の `.plist` を生成する

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
