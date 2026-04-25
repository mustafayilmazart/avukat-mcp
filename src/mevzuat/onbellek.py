# Bu modül, scraper tarafından çekilen mevzuat metinlerini SQLite tabanlı
# disk önbelleğinde tutar. Aynı madde tekrar istendiğinde ağ trafiği yerine
# önbellekten servis edilir. Varsayılan TTL 7 gündür; yasa değişikliklerinin
# önbelleğe takılıp kalmaması için kısa tutulmuştur.

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("avukat-mcp.onbellek")

# Varsayılan TTL — 7 gün (604800 saniye)
VARSAYILAN_TTL_SN = 7 * 24 * 60 * 60


@dataclass
class OnbellekKaydi:
    """Önbellekte saklanan tek kayıt — anahtar + metin + metadata."""
    anahtar: str
    icerik: str
    kaynak: str
    alinma_zamani: float
    metadata_json: str = "{}"


class DiskOnbellegi:
    """
    SQLite tabanlı basit key-value önbellek.
    Anahtar: URL veya kanun-madde kombinasyonu.
    Aynı anahtar tekrar istenirse ve TTL dolmadıysa, diskten döndürür.
    """

    def __init__(self, db_yolu: Path, ttl_sn: int = VARSAYILAN_TTL_SN):
        # Veritabanı dosyasının tam yolu
        self.db_yolu = Path(db_yolu)
        self.ttl_sn = ttl_sn
        self.db_yolu.parent.mkdir(parents=True, exist_ok=True)
        self._tablo_olustur()

    def _baglan(self) -> sqlite3.Connection:
        """Yeni bir SQLite bağlantısı açar. Her işlem kendi bağlantısını kullanır."""
        baglanti = sqlite3.connect(str(self.db_yolu))
        baglanti.row_factory = sqlite3.Row
        return baglanti

    def _tablo_olustur(self) -> None:
        """İlk çalıştırmada tablo ve indeksi oluşturur."""
        with self._baglan() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS onbellek (
                    anahtar TEXT PRIMARY KEY,
                    icerik TEXT NOT NULL,
                    kaynak TEXT NOT NULL,
                    alinma_zamani REAL NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_alinma ON onbellek(alinma_zamani)")

    def getir(self, anahtar: str) -> Optional[OnbellekKaydi]:
        """Anahtara karşılık gelen kaydı döndürür. Süresi dolmuşsa None."""
        with self._baglan() as db:
            satir = db.execute(
                "SELECT * FROM onbellek WHERE anahtar = ?",
                (anahtar,),
            ).fetchone()

        if not satir:
            return None

        yas = time.time() - satir["alinma_zamani"]
        if yas > self.ttl_sn:
            logger.debug(f"Önbellek süresi doldu: {anahtar} ({yas:.0f}s > {self.ttl_sn}s)")
            return None

        return OnbellekKaydi(
            anahtar=satir["anahtar"],
            icerik=satir["icerik"],
            kaynak=satir["kaynak"],
            alinma_zamani=satir["alinma_zamani"],
            metadata_json=satir["metadata_json"],
        )

    def kaydet(self, anahtar: str, icerik: str, kaynak: str, metadata: Optional[dict] = None) -> None:
        """Yeni kayıt ekler veya mevcut kaydı günceller (upsert)."""
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._baglan() as db:
            db.execute("""
                INSERT INTO onbellek(anahtar, icerik, kaynak, alinma_zamani, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(anahtar) DO UPDATE SET
                    icerik = excluded.icerik,
                    kaynak = excluded.kaynak,
                    alinma_zamani = excluded.alinma_zamani,
                    metadata_json = excluded.metadata_json
            """, (anahtar, icerik, kaynak, time.time(), meta_json))

    def sil(self, anahtar: str) -> None:
        """Belirli bir kaydı siler."""
        with self._baglan() as db:
            db.execute("DELETE FROM onbellek WHERE anahtar = ?", (anahtar,))

    def temizle(self, eski_mi: bool = True) -> int:
        """
        eski_mi=True: süresi dolmuş kayıtları siler (default).
        eski_mi=False: tüm önbelleği temizler.
        """
        with self._baglan() as db:
            if eski_mi:
                esik = time.time() - self.ttl_sn
                sonuc = db.execute("DELETE FROM onbellek WHERE alinma_zamani < ?", (esik,))
            else:
                sonuc = db.execute("DELETE FROM onbellek")
            return sonuc.rowcount

    def istatistik(self) -> dict:
        """Önbellekteki kayıt sayısı ve toplam boyut."""
        with self._baglan() as db:
            satir = db.execute(
                "SELECT COUNT(*) as adet, SUM(LENGTH(icerik)) as toplam_byte FROM onbellek"
            ).fetchone()
            return {
                "kayit_sayisi": satir["adet"] or 0,
                "toplam_byte": satir["toplam_byte"] or 0,
                "ttl_saniye": self.ttl_sn,
                "db_dosyasi": str(self.db_yolu),
            }
