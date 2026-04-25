# Bu modül, Türk ve uluslararası mevzuat kaynaklarından online
# arama ve bilgi çekme işlevlerini sağlar. Kural tabanlı offline
# kontrollerin yanında, canlı mevzuat sorgusu yapmak için kullanılır.

from .mevzuat_arayici import MevzuatArayici
from .yerel_kurallar import YerelKuralDeposu
from .onbellek import DiskOnbellegi
from .scraper import MevzuatScraper, MevzuatMetni
from .guncelleme import KuralGuncelleyici, GuncellemeSonucu, RESMI_KANUN_URLLERI
from .mcp_koprusu import MevzuatMCPKoprusu, KopruCevabi

__all__ = [
    "MevzuatArayici",
    "YerelKuralDeposu",
    "DiskOnbellegi",
    "MevzuatScraper",
    "MevzuatMetni",
    "KuralGuncelleyici",
    "GuncellemeSonucu",
    "RESMI_KANUN_URLLERI",
    "MevzuatMCPKoprusu",
    "KopruCevabi",
]
