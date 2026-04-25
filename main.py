"""
Avukat MCP — Giriş noktası.
Bu dosya, `python main.py` veya `uv run avukat-mcp` ile çalıştırıldığında
src/server.py içindeki MCP sunucusunu başlatır.
"""

import sys
from pathlib import Path

# src/ dizinini modül arama yoluna ekle
sys.path.insert(0, str(Path(__file__).parent / "src"))

from server import main


if __name__ == "__main__":
    main()
