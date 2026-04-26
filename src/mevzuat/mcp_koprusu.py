# Bu modül, KEŞİF ekosistemindeki ayrı bir MCP sunucusu olan 'mevzuat-mcp'
# (Türk mevzuat arama) ile köprü kurar. mevzuat-mcp sunucusu kuruluysa,
# avukat-mcp onun tool'larını subprocess üzerinden çağırabilir.
# Kurulu değilse köprü sessizce devre dışı kalır ve yerel scraper kullanılır.

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("avukat-mcp.kopru")

# KEŞİF registry'sinde mevzuat-mcp için beklenen konum
VARSAYILAN_MEVZUAT_MCP_YOLU = Path.home() / "projects" / "mevzuat-mcp" / "server.py"


@dataclass
class KopruCevabi:
    """mevzuat-mcp'den gelen cevabı temsil eder."""
    basarili: bool
    icerik: str = ""
    hata: str = ""


class MevzuatMCPKoprusu:
    """
    mevzuat-mcp MCP sunucusuna stdio üzerinden JSON-RPC çağrısı yapar.
    Kurulu değilse `mevcut_mu()` False döner ve çağrılar sessizce başarısız olur.
    """

    def __init__(self, mevzuat_mcp_yolu: Optional[Path] = None):
        self.mevzuat_mcp_yolu = Path(
            os.environ.get("MEVZUAT_MCP_PATH") or
            (mevzuat_mcp_yolu or VARSAYILAN_MEVZUAT_MCP_YOLU)
        )

    def mevcut_mu(self) -> bool:
        """mevzuat-mcp sunucusu kurulu mu kontrol eder."""
        return self.mevzuat_mcp_yolu.exists()

    async def tool_cagir(self, tool_adi: str, argumanlar: dict, zaman_asimi: float = 30.0) -> KopruCevabi:
        """
        mevzuat-mcp'deki bir tool'u çağırır. MCP protokolü JSON-RPC üzerinden
        çalıştığı için sunucuyu subprocess olarak başlatıp stdin/stdout ile
        haberleşiyoruz.
        """
        if not self.mevcut_mu():
            return KopruCevabi(basarili=False, hata="mevzuat-mcp kurulu değil")

        # MCP JSON-RPC istek mesajları — initialize + tools/call
        initialize_mesaji = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "avukat-mcp", "version": "1.0.0"},
            },
        }
        initialized_bildirim = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        tool_cagri = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_adi, "arguments": argumanlar},
        }

        mesajlar = [initialize_mesaji, initialized_bildirim, tool_cagri]
        stdin_icerik = "\n".join(json.dumps(m, ensure_ascii=False) for m in mesajlar) + "\n"

        try:
            surec = await asyncio.create_subprocess_exec(
                "python", str(self.mevzuat_mcp_yolu),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    surec.communicate(stdin_icerik.encode("utf-8")),
                    timeout=zaman_asimi,
                )
            except asyncio.TimeoutError:
                surec.kill()
                await surec.wait()
                return KopruCevabi(basarili=False, hata="Zaman aşımı")

            cikti = stdout.decode("utf-8", errors="replace")
            # JSON-RPC cevaplarını satır satır ayrıştır — ID=2 olan tool sonucu
            for satir in cikti.splitlines():
                satir = satir.strip()
                if not satir or not satir.startswith("{"):
                    continue
                try:
                    cevap = json.loads(satir)
                except json.JSONDecodeError:
                    continue
                if cevap.get("id") == 2:
                    if "result" in cevap:
                        icerik_listesi = cevap["result"].get("content", [])
                        metin_parcalari = [
                            item.get("text", "") for item in icerik_listesi
                            if item.get("type") == "text"
                        ]
                        return KopruCevabi(
                            basarili=True,
                            icerik="\n".join(metin_parcalari),
                        )
                    if "error" in cevap:
                        return KopruCevabi(
                            basarili=False,
                            hata=str(cevap["error"]),
                        )

            return KopruCevabi(
                basarili=False,
                hata=f"Cevap ayrıştırılamadı. stderr: {stderr.decode('utf-8', errors='replace')[:400]}",
            )
        except Exception as e:
            return KopruCevabi(basarili=False, hata=f"Çağrı hatası: {e}")

    async def mevzuat_ara(self, sorgu: str) -> KopruCevabi:
        """mevzuat-mcp'nin arama tool'unu proxy eder."""
        # mevzuat-mcp'de yaygın tool adları — değişirse ENV ile override edilebilir
        tool_adi = os.environ.get("MEVZUAT_MCP_SEARCH_TOOL", "search_mevzuat")
        return await self.tool_cagir(tool_adi, {"query": sorgu})

    async def madde_getir(self, kanun_no: str, madde_no: str) -> KopruCevabi:
        """mevzuat-mcp'nin madde getirme tool'unu proxy eder."""
        tool_adi = os.environ.get("MEVZUAT_MCP_ARTICLE_TOOL", "get_article")
        return await self.tool_cagir(tool_adi, {
            "law_no": kanun_no,
            "article_no": madde_no,
        })
