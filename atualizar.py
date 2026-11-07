#!/usr/bin/env python3
"""Monta filmes.json a partir de fontes públicas.

Fontes:
  archive  - Internet Archive (advancedsearch, sem chave)
  commons  - Wikimedia Commons (vídeos livres, sem chave)
  youtube  - playlists do YouTube (opcional; precisa YOUTUBE_API_KEY)

Só usa a biblioteca padrão do Python. Cada linha falha de forma isolada:
se uma fonte cair, o resto do catálogo é gerado normalmente.
"""
import json
import os
import re
import sys
import time
import html
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CONFIG = RAIZ / "linhas.json"
SAIDA = RAIZ / "filmes.json"
UA = "StreamingLivreBot/1.0 (catalogo pessoal; GitHub Actions)"


# ---------- utilidades ----------
def http_json(url, tentativas=3, espera=2.0):
    ultimo = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            ultimo = e
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"falha ao buscar {url[:90]}...: {ultimo}")


def primeiro(v):
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def limpar(texto, max_chars=320):
    t = html.unescape(re.sub(r"<[^>]+>", " ", str(primeiro(texto))))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= max_chars else t[: max_chars - 1].rstrip() + "…"


def ano_de(v):
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", str(primeiro(v)))
    return int(m.group(1)) if m else None


# ---------- Internet Archive ----------
def buscar_archive(linha, limite):
    q = f"({linha['consulta']}) AND mediatype:movies AND -access-restricted-item:true"
    p = [
        ("q", q),
        ("rows", str(limite * 2)),  # busca a mais para compensar descartes
        ("page", "1"),
        ("output", "json"),
        ("sort[]", linha.get("ordem", "downloads desc")),
    ]
    for campo in ("identifier", "title", "year", "description", "downloads", "runtime"):
        p.append(("fl[]", campo))
    dados = http_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(p))
    minimo = int(linha.get("min_downloads", 0))
    itens, vistos = [], set()
    for d in dados.get("response", {}).get("docs", []):
        ident = d.get("identifier")
        titulo = limpar(d.get("title"), 140)
        if not ident or not titulo or ident in vistos:
            continue
        if int(d.get("downloads") or 0) < minimo:
            continue
        vistos.add(ident)
        itens.append({
            "fonte": "archive",
            "id": ident,
            "titulo": titulo,
            "ano": ano_de(d.get("year")),
            "descricao": limpar(d.get("description")),
            "duracao": limpar(d.get("runtime"), 20) or None,
            "poster": f"https://archive.org/services/img/{urllib.parse.quote(ident)}",
        })
        if len(itens) >= limite:
            break
    return itens


# ---------- Wikimedia Commons ----------
VIDEO_OK = {"video/webm", "video/ogg", "video/mp4"}


def buscar_commons(linha, limite):
    p = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:video {linha['termo']}",
        "gsrnamespace": "6",
        "gsrlimit": str(min(limite * 2, 50)),
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "500",
    }
    dados = http_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p))
    paginas = sorted(dados.get("query", {}).get("pages", {}).values(), key=lambda x: x.get("index", 0))
    itens = []
    for pg in paginas:
        info = (pg.get("imageinfo") or [{}])[0]
        if info.get("mime") not in VIDEO_OK or not info.get("url"):
            continue
        meta = info.get("extmetadata", {})
        titulo = re.sub(r"\.\w+$", "", pg.get("title", "").replace("File:", "")).replace("_", " ")
        itens.append({
            "fonte": "commons",
            "id": str(pg.get("pageid")),
            "titulo": limpar(titulo, 140),
            "ano": ano_de(meta.get("DateTimeOriginal", {}).get("value", "")),
            "descricao": limpar(meta.get("ImageDescription", {}).get("value", "")),
            "poster": info.get("thumburl") or "",
            "url": info["url"],
            "tipo": info["mime"],
            "pagina": info.get("descriptionurl"),
        })
        if len(itens) >= limite:
            break
    return itens


# ---------- YouTube (opcional) ----------
def buscar_youtube(linha, limite):
    chave = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("YOUTUBE_API_KEY não definida (linha ignorada)")
    base = "https://www.googleapis.com/youtube/v3/"
    pl = http_json(base + "playlistItems?" + urllib.parse.urlencode({
        "part": "snippet", "maxResults": "50", "playlistId": linha["playlist"], "key": chave}))
    ids = [i["snippet"]["resourceId"]["videoId"] for i in pl.get("items", [])
           if i["snippet"]["title"] not in ("Private video", "Deleted video")]
    if not ids:
        return []
    vd = http_json(base + "videos?" + urllib.parse.urlencode({
        "part": "status,snippet", "id": ",".join(ids[:50]), "key": chave}))
    itens = []
    for v in vd.get("items", []):
        st = v.get("status", {})
        if not st.get("embeddable") or st.get("privacyStatus") != "public":
            continue
        sn = v["snippet"]
        thumbs = sn.get("thumbnails", {})
        poster = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        itens.append({
            "fonte": "youtube",
            "id": v["id"],
            "titulo": limpar(sn.get("title"), 140),
            "ano": ano_de(sn.get("publishedAt")),
            "descricao": limpar(sn.get("description")),
            "poster": poster,
        })
        if len(itens) >= limite:
            break
    return itens


FONTES = {"archive": buscar_archive, "commons": buscar_commons, "youtube": buscar_youtube}


# ---------- principal ----------
def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    limite_padrao = int(cfg.get("limite_padrao", 24))
    saida = []

    for linha in cfg.get("linhas", []):
        if linha.get("ativo") is False:
            print(f"-- {linha['id']}: desativada")
            continue
        func = FONTES.get(linha.get("fonte"))
        if not func:
            print(f"!! {linha['id']}: fonte desconhecida '{linha.get('fonte')}'")
            continue
        try:
            itens = func(linha, int(linha.get("limite", limite_padrao)))
        except Exception as e:  # uma linha ruim não derruba o resto
            print(f"!! {linha['id']}: {e}")
            continue
        print(f"OK {linha['id']}: {len(itens)} itens")
        if itens:
            saida.append({"id": linha["id"], "titulo": linha["titulo"], "itens": itens})

    if not saida:
        print("Nenhuma linha gerou itens; mantendo o catálogo anterior.")
        return 1

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({
        "atualizadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "linhas": saida,
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Catálogo salvo: {sum(len(l['itens']) for l in saida)} itens em {len(saida)} linhas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
