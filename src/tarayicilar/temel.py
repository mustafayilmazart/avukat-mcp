# Bu modül, tüm tarayıcıların türediği temel sınıfı (BaseTarayici) ve
# bulgular için kullanılan Bulgu veri sınıfını tanımlar.
# Dosya tarama, filtreleme ve regex arama altyapısı burada yer alır.

import re
import asyncio
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Pattern


# Bulgu: Tarama sırasında tespit edilen her hukuki/teknik sorunu temsil eder.
@dataclass
class Bulgu:
    id: str                          # Benzersiz bulgu kimliği (örn: "GUV-001")
    seviye: str                      # Seviye: kritik / yuksek / orta / dusuk / bilgi
    kategori: str                    # Hangi tarayıcı alanı: guvenlik, gizlilik, lisans vb.
    baslik: str                      # Kısa başlık
    dosya: str                       # Bulgunu tespit eden dosya yolu
    satir: int                       # Kaçıncı satırda bulundu (0 = dosya düzeyinde)
    aciklama: str                    # Detaylı açıklama
    mevzuat: List[str] = field(default_factory=list)   # İlgili yasa/madde referansları
    duzeltme: str = ""               # Önerilen düzeltme adımları
    oncelik: int = 5                 # 1 (en acil) – 10 (en düşük) öncelik


# Taranmayacak dizinler — bağımlılık klasörleri, önbellek ve derleme çıktıları
ATLANAN_DIZINLER = {
    "node_modules", ".venv", "venv", "__pycache__",
    ".git", ".next", "build", "dist", ".cache",
    ".mypy_cache", ".pytest_cache", "coverage",
}

# Taranacak dosya uzantıları
TARANACAK_UZANTILAR = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".html", ".css", ".json", ".env",
    ".yaml", ".yml", ".toml", ".cfg",
}


class BaseTarayici:
    """
    Tüm tarayıcıların türediği temel sınıf.
    Proje dizinini dolaşır, uygun dosyaları bulur ve regex ile içerik arar.
    Alt sınıflar `tara()` metodunu override ederek kendi mantıklarını uygular.
    """

    def __init__(self, proje_dizini: str):
        # Taranacak proje kök dizini
        self.proje_dizini = Path(proje_dizini)
        self.bulgular: List[Bulgu] = []
        self._bulgu_sayaci = 0

    def _bulgu_id_uret(self, prefix: str) -> str:
        """Her bulgu için sıralı bir kimlik üretir: örn. GUV-001"""
        self._bulgu_sayaci += 1
        return f"{prefix}-{self._bulgu_sayaci:03d}"

    def _dosyalari_listele(self, ekstra_uzantilar: Optional[set] = None) -> List[Path]:
        """
        Proje dizinini özyinelemeli tarar.
        Atlanan dizinleri ve geçersiz uzantıları filtreler.
        """
        uzantilar = TARANACAK_UZANTILAR | (ekstra_uzantilar or set())
        sonuc = []

        for yol in self.proje_dizini.rglob("*"):
            # Atlanan dizin kontrolü
            if any(atlanan in yol.parts for atlanan in ATLANAN_DIZINLER):
                continue
            # Sadece dosya ve uzantı eşleşmesi
            if yol.is_file() and yol.suffix.lower() in uzantilar:
                sonuc.append(yol)

        return sonuc

    async def _dosya_oku(self, dosya_yolu: Path) -> Optional[str]:
        """Dosyayı asenkron okur. Binary veya okunamayan dosyaları atlar."""
        try:
            loop = asyncio.get_event_loop()
            icerik = await loop.run_in_executor(
                None,
                lambda: dosya_yolu.read_text(encoding="utf-8", errors="ignore")
            )
            return icerik
        except Exception:
            return None

    async def _icerik_ara(
        self,
        dosya_yolu: Path,
        pattern: Pattern,
        icerik: Optional[str] = None
    ) -> List[tuple]:
        """
        Verilen regex pattern'i dosya içeriğinde arar.
        Eşleşen her satır için (satir_no, satir_metni, eslesme) döndürür.
        """
        if icerik is None:
            icerik = await self._dosya_oku(dosya_yolu)
        if not icerik:
            return []

        eslesme_listesi = []
        for satir_no, satir in enumerate(icerik.splitlines(), start=1):
            eslesme = pattern.search(satir)
            if eslesme:
                eslesme_listesi.append((satir_no, satir.strip(), eslesme))

        return eslesme_listesi

    def _dosya_var_mi(self, *isimler: str) -> Optional[Path]:
        """
        Proje kökünde veya alt dizinlerde belirtilen isimlerden birini arar.
        Bulunan ilk eşleşmeyi döndürür.
        """
        for isim in isimler:
            # Kök dizinde doğrudan ara
            dogrudan = self.proje_dizini / isim
            if dogrudan.exists():
                return dogrudan
            # Alt dizinlerde ara
            for yol in self.proje_dizini.rglob(isim):
                if not any(atlanan in yol.parts for atlanan in ATLANAN_DIZINLER):
                    return yol
        return None

    async def tara(self) -> List[Bulgu]:
        """
        Alt sınıflar bu metodu override eder.
        Tarama sonucunda Bulgu listesi döndürür.
        """
        raise NotImplementedError("Alt sınıf tara() metodunu uygulamalıdır.")
