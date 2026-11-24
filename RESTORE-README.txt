# FatFish online memory backup 20261125-042001
Scope: AstrBot memory/configuration and static SnowLuma configuration.
Excluded: NapCat, QQ runtime/login state, VNC credentials, logs, caches, plugin sources and workspaces.
Consistency: per-file online snapshot; SQLite uses the online backup API.
Decrypt: age -d -i fatfish_age_identity.txt fatfish-memory-20261125-042001.tar.gz.age > fatfish-memory-20261125-042001.tar.gz.age
Restore: inspect the archive first, then restore selected paths after stopping their writers.
If split into part files: cat *.part-* > fatfish-memory-20261125-042001.tar.gz.age before decryption.
sha256: verify the decrypted tar.gz with fatfish-memory-20261125-042001.tar.gz.age.sha256.
