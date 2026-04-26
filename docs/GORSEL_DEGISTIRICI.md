# WordPress Görsel Otomatik Değiştirici Motor

**Telif riski taşıyan görselleri, site layout'unu bozmadan Unsplash CC0 alternatifleriyle güvenli şekilde değiştiren WordPress otomasyon sistemi.**

## Özellik

- **Site bozulmaz** — yeni görsel aynı boyuta kırpılır (cover stratejisi), aynı alt text korunur, tüm post/page içeriklerindeki URL referansları otomatik güncellenir
- **Elementor uyumu** — `_elementor_data` meta alanındaki URL'ler de güncellenir
- **Tam yedekleme** — orijinaller diske yedeklenir, post snapshot'ları alınır, manifest.json tutulur
- **Rollback** — tek komutla eski hale döndürülebilir
- **Dry-run mode** — hiç dokunmadan planı göster
- **Onay kontrolü** — her görsel için ayrı onay veya toplu onay

## Mimari

```
src/gorsel_degistirici/
├── wp_api.py         # WordPress REST API istemcisi (auth, media, post)
├── unsplash.py       # Unsplash API (arama + indirme)
├── gorsel_islem.py   # Pillow ile boyut eşleştirme + kategori tahmini
├── yedekleme.py      # Disk yedekleme + manifest + rollback
└── degistir.py       # Orkestratör: plan_uret + uygula + geri_al

scripts/
└── gorsel_degistir_cli.py  # CLI giriş noktası
```

## Kurulum

### 1. Bağımlılıklar

```bash
uv add pillow  # zaten reportlab ile geldi
# httpx, beautifulsoup4 zaten var
```

### 2. WordPress Application Password

WP Admin'e gir → sağ üst → Profil → **Application Passwords** → yeni oluştur (ör. `avukat-mcp`). Gelen parolayı not al (boşluklu 4×6 format).

### 3. Unsplash API Key

https://unsplash.com/oauth/applications/new → yeni uygulama oluştur → **Access Key** al. Ücretsiz plan saatte 50 istek, kayıtla 1000 istek.

### 4. Ortam değişkenleri

```bash
# .env veya PowerShell profili
$env:WP_SITE_URL="https://example.com"
$env:WP_USERNAME="admin_kullanici_adi"
$env:WP_APP_PASSWORD="abcd efgh ijkl mnop qrst uvwx"
$env:UNSPLASH_ACCESS_KEY="..."
```

## Kullanım

### 1. Sağlık kontrolü

```bash
python scripts/gorsel_degistir_cli.py --saglik
```

Çıktı:
- WP API bağlantısı, kullanıcı yetkileri (edit_posts, upload_files)
- Unsplash API erişimi

### 2. Dry-run (önerilen başlangıç)

```bash
python scripts/gorsel_degistir_cli.py --dry-run
```

Çıktı:
- Her riskli görsel için: WP media ID, boyut, Unsplash aday ID/URL/fotoğrafçı, etkilenen post sayısı
- Plan JSON: `data/raporlar/degistirme_plani_*.json`

**Hiçbir değişiklik yapılmaz** — sadece keşif.

### 3. Apply — her görsel için onay

```bash
python scripts/gorsel_degistir_cli.py --apply --onay her_biri --limit 3
```

Her görsel için `[e/H]` sorar. Önce 3 görselle test et.

### 4. Apply — tüm görseller, tam otomatik

```bash
python scripts/gorsel_degistir_cli.py --apply --onay hepsi
```

### 5. Rollback

```bash
# En son oturumu geri al
python scripts/gorsel_degistir_cli.py --rollback son

# Belirli bir oturumu
python scripts/gorsel_degistir_cli.py --rollback ~/projects/avukat-mcp/data/yedekler/20260423_111500
```

## İş Akışı (Değiştirme)

```
1. Medya bul (WP REST API)
       ↓
2. Orijinali indir → yedekle (data/yedekler/OTURUM/orijinal_dosyalar/)
       ↓
3. Unsplash'ta kategori tahmini (team, coaching, business vs.)
       ↓
4. Aday görsel bul (aynı oran/orientasyon)
       ↓
5. Pillow ile cover stratejiyle kırp → aynı boyuta getir
       ↓
6. WP'ye yeni media olarak yükle
       ↓
7. Tüm postlarda URL'yi değiştir (post_content + _elementor_data)
       ↓
8. Eski medyayı TRASH'e at (force=false → geri alınabilir)
       ↓
9. Manifest.json'a kaydet (rollback için)
```

## Güvenlik Notu

- **Application Password** WP admin parolası değildir; yetki kısıtlıdır ve her uygulama için ayrı oluşturulur
- **Rollback güvenliği**: Eski medyalar sadece trash'e atılır (force=false), kalıcı silinmez. WordPress 30 gün sonra otomatik temizleyebilir — oturum bitince "Trash > Empty" kontrol et
- **Rate limit**: Unsplash saatte 50/1000 istek; script her istek arası 2 sn bekler
- **Test**: Her zaman önce **staging sitede** dene veya **--limit 1** ile başla

## Sınırlar

- Eski URL'nin kullanıldığı **third-party önbellek**ler (Cloudflare, CDN) temizlenmez → CDN panelinden purge yapılmalı
- **Gutenberg block reused blocks** referansları manuel kontrol gerektirir
- Custom plugin'lerin saklayacağı görsel URL'leri (ör. theme options)aranmaz — gerekirse DB'de `UPDATE wp_options SET option_value = REPLACE(...)` ile manuel

## Hata Durumları

| Hata | Çözüm |
|------|-------|
| `401 Unauthorized` | WP_APP_PASSWORD yanlış veya kullanıcının yetkisi yok |
| `WP medya kaydı bulunamadı` | Dosya adı WP'de farklı — `scripts/ters_arama.py` verilerini güncelle |
| `Unsplash'ta aday bulunamadı` | Kategori tahmini çok dar — `gorsel_islem.py` > `KATEGORI_SOZLUGU` güncelle |
| `Upload HTTP 413` | WP `post_max_size` küçük — `php.ini` artır veya dosya sıkıştır |

## Hukuki Dayanak (FSEK)

- **md.14** — Eser sahibinin manevi hakları (kaynak belirtme)
- **md.52** — Mali hak devri yazılı şekil şartı
- Unsplash CC0 lisansı FSEK md.52 uyarınca **evrensel kamu alanı feragatı** sayılır, ayrıca yazılı sözleşme aranmaz (Unsplash License Terms bağlayıcı)

## Örnek Çıktı (dry-run)

```
#   Risk     Media ID   Boyut      Dosya                                    Unsplash Adayı                   Postlar
────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
1   KRİTİK   127        1000x1300  Kocluk-seanlari.jpg                      abc123xyz                        3
2   YÜKSEK   129        960x640    4.webp                                   def456uvw                        5
3   YÜKSEK   131        1000x1300  3.webp                                   ghi789rst                        2
```
