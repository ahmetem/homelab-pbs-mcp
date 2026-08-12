# homelab-pbs-mcp — proje talimatları

<!-- Hedef 40-80 satır. Codebase'den okunabileni yazma. YAZ: komut, koşum yeri,
     sapan konvansiyon, tuzak. -->

## Ne / nerede koşuyor
- **Ne:** Proxmox Backup Server için özel MCP sunucusu — datastore durumu, snapshot,
  GC, prune, verify, task takibi.
- **Hedef sistem:** CT 205 `pbs` (192.168.1.27), datastore `wdmycloud` (WD My Cloud NAS,
  NFS üzerinden).
- **Nerede:** **Yerel makinede** stdio MCP olarak koşar — Claude Desktop config'inde
  `pbs` adıyla kayıtlı (`python pbs_mcp.py`).
- **Sürüm yeri:** `pyproject.toml` + `CHANGELOG.md`
- **Kod keşfi:** CBM indeksli · graphify grafında var

## Komutlar

    python -m pytest
    python pbs_mcp.py             # stdio MCP; normalde Claude başlatır

## Nereye bakılır
- Araçlar `pbs_mcp/tools/` altında; araç envanterini oradan oku (sayı yazmıyorum, bayatlar)
- **`pbs_mcp/mcp_instance.py` SDK'nın server sınıfına dokunan TEK modüldür** (v0.4.0,
  spec revizyonu 2026-07-28): `MCPServer` importu `ImportError`'da 1.x'in `FastMCP`'sine
  düşer. Decorator API taşınmadığı için araçlar iki majörde de aynı kaydolur. Başka
  modüle `mcp.server.*` importu ekleme — 1.x'te sessizce kırılır.
- `moderate` modda indeksleme `pbs_mcp/tools/` altını filtreleyebiliyor — CBM ile kod
  ararken tool handler'ları göremezsen indeksin `full` modda olduğundan emin ol

## Veri ve bağımlılıklar
- **Zorunlu env:** `PBS_HOST`, `PBS_TOKEN_ID`, `PBS_TOKEN_SECRET`; opsiyonel
  `PBS_{NODE,VERIFY_TLS,DEFAULT_DATASTORE,HTTP_TIMEOUT}` — `.env.example`'da
- **`PBS_ALLOW_WRITE`** — yazma yeteneğini açan ayrı kapı; varsayılan kapalı kalmalı

## Bu projeye özgü kısıtlar
- Yıkıcı işlemler (`forget_snapshot`, `prune`, `run_gc`) yedek **silen** işlemlerdir:
  `prune_dry_run` ile önce göster, sonra uygula. Bu sıra atlanmaz.
- `PBS_ALLOW_WRITE`'ı kalıcı açık bırakma; yalnız o iş için aç.

## Tuzaklar
- Datastore NFS üzerinde: kilit hataları (`ENOLCK`) ve `all_squash`/`local_lock` ayarları
  bu kurulumun bilinen kırılganlığı — dosya kilidi hatasını koddaki bug sanma.
  Operasyonel ayrıntı `pbs-homelab` skill'inde.
- Değişiklik geçmişi: `CHANGELOG.md`
