# Atıflar & Yararlanılan Kaynaklar

Bu proje, aşağıdaki açık kaynak yazılımları, standartları ve referans dokümanları kullanmıştır. Her birine ayrı ayrı teşekkür ediyoruz.

## Çekirdek Bağımlılıklar

| Paket | Lisans | Kullanım |
|---|---|---|
| [Model Context Protocol SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | MCP sunucu altyapısı |
| [httpx](https://www.python-httpx.org/) | BSD-3-Clause | Asenkron HTTP istemcisi |
| [aiofiles](https://github.com/Tinche/aiofiles) | Apache 2.0 | Asenkron dosya I/O |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | MIT | HTML/XML ayrıştırma |
| [Playwright](https://playwright.dev/python/) | Apache 2.0 | Tarayıcı otomasyonu (opsiyonel scraper) |
| [reportlab](https://www.reportlab.com/opensource/) | BSD | PDF rapor üretimi |
| [hatchling](https://hatch.pypa.io/) | MIT | Build backend |

## Mevzuat ve Standart Kaynakları

Hukuki kural setleri aşağıdaki **resmi metinlere** dayanır. Bu dokümanların kendileri kamu malıdır (kanun metinleri telif kapsamı dışındadır):

- **KVKK** — 6698 sayılı Kişisel Verilerin Korunması Kanunu (T.C. Resmi Gazete)
- **KVKK Aydınlatma Yükümlülüğü Tebliği** — KVKK Kurumu yayınları
- **GDPR** — Regulation (EU) 2016/679, EUR-Lex
- **6502 sayılı Tüketicinin Korunması Hakkında Kanun** — Mesafeli satış için
- **6563 sayılı Elektronik Ticaretin Düzenlenmesi Hakkında Kanun (İYS dahil)**
- **5846 sayılı Fikir ve Sanat Eserleri Kanunu (FSEK)**
- **PCI-DSS v4.0** — PCI Security Standards Council
- **COPPA** — Children's Online Privacy Protection Act, US Code 15 USC §6501
- **CAN-SPAM Act** — US Public Law 108-187
- **OWASP Top 10** — © OWASP Foundation, CC BY-SA 4.0

## İlham Alınan Projeler

Bu projenin tasarımı kısmen şu çalışmalardan ilham almıştır:

- [**detect-secrets**](https://github.com/Yelp/detect-secrets) (Apache 2.0) — Yapılandırılabilir secret detection yapısı (kendi pattern setimiz sıfırdan yazıldı)
- [**Bandit**](https://github.com/PyCQA/bandit) (Apache 2.0) — Python güvenlik tarayıcı paterni
- [**git-secrets**](https://github.com/awslabs/git-secrets) (Apache 2.0) — Pre-commit secret tarama yaklaşımı

> **Not:** Yukarıdaki projelerden hiçbirinin **kodu, regex'i veya rule set'i kopyalanmamıştır.** Tüm regex'ler, kural setleri ve tarayıcı sınıfları **sıfırdan, Türkiye mevzuatı odaklı** olarak yazılmıştır. Yalnızca **mimari/yaklaşım ilhamı** alınmıştır.
>
> AGPL ve copyleft lisanslı projelerden (TruffleHog vb.) **bilinçli olarak uzak durulmuştur** — bu projenin permissive MIT yayını için lisans bulaşması riski yaratabilirdi.

## Veri Kaynakları

`mevzuat_ara` aracı, kullanıcı talep ederse aşağıdaki **resmi açık veri kaynaklarından** sorgulama yapabilir:

- [mevzuat.gov.tr](https://mevzuat.gov.tr) — T.C. Cumhurbaşkanlığı Mevzuat Bilgi Sistemi
- [eur-lex.europa.eu](https://eur-lex.europa.eu) — Avrupa Birliği mevzuatı

Bu sitelerin içeriği kamu malıdır (kanun metinleri telif kapsamı dışındadır), ancak **site sunum biçimi** ve **arama altyapısı** ilgili kurumlara aittir.

> **Erişim Kuralları:** `mevzuat_ara` aracı, hedef sitelerin `robots.txt` kurallarına ve yayınlanmış API kotalarına **uymakla yükümlüdür**. Saniyede en fazla 1 istek + User-Agent identifikasyonu zorunludur. Bu MCP, **kullanıcının kendi sorgusu** üzerine tek seferlik çağrı yapar; **toplu kazıma yapmaz**, içeriği yeniden yayınlamaz.

## Lisans Uyumluluğu

Tüm bağımlılıklar MIT, BSD, Apache 2.0 gibi **permissive** lisanslara sahiptir. Bu projeyi MIT lisansıyla yeniden dağıtmak için herhangi bir engel bulunmamaktadır.

Eğer atıf eksik bıraktığımız bir kaynak varsa lütfen [issue açın](https://github.com/kpmustafayilmaz/avukat-mcp/issues).
