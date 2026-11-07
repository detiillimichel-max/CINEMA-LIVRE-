#!/usr/bin/env python3
"""Varre o Internet Archive por setores e grava arquivos em data/.

Usa a API de varredura (services/search/v1/scrape), que pagina por cursor e
aguenta dezenas de milhares de resultados. Saída:

  data/indice.json                 -> setores, totais e destaques (leve)
  data/setores/<setor>-<n>.json    -> itens do setor em partes (compactos)

Variáveis de ambiente opcionais:
  MAX_ITENS_SETOR  sobrescreve o limite de itens por setor
  SETORES          lista de ids separados por vírgula (roda só esses)

Só biblioteca padrão. Cada setor falha de forma isolada.
"""
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atualizar import http_json, limpar, ano_de, primeiro  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "setores.json"
DADOS = RAIZ / "data"
PASTA = DADOS / "setores"
INDICE = DADOS / "indice.json"
URL = "https://archive.org/services/search/v1/scrape?"
CAMPOS = "identifier,title,year,description,downloads,runtime"
PAUSA = 1.0          # segundos entre páginas (gentil com o servidor)
POR_PAGINA = 1000    # a API aceita de 100 a 10000


def varrer(q, max_itens):
    """Percorre todas as páginas por cursor até max_itens ou o fim."""
    itens, cursor, total, ordenar = [], None, None, "downloads desc"
    while len(itens) < max_itens:
        p = {"q": q, "fields": CAMPOS, "count": str(POR_PAGINA)}
        if ordenar:
            p["sorts"] = ordenar
        if cursor:
            p["cursor"] = cursor
        try:
            dados = http_json(URL + urllib.parse.urlencode(p))
        except RuntimeError:
            if ordenar and not itens:      # talvez 'sorts' não seja aceito: tenta sem
                ordenar = None
                continue
            raise
        total = dados.get("total", total)
        itens.extend(dados.get("items", []))
        cursor = dados.get("cursor")
        if not cursor:
            break
        time.sleep(PAUSA)
    return itens[:max_itens], total


def montar_consulta(setor, cfg):
    q = f"({setor['consulta']}) AND mediatype:movies AND -access-restricted-item:true"
    if cfg.get("excluir"):
        q += f" AND NOT ({cfg['excluir']})"
    return q


def compactar(brutos, minimo, n_destaques):
    vistos, saida = set(), []
    for d in brutos:
        ident = d.get("identifier")
        titulo = limpar(d.get("title"), 110)
        if not ident or not titulo or ident in vistos:
            continue
        baixados = int(d.get("downloads") or 0)
        if baixados < minimo:
            continue
        vistos.add(ident)
        item = {"i": ident, "t": titulo, "d": baixados}
        ano = ano_de(d.get("year"))
        if ano:
            item["a"] = ano
        dur = limpar(d.get("runtime"), 20)
        if dur:
            item["r"] = dur
        item["_s"] = limpar(d.get("description"), 260)   # temporário
        saida.append(item)
    saida.sort(key=lambda x: -x["d"])
    for pos, it in enumerate(saida):
        desc = it.pop("_s")
        if pos < n_destaques and desc:
            it["s"] = desc               # descrição só para os destaques
    return saida


def gravar_json(caminho, obj):
    caminho.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    limite_env = os.environ.get("MAX_ITENS_SETOR", "").strip()
    filtro = {s.strip() for s in os.environ.get("SETORES", "").split(",") if s.strip()}
    parte_tam = int(cfg.get("tamanho_parte", 500))
    n_dest = int(cfg.get("destaques_por_setor", 30))

    try:
        antigo = json.loads(INDICE.read_text(encoding="utf-8"))
    except Exception:
        antigo = {"setores": []}
    por_id = {s["id"]: s for s in antigo.get("setores", [])}
    ordem = [s["id"] for s in cfg["setores"]]

    PASTA.mkdir(parents=True, exist_ok=True)
    ok = 0
    for setor in cfg["setores"]:
        sid = setor["id"]
        if filtro and sid not in filtro:
            continue
        limite = int(limite_env or setor.get("max_itens") or cfg.get("max_itens_padrao", 1500))
        try:
            brutos, total = varrer(montar_consulta(setor, cfg), limite)
        except Exception as e:
            print(f"!! {sid}: {e}")
            continue
        itens = compactar(brutos, int(cfg.get("min_downloads", 0)), n_dest)
        if not itens:
            print(f"!! {sid}: nenhum item (consulta sem resultados)")
            continue

        for velho in PASTA.glob(f"{sid}-*.json"):
            velho.unlink()
        partes = [itens[i:i + parte_tam] for i in range(0, len(itens), parte_tam)]
        for n, parte in enumerate(partes):
            gravar_json(PASTA / f"{sid}-{n}.json", parte)

        por_id[sid] = {
            "id": sid,
            "titulo": setor["titulo"],
            "total": int(total or len(itens)),
            "salvos": len(itens),
            "partes": len(partes),
            "destaque": itens[:n_dest],
        }
        ok += 1
        print(f"OK {sid}: {len(itens)} itens salvos ({total} no Archive), {len(partes)} partes")

    if not ok:
        print("Nenhum setor atualizado; mantendo o que já existe.")
        return 1

    setores = [por_id[i] for i in ordem if i in por_id]
    gravar_json(INDICE, {
        "atualizadoEm": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "setores": setores,
    })
    print(f"Concluído: {sum(s['salvos'] for s in setores)} itens em {len(setores)} setores.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
