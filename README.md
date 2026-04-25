# Avukat MCP

> **Türkiye ve uluslararası hukuki uyumluluk tarayıcısı — Model Context Protocol (MCP) sunucusu.**
> *Turkey-focused legal compliance scanner for software projects, exposed via MCP.*

`D:\0` (veya istediğiniz herhangi bir kök dizin) altındaki tüm yazılım projelerini **KVKK, GDPR, E-Ticaret Kanunu, PCI-DSS, COPPA, FSEK, CAN-SPAM, İYS** mevzuatı çerçevesinde tarar; hukuki riskleri tespit eder, somut düzeltme önerileri sunar.

[![Made with MCP](https://img.shields.io/badge/MCP-Server-blueviolet)](https://modelcontextprotocol.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

---

## 🇹🇷 Neden Avukat MCP?

Türkiye'de bir yazılım projesi geliştirirken **KVKK aydınlatma metni**, **çerez izni**, **İYS kaydı**, **mesafeli satış sözleşmesi** gibi onlarca yükümlülük var. Çoğu geliştirici bunları kod tarafında nasıl uyguladığını **bilemiyor** ya da **unutuyor**. Avukat MCP, bu boşluğu doldurur:

- Form alanlarınızı tarar → KVKK aydınlatma var mı?
- Cookie / localStorage / IP loglarını bulur → consent banner gerekli mi?
- `.env` ve hardcoded secret'ları yakalar → güvenlik
- LICENSE ve 3. parti telifleri inceler → FSEK uyumu
- E-ticaret entegrasyonlarınızı tarar → mesafeli satış gerekli mi?

---

## ✨ Özellikler

### 7 Uzmanlaşmış Tarayıcı

| Tarayıcı                | Denetlediği Alan                                            |
| ----------------------- | ----------------------------------------------------------- |
| **VeriToplamaTarayici** | Form alanları, cookie, analytics, localStorage, IP loglama  |
| **GizlilikTarayici**    | Gizlilik politikası, KVKK aydınlatma metni, cookie consent  |
| **LisansTarayici**      | LICENSE dosyası, GPL bulaşıcılığı, üçüncü parti lisanslar   |
| **EticaretTarayici**    | Mesafeli satış, 14 gün cayma, 3D Secure, SSL, fatura        |
| **GuvenlikTarayici**    | Hardcoded secrets, SQL injection, XSS, CORS, .env güvenliği |
| **IletisimTarayici**    | İYS kaydı, opt-in checkbox, unsubscribe, gönderen kimliği   |
| **CocukTarayici**       | Yaş doğrulama, ebeveyn onayı, çocuk reklam kısıtlaması      |

### 13 MCP Tool

`proje_tara`, `tum_projeleri_tara`, `hizli_tarama`, `rapor_olustur`, `duzeltme_plani`, `mevzuat_ara`, `kural_setleri_listele`, `kvkk_kontrol`, `gdpr_kontrol`, `eticaret_kontrol`, `telif_kontrol`, `iletisim_kontrol`, `cocuk_kontrol`, `guvenlik_kontrol`

---

## 🚀 Kurulum

```bash
git clone https://github.com/kpmustafayilmaz/avukat-mcp
cd avukat-mcp
uv sync
# veya:
pip install -e .
```

### Claude Desktop / Code yapılandırması

`mcp.json` veya `claude_desktop_config.json`'a ekleyin:

```json
{
  "mcpServers": {
    "avukat": {
      "command": "uv",
      "args": ["--directory", "/path/to/avukat-mcp", "run", "avukat-mcp"]
    }
  }
}
```

---

## 📖 Kullanım Örnekleri

```
> Şu projeyi KVKK açısından tarat: D:\projects\my-shop
```

```
> D:\workspace altındaki tüm projelerin kritik güvenlik açıklarını listele
```

```
> "kişisel veri" terimini içeren mevzuat maddelerini ara
```

---

## 🌍 English Summary

A Turkey-focused legal compliance MCP server. Scans software projects for KVKK (Turkey's GDPR), GDPR, e-commerce law, PCI-DSS, COPPA, FSEK (copyright), CAN-SPAM and İYS (Turkey's commercial communications) violations. Provides 13 MCP tools to be used by Claude Desktop, Cursor, or any MCP-compatible AI client.

While the rule packs are Turkey-first, GDPR/PCI-DSS/COPPA scanners work for any project regardless of jurisdiction.

---

## 📚 Atıflar & Yararlanılan Kaynaklar

Bu projenin geliştirilmesinde yararlanılan kaynaklar [ATTRIBUTIONS.md](ATTRIBUTIONS.md) dosyasında listelenmiştir.

---

## 🤝 Katkı

Pull request'ler ve issue'lar memnuniyetle karşılanır. Özellikle:
- Yeni mevzuat (KVKK güncellemeleri, AB AI Act, vb.)
- Yeni dile özgü tarayıcılar (Go, Rust, Swift için pattern setleri)
- Türkçe + İngilizce dokümantasyon iyileştirmeleri

---

## ⚠️ Yasal Uyarı / Legal Notice

**Türkçe:**
Bu yazılım **hukuki tavsiye yerine geçmez**. Üretilen bulgular yalnızca **ön denetim** niteliğindedir; KVKK Kurumu, GDPR otoriteleri veya başka herhangi bir düzenleyici makam tarafından bağlayıcı kabul edilmez. Bu yazılımın çıktısına dayanarak alınan kararlar, ödenen cezalar, kaybedilen müşteri/sözleşmeler veya itibar zararları için **yazar hiçbir sorumluluk kabul etmez**. Üretim ortamına geçmeden önce mutlaka **lisanslı bir avukatla** görüşün.

**English:**
This software is **NOT legal advice**. Findings are **preliminary indicators only** and are not binding for KVKK Authority, GDPR Supervisory Authorities, or any other regulator. The author **disclaims all liability** for any regulatory penalty, fine, agency decision, lost contract, business loss, or reputational damage arising from reliance on this software's output. Always consult a **licensed attorney** in your jurisdiction before acting on the findings.

## 📄 Lisans / License

MIT — bkz. [LICENSE](LICENSE).
