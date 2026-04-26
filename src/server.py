"""
Avukat MCP — Hukuki Uyumluluk Tarama ve Raporlama Sunucusu
============================================================
~/projects (veya AVUKAT_MCP_PROJELER_KOK env var ile belirlenen dizin) altındaki
projeleri tarar, Türkiye kanunları (KVKK, TTK, e-ticaret) ve uluslararası mevzuat
(GDPR, CCPA, DMCA, PCI-DSS, COPPA, CAN-SPAM) kapsamında hukuki uyumluluk kontrolü yapar.

Kurulum:
  git clone https://github.com/mustafayilmazart/kesif-avukat-mcp
  cd kesif-avukat-mcp
  uv sync
  # veya pip ile:
  # python -m venv .venv && source .venv/bin/activate  (Linux/Mac)
  # python -m venv .venv && .venv\\Scripts\\activate    (Windows)
  # pip install -e .

Çalıştırma:
  python src/server.py
"""

import sys
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Proje kök dizini ve veri klasörleri
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KURALLAR_DIR = DATA_DIR / "kurallar"
RAPOR_DIR = DATA_DIR / "raporlar"
CACHE_DIR = DATA_DIR / "cache"

# Gerekli dizinleri oluştur
for d in [DATA_DIR, KURALLAR_DIR, RAPOR_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Loglama (stderr'e — stdout MCP JSON-RPC için ayrılmış)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [avukat-mcp] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("avukat-mcp")

# Tarayıcı ve mevzuat modüllerini içe aktar
sys.path.insert(0, str(Path(__file__).parent))
from tarayicilar import (
    Bulgu,
    VeriToplamaTarayici, GizlilikTarayici, LisansTarayici,
    EticaretTarayici, GuvenlikTarayici, IletisimTarayici, CocukTarayici,
)
from mevzuat import (
    MevzuatArayici, YerelKuralDeposu,
    DiskOnbellegi, MevzuatScraper,
    KuralGuncelleyici, RESMI_KANUN_URLLERI,
    MevzuatMCPKoprusu,
)

# MCP SDK
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("avukat-mcp")

# Projeler kök dizini — kullanıcı kendi yolunu AVUKAT_MCP_PROJELER_KOK env var ile vermeli
# Default: home directory altında "projects" — taşınabilir
PROJELER_KOK = Path(os.environ.get(
    "AVUKAT_MCP_PROJELER_KOK",
    str(Path.home() / "projects")
))

# Taranmayacak dizinler (proje değil, yardımcı klasörler)
ATLANAN_PROJELER = {
    "node_modules", ".git", "scripts", "temp-sketchwow-extracted",
    "tessdata", "_portable", "000MCP-Servers",
}

# Ortak arayıcı, kural deposu, scraper, önbellek, köprü
# Bunlar tek sefer yüklenip tüm tool çağrılarında paylaşılır.
_kural_deposu = YerelKuralDeposu(KURALLAR_DIR)
_mevzuat_arayici = MevzuatArayici()
_onbellek = DiskOnbellegi(CACHE_DIR / "mevzuat_onbellek.sqlite")
_scraper = MevzuatScraper(onbellek=_onbellek)
_mcp_koprusu = MevzuatMCPKoprusu()
_guncelleyici = KuralGuncelleyici(KURALLAR_DIR, _onbellek, _scraper)


# ─── YARDIMCI FONKSİYONLAR ─────────────────────────────────────────

def _projeleri_listele() -> list[str]:
    """PROJELER_KOK altındaki proje dizinlerini listeler"""
    if not PROJELER_KOK.exists():
        return []
    projeler = []
    for yol in PROJELER_KOK.iterdir():
        if yol.is_dir() and yol.name not in ATLANAN_PROJELER and not yol.name.startswith("."):
            projeler.append(yol.name)
    return sorted(projeler)


async def _tum_tarayicilari_calistir(proje_yolu: str) -> list[dict]:
    """Tüm tarayıcıları bir proje üzerinde çalıştırır, bulguları birleştirir"""
    tarayicilar = [
        VeriToplamaTarayici(proje_yolu),
        GizlilikTarayici(proje_yolu),
        LisansTarayici(proje_yolu),
        EticaretTarayici(proje_yolu),
        GuvenlikTarayici(proje_yolu),
        IletisimTarayici(proje_yolu),
        CocukTarayici(proje_yolu),
    ]

    tum_bulgular: list[Bulgu] = []
    for tarayici in tarayicilar:
        try:
            bulgular = await tarayici.tara()
            tum_bulgular.extend(bulgular)
        except Exception as e:
            logger.error(f"Tarayıcı hatası ({tarayici.__class__.__name__}): {e}")

    # Bulguları önceliğe göre sırala (1 en acil)
    tum_bulgular.sort(key=lambda b: b.oncelik)

    return [_bulgu_to_dict(b) for b in tum_bulgular]


def _bulgu_to_dict(b: Bulgu) -> dict:
    """Bulgu dataclass'ını serileştirilebilir sözlüğe çevirir"""
    return {
        "id": b.id,
        "seviye": b.seviye,
        "kategori": b.kategori,
        "baslik": b.baslik,
        "dosya": str(b.dosya),
        "satir": b.satir,
        "aciklama": b.aciklama,
        "mevzuat": b.mevzuat,
        "duzeltme": b.duzeltme,
        "oncelik": b.oncelik,
    }


def _bulgulari_ozetle(bulgular: list[dict]) -> dict:
    """Bulguları seviyeye göre sayar"""
    ozet = {"kritik": 0, "yuksek": 0, "orta": 0, "dusuk": 0, "bilgi": 0}
    for b in bulgular:
        seviye = b.get("seviye", "bilgi")
        if seviye in ozet:
            ozet[seviye] += 1
    return ozet


def _markdown_rapor_olustur(proje_adi: str, bulgular: list[dict]) -> str:
    """Bulgulardan Markdown formatında hukuki uyumluluk raporu oluşturur"""
    ozet = _bulgulari_ozetle(bulgular)
    tarih = datetime.now().strftime("%Y-%m-%d %H:%M")

    satirlar = [
        f"# Hukuki Uyumluluk Raporu — {proje_adi}",
        f"**Tarih:** {tarih}",
        f"**Tarama Motoru:** Avukat MCP v1.0",
        "",
        "## Özet",
        f"- 🔴 Kritik: **{ozet['kritik']}** sorun",
        f"- 🟠 Yüksek: **{ozet['yuksek']}** sorun",
        f"- 🟡 Orta: **{ozet['orta']}** sorun",
        f"- 🔵 Düşük: **{ozet['dusuk']}** sorun",
        f"- ℹ️ Bilgi: **{ozet['bilgi']}** öneri",
        f"- **Toplam:** {len(bulgular)} bulgu",
        "",
    ]

    if not bulgular:
        satirlar.append("✅ Herhangi bir hukuki uyumluluk sorunu tespit edilmedi.")
        return "\n".join(satirlar)

    satirlar.append("## Bulgular")
    satirlar.append("")

    seviye_sirasi = ["kritik", "yuksek", "orta", "dusuk", "bilgi"]
    seviye_emoji = {"kritik": "🔴", "yuksek": "🟠", "orta": "🟡", "dusuk": "🔵", "bilgi": "ℹ️"}

    for seviye in seviye_sirasi:
        seviye_bulgulari = [b for b in bulgular if b["seviye"] == seviye]
        if not seviye_bulgulari:
            continue

        for b in seviye_bulgulari:
            emoji = seviye_emoji.get(seviye, "")
            satirlar.append(f"### {emoji} [{b['seviye'].upper()}] {b['baslik']}")
            satirlar.append(f"- **ID:** {b['id']}")
            satirlar.append(f"- **Kategori:** {b['kategori']}")
            if b["dosya"]:
                konum = f"{b['dosya']}"
                if b["satir"]:
                    konum += f":{b['satir']}"
                satirlar.append(f"- **Dosya:** `{konum}`")
            satirlar.append(f"- **Açıklama:** {b['aciklama']}")
            if b["mevzuat"]:
                satirlar.append(f"- **İlgili Mevzuat:** {', '.join(b['mevzuat'])}")
            if b["duzeltme"]:
                satirlar.append(f"- **Düzeltme Önerisi:** {b['duzeltme']}")
            satirlar.append("")

    satirlar.append("## Düzeltme Öncelikleri")
    satirlar.append("")
    satirlar.append("| Öncelik | ID | Başlık | Seviye |")
    satirlar.append("|---------|-----|--------|--------|")
    for b in bulgular[:20]:
        satirlar.append(f"| {b['oncelik']} | {b['id']} | {b['baslik']} | {b['seviye']} |")

    return "\n".join(satirlar)


def _kategoriye_gore_filtrele(bulgular: list[dict], anahtarlar: list[str], mevzuat_anahtarlari: list[str]) -> list[dict]:
    """Belirli kategorilere veya mevzuat referanslarına göre bulgu filtreler"""
    anahtarlar_kucuk = [a.lower() for a in anahtarlar]
    return [
        b for b in bulgular
        if any(a in b.get("kategori", "").lower() for a in anahtarlar_kucuk)
        or any(m in ref for m in mevzuat_anahtarlari for ref in b.get("mevzuat", []))
    ]


# ─── MCP TOOL'LARI ─────────────────────────────────────────────────

@mcp.tool()
async def proje_tara(proje_yolu: str) -> str:
    """Tek bir projeyi tarar ve hukuki sorunları tespit eder.
    proje_yolu: Proje dizin yolu (örn: ~/projects/Python-MyProject veya /absolute/path)
    """
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    logger.info(f"Proje taranıyor: {proje_yolu}")
    bulgular = await _tum_tarayicilari_calistir(proje_yolu)
    ozet = _bulgulari_ozetle(bulgular)

    return json.dumps({
        "proje": yol.name,
        "tarih": datetime.now().isoformat(),
        "ozet": ozet,
        "toplam_bulgu": len(bulgular),
        "bulgular": bulgular,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def tum_projeleri_tara() -> str:
    """AVUKAT_MCP_PROJELER_KOK altındaki tüm projeleri tarar ve hukuki uyumluluk özetini döndürür."""
    projeler = _projeleri_listele()
    logger.info(f"{len(projeler)} proje taranacak")

    sonuclar = []
    for proje_adi in projeler:
        proje_yolu = str(PROJELER_KOK / proje_adi)
        try:
            bulgular = await _tum_tarayicilari_calistir(proje_yolu)
            ozet = _bulgulari_ozetle(bulgular)
            sonuclar.append({
                "proje": proje_adi,
                "ozet": ozet,
                "toplam": len(bulgular),
                "kritik_bulgular": [b for b in bulgular if b["seviye"] == "kritik"][:3],
            })
        except Exception as e:
            sonuclar.append({"proje": proje_adi, "hata": str(e)})

    rapor_yolu = RAPOR_DIR / f"toplu_tarama_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(rapor_yolu, "w", encoding="utf-8") as f:
        json.dump(sonuclar, f, ensure_ascii=False, indent=2)

    return json.dumps({
        "tarih": datetime.now().isoformat(),
        "taranan_proje_sayisi": len(projeler),
        "rapor_dosyasi": str(rapor_yolu),
        "sonuclar": sonuclar,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def rapor_olustur(proje_adi: str) -> str:
    """Bir proje için detaylı Markdown hukuki uyumluluk raporu oluşturur.
    proje_adi: Proje klasör adı (örn: Python-KesifPortal)
    """
    proje_yolu = str(PROJELER_KOK / proje_adi)
    if not Path(proje_yolu).exists():
        return f"Hata: Proje bulunamadı — {proje_yolu}"

    bulgular = await _tum_tarayicilari_calistir(proje_yolu)
    rapor = _markdown_rapor_olustur(proje_adi, bulgular)

    rapor_dosya = RAPOR_DIR / f"{proje_adi}_{datetime.now().strftime('%Y%m%d')}.md"
    rapor_dosya.write_text(rapor, encoding="utf-8")

    return rapor


@mcp.tool()
async def mevzuat_ara(sorgu: str, ulke: str = "TR", kaynak: str = "yerel") -> str:
    """Mevzuat kaynaklarında arama yapar.
    sorgu: Aranacak konu (örn: KVKK açık rıza, GDPR cookie consent)
    ulke: TR, EU, US, GLOBAL — filtreleme için
    kaynak: 'yerel' (offline JSON) veya 'online' (mevzuat.gov.tr, kvkk.gov.tr, EUR-Lex)
    """
    if kaynak == "online":
        hedef_kaynaklar: list[str] = []
        if ulke.upper() == "TR":
            hedef_kaynaklar = ["tr", "kvkk"]
        elif ulke.upper() in ("EU", "GLOBAL"):
            hedef_kaynaklar = ["eurlex"]
        else:
            hedef_kaynaklar = ["tr", "kvkk", "eurlex"]

        online_sonuclar = await _mevzuat_arayici.coklu_kaynak_ara(sorgu, hedef_kaynaklar)
        return json.dumps({
            "sorgu": sorgu,
            "ulke": ulke,
            "kaynak": "online",
            "sonuc_sayisi": len(online_sonuclar),
            "sonuclar": [
                {
                    "kaynak": s.kaynak,
                    "baslik": s.baslik,
                    "ozet": s.ozet,
                    "link": s.link,
                    "etiketler": s.etiketler,
                }
                for s in online_sonuclar
            ],
        }, ensure_ascii=False, indent=2)

    # Varsayılan: yerel kural deposunda ara
    ulke_filtresi = None if ulke.upper() == "GLOBAL" else ulke
    yerel_sonuclar = _kural_deposu.ara(sorgu, ulke=ulke_filtresi)

    return json.dumps({
        "sorgu": sorgu,
        "ulke": ulke,
        "kaynak": "yerel",
        "sonuc_sayisi": len(yerel_sonuclar),
        "sonuclar": yerel_sonuclar,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def kural_setleri_listele() -> str:
    """Yüklü yerel kural setlerinin listesini ve istatistiklerini döndürür."""
    return json.dumps(_kural_deposu.istatistik(), ensure_ascii=False, indent=2)


@mcp.tool()
async def kvkk_kontrol(proje_yolu: str) -> str:
    """Bir projeyi KVKK (6698 sayılı Kanun) kapsamında kontrol eder."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    bulgular = await _tum_tarayicilari_calistir(proje_yolu)
    kvkk_bulgular = _kategoriye_gore_filtrele(
        bulgular,
        anahtarlar=["kvkk", "veri", "gizlilik", "privacy", "cookie", "ip_loglama", "storage"],
        mevzuat_anahtarlari=["KVKK", "6698"],
    )

    return json.dumps({
        "proje": yol.name,
        "kontrol": "KVKK",
        "toplam_bulgu": len(kvkk_bulgular),
        "bulgular": kvkk_bulgular,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def gdpr_kontrol(proje_yolu: str) -> str:
    """Bir projeyi GDPR (AB 2016/679) kapsamında kontrol eder."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    bulgular = await _tum_tarayicilari_calistir(proje_yolu)
    gdpr_bulgular = _kategoriye_gore_filtrele(
        bulgular,
        anahtarlar=["gdpr", "privacy", "consent", "cookie", "veri", "gizlilik"],
        mevzuat_anahtarlari=["GDPR", "2016/679", "ePrivacy"],
    )

    return json.dumps({
        "proje": yol.name,
        "kontrol": "GDPR",
        "toplam_bulgu": len(gdpr_bulgular),
        "bulgular": gdpr_bulgular,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def eticaret_kontrol(proje_yolu: str) -> str:
    """Bir projeyi e-ticaret mevzuatı kapsamında kontrol eder."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    tarayicilar = [EticaretTarayici(proje_yolu), GuvenlikTarayici(proje_yolu)]
    bulgular: list[Bulgu] = []
    for t in tarayicilar:
        try:
            bulgular.extend(await t.tara())
        except Exception as e:
            logger.error(f"{t.__class__.__name__}: {e}")

    bulgular_dict = [_bulgu_to_dict(b) for b in bulgular]
    bulgular_dict.sort(key=lambda x: x["oncelik"])

    return json.dumps({
        "proje": yol.name,
        "kontrol": "E-Ticaret",
        "toplam_bulgu": len(bulgular_dict),
        "bulgular": bulgular_dict,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def telif_kontrol(proje_yolu: str) -> str:
    """Bir projenin telif hakları ve yazılım lisans uyumluluğunu kontrol eder."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    tarayici = LisansTarayici(proje_yolu)
    try:
        bulgular = await tarayici.tara()
    except Exception as e:
        return json.dumps({"hata": f"Tarama hatası: {e}"}, ensure_ascii=False)

    return json.dumps({
        "proje": yol.name,
        "kontrol": "Telif/Lisans",
        "toplam_bulgu": len(bulgular),
        "bulgular": [_bulgu_to_dict(b) for b in bulgular],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def iletisim_kontrol(proje_yolu: str) -> str:
    """Projeyi ticari iletişim (İYS, CAN-SPAM, opt-in/unsubscribe) açısından kontrol eder."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    try:
        bulgular = await IletisimTarayici(proje_yolu).tara()
    except Exception as e:
        return json.dumps({"hata": f"Tarama hatası: {e}"}, ensure_ascii=False)

    return json.dumps({
        "proje": yol.name,
        "kontrol": "Ticari İletişim / İYS",
        "toplam_bulgu": len(bulgular),
        "bulgular": [_bulgu_to_dict(b) for b in bulgular],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def cocuk_kontrol(proje_yolu: str) -> str:
    """Çocuk verisi koruma (COPPA, GDPR md.8, KVKK md.6) kontrolü yapar."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    try:
        bulgular = await CocukTarayici(proje_yolu).tara()
    except Exception as e:
        return json.dumps({"hata": f"Tarama hatası: {e}"}, ensure_ascii=False)

    return json.dumps({
        "proje": yol.name,
        "kontrol": "Çocuk Verisi Koruma",
        "toplam_bulgu": len(bulgular),
        "bulgular": [_bulgu_to_dict(b) for b in bulgular],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def guvenlik_kontrol(proje_yolu: str) -> str:
    """Projeyi güvenlik açıklarına karşı tarar (hardcoded secret, SQLi, XSS, CORS, .env)."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    try:
        bulgular = await GuvenlikTarayici(proje_yolu).tara()
    except Exception as e:
        return json.dumps({"hata": f"Tarama hatası: {e}"}, ensure_ascii=False)

    return json.dumps({
        "proje": yol.name,
        "kontrol": "Güvenlik",
        "toplam_bulgu": len(bulgular),
        "bulgular": [_bulgu_to_dict(b) for b in bulgular],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def duzeltme_plani(proje_adi: str) -> str:
    """Tespit edilen sorunlar için düzeltme planı oluşturur (JSON — diğer ajanlar okuyabilir).
    proje_adi: Proje klasör adı (örn: Python-KesifPortal)
    """
    proje_yolu = str(PROJELER_KOK / proje_adi)
    if not Path(proje_yolu).exists():
        return json.dumps({"hata": f"Proje bulunamadı: {proje_adi}"}, ensure_ascii=False)

    bulgular = await _tum_tarayicilari_calistir(proje_yolu)

    plan = {
        "proje": proje_adi,
        "tarih": datetime.now().isoformat(),
        "toplam_bulgu": len(bulgular),
        "ozet": _bulgulari_ozetle(bulgular),
        "bulgular": bulgular,
        "oncelik_sirasi": [
            {
                "adim": i + 1,
                "id": b["id"],
                "baslik": b["baslik"],
                "seviye": b["seviye"],
                "dosya": b["dosya"],
                "satir": b["satir"],
                "duzeltme": b["duzeltme"],
            }
            for i, b in enumerate(bulgular) if b["seviye"] in ("kritik", "yuksek")
        ],
    }

    plan_dosya = RAPOR_DIR / f"duzeltme_plani_{proje_adi}_{datetime.now().strftime('%Y%m%d')}.json"
    with open(plan_dosya, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    return json.dumps(plan, ensure_ascii=False, indent=2)


@mcp.tool()
async def mevzuat_tam_metin(kaynak_id: str, madde_no: str = "") -> str:
    """Resmi kaynaktan bir kanunun TAM METNİNİ veya belirli bir MADDESİNİ çeker.

    kaynak_id: 'kvkk', 'eticaret_tr', 'tuketici', 'fsek', 'vuk', 'cocuk_koruma', 'gdpr'
    madde_no: Madde numarası (örn '5', '10') — boş bırakılırsa tüm kanun metni döner

    Önce mevzuat-mcp (varsa) denenir, yoksa doğrudan scraper (mevzuat.gov.tr / EUR-Lex) kullanılır.
    Sonuçlar 7 gün önbellekte saklanır.
    """
    # Önce mevzuat-mcp köprüsünü dene — kurulu ise çok daha hızlı ve kararlı
    if _mcp_koprusu.mevcut_mu() and madde_no:
        cevap = await _mcp_koprusu.madde_getir(kaynak_id, madde_no)
        if cevap.basarili and cevap.icerik:
            return json.dumps({
                "kaynak_id": kaynak_id,
                "madde_no": madde_no,
                "kaynak": "mevzuat-mcp",
                "metin": cevap.icerik,
            }, ensure_ascii=False, indent=2)

    # Scraper fallback
    kanun_url = RESMI_KANUN_URLLERI.get(kaynak_id)
    if not kanun_url:
        return json.dumps({
            "hata": f"Tanımsız kaynak: {kaynak_id}",
            "desteklenen": list(RESMI_KANUN_URLLERI.keys()),
        }, ensure_ascii=False)

    try:
        if kaynak_id == "gdpr":
            metin = await _scraper.eurlex_celex_getir("32016R0679")
        elif madde_no:
            metin = await _scraper.madde_getir(kanun_url, madde_no)
        else:
            metin = await _scraper.kanun_metni_getir(kanun_url)
    except Exception as e:
        return json.dumps({"hata": f"Scraper hatası: {e}"}, ensure_ascii=False)

    if not metin:
        return json.dumps({"hata": "Metin çekilemedi"}, ensure_ascii=False)

    return json.dumps({
        "kaynak_id": kaynak_id,
        "madde_no": madde_no or "tamami",
        "kanun_adi": metin.kanun_adi,
        "baslik": metin.baslik,
        "url": metin.url,
        "kaynak": metin.kaynak,
        "onbellekten": metin.onbellekten_geldi,
        "metin_uzunlugu": len(metin.metin),
        "metin": metin.metin[:8000],  # MCP yanıt sınırı için kes — gerekirse dosyaya yaz
        "kesildi_mi": len(metin.metin) > 8000,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def kvkk_karar_ara(sorgu: str, limit: int = 10) -> str:
    """KVKK Kurumu kurul kararlarında arama yapar (kvkk.gov.tr)."""
    try:
        sonuclar = await _scraper.kvkk_karar_ara(sorgu, limit)
    except Exception as e:
        return json.dumps({"hata": f"Arama hatası: {e}"}, ensure_ascii=False)

    return json.dumps({
        "sorgu": sorgu,
        "sonuc_sayisi": len(sonuclar),
        "sonuclar": sonuclar,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def kvkk_karar_metin(url: str) -> str:
    """Verilen kvkk.gov.tr URL'sindeki kurul kararının tam metnini çeker."""
    try:
        metin = await _scraper.kvkk_karar_metin(url)
    except Exception as e:
        return json.dumps({"hata": f"Çekme hatası: {e}"}, ensure_ascii=False)

    if not metin:
        return json.dumps({"hata": "Metin çekilemedi"}, ensure_ascii=False)

    return json.dumps({
        "url": url,
        "baslik": metin.baslik,
        "onbellekten": metin.onbellekten_geldi,
        "metin": metin.metin[:10000],
        "kesildi_mi": len(metin.metin) > 10000,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def kurallari_guncelle(kaynak_id: str = "") -> str:
    """Yerel kural setlerini resmi mevzuat kaynaklarından günceller.

    kaynak_id: Boşsa tüm kural setlerini günceller, aksi halde sadece belirtileni.
    Kanun metnini çeker, hash karşılaştırarak değişiklik tespit eder, meta.guncelleme
    alanını yeniler. Değişiklik varsa uyarı döner.
    """
    try:
        if kaynak_id:
            sonuclar = [await _guncelleyici.kaynak_guncelle(kaynak_id)]
        else:
            sonuclar = await _guncelleyici.tumunu_guncelle()
    except Exception as e:
        return json.dumps({"hata": f"Güncelleme hatası: {e}"}, ensure_ascii=False)

    degisiklik_var = sum(1 for s in sonuclar if s.durum == "basarili" and s.onceki_hash)

    return json.dumps({
        "tarih": datetime.now().isoformat(),
        "taranan_sayisi": len(sonuclar),
        "degisiklik_tespit_edilen": degisiklik_var,
        "sonuclar": [
            {
                "kaynak_id": s.kaynak_id,
                "durum": s.durum,
                "metin_uzunlugu": s.metin_uzunlugu,
                "onceki_hash": s.onceki_hash,
                "yeni_hash": s.yeni_hash,
                "hata": s.hata,
            }
            for s in sonuclar
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def onbellek_durumu(eylem: str = "istatistik") -> str:
    """Mevzuat önbelleğini yönetir.

    eylem: 'istatistik' (varsayılan) | 'temizle_eski' | 'temizle_hepsi'
    """
    if eylem == "istatistik":
        return json.dumps(_onbellek.istatistik(), ensure_ascii=False, indent=2)
    if eylem == "temizle_eski":
        silindi = _onbellek.temizle(eski_mi=True)
        return json.dumps({"silinen_kayit": silindi, "eylem": "temizle_eski"}, ensure_ascii=False)
    if eylem == "temizle_hepsi":
        silindi = _onbellek.temizle(eski_mi=False)
        return json.dumps({"silinen_kayit": silindi, "eylem": "temizle_hepsi"}, ensure_ascii=False)
    return json.dumps({"hata": f"Bilinmeyen eylem: {eylem}"}, ensure_ascii=False)


@mcp.tool()
async def scraper_durumu() -> str:
    """Scraper, önbellek ve mevzuat-mcp köprüsünün sağlık durumunu döndürür."""
    from mevzuat.scraper import PLAYWRIGHT_VAR
    return json.dumps({
        "playwright_yuklu": PLAYWRIGHT_VAR,
        "mevzuat_mcp_koprusu_aktif": _mcp_koprusu.mevcut_mu(),
        "mevzuat_mcp_yolu": str(_mcp_koprusu.mevzuat_mcp_yolu),
        "desteklenen_kaynaklar": list(RESMI_KANUN_URLLERI.keys()),
        "onbellek": _onbellek.istatistik(),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def hizli_tarama(proje_yolu: str) -> str:
    """Projede sadece KRİTİK seviyedeki sorunları hızlıca döndürür (özet tarama)."""
    yol = Path(proje_yolu)
    if not yol.exists():
        return json.dumps({"hata": f"Dizin bulunamadı: {proje_yolu}"}, ensure_ascii=False)

    bulgular = await _tum_tarayicilari_calistir(proje_yolu)
    kritikler = [b for b in bulgular if b["seviye"] == "kritik"]

    return json.dumps({
        "proje": yol.name,
        "tarih": datetime.now().isoformat(),
        "kritik_sayisi": len(kritikler),
        "toplam_bulgu": len(bulgular),
        "kritik_bulgular": kritikler,
    }, ensure_ascii=False, indent=2)


# ─── MCP KAYNAK (resource) TANIMLARI ───────────────────────────────

@mcp.resource("avukat://raporlar")
def raporlar_listesi() -> str:
    """data/raporlar/ dizinindeki tüm raporların listesini döndürür."""
    if not RAPOR_DIR.exists():
        return "Rapor dizini bulunamadı."
    dosyalar = sorted(RAPOR_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return "\n".join(f"- {d.name} ({d.stat().st_size} bayt)" for d in dosyalar[:50])


@mcp.resource("avukat://kurallar/{kaynak}")
def kural_kaynagi(kaynak: str) -> str:
    """Belirli bir kural kaynağının tam JSON içeriğini döndürür."""
    dosya = KURALLAR_DIR / f"{kaynak}.json"
    if not dosya.exists():
        return json.dumps({"hata": f"Kaynak bulunamadı: {kaynak}"}, ensure_ascii=False)
    return dosya.read_text(encoding="utf-8")


# ─── SUNUCUYU BAŞLAT ───────────────────────────────────────────────

def main() -> None:
    """MCP sunucusunu stdio üzerinden başlatır."""
    logger.info("Avukat MCP sunucusu başlatılıyor...")
    logger.info(f"Kural setleri: {_kural_deposu.kaynak_listesi()}")
    logger.info(f"Proje kökü: {PROJELER_KOK}")
    mcp.run()


if __name__ == "__main__":
    main()
