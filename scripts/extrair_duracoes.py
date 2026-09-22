# -*- coding: utf-8 -*-
"""Extrai título + duração HH:MM:SS das aulas no HTML do Gran (via transcript)."""
from __future__ import annotations

import json
import re
import html as html_mod
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT = Path(
    r"C:\Users\celso53793477\.cursor\projects\c-Users-celso53793477-Desktop-projetos-atuais-concurso"
    r"\agent-transcripts\4073bd1c-06a5-4ac8-9425-6657354fd5ec"
    r"\4073bd1c-06a5-4ac8-9425-6657354fd5ec.jsonl"
)
OUT_JSON = ROOT / "data" / "topicos_gran.json"
DURACOES_JSON = ROOT / "data" / "duracoes_aulas.json"

DISCIPLINAS = [
    "Língua Portuguesa",
    "Língua Inglesa",
    "Matemática",
    "Atualidades do Mercado Financeiro",
    "Matemática Financeira",
    "Conhecimentos Bancários",
    "Conhecimentos de Informática",
    "Vendas e Negociação",
    "Redação Discursiva",
]


def clean(s: str) -> str:
    s = html_mod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_hhmmss(texto: str) -> int | None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", texto.strip())
    if not m:
        return None
    h, mi, s = map(int, m.groups())
    return h * 3600 + mi * 60 + s


def load_html_from_transcript() -> str:
    parts = []
    with TRANSCRIPT.open(encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("role") != "user":
                continue
            for part in obj.get("message", {}).get("content", []):
                if part.get("type") != "text":
                    continue
                text = part.get("text", "")
                if "dark:text-primary-dark-40" in text or "titulo-curso" in text:
                    m = re.search(r"<div[\s\S]+", text)
                    parts.append(m.group(0) if m else text)
    return "\n".join(parts)


def extract_lesson_durations(html: str) -> list[dict]:
    """
    Para cada link de aula (aria-label com Professor), pega o primeiro
    span de duração HH:MM:SS à frente no mesmo bloco.
    """
    # Bloco: aria-label="N - Título - Professor ..." ... >HH:MM:SS</span>
    pattern = re.compile(
        r'aria-label="(\d{1,3}\s*[-–—]\s*[^"]+?)"'
        r'[\s\S]{0,2500}?'
        r'<span class="self-center text-sm text-neutrals-mid-800 dark:text-primary-dark-40">'
        r"(\d{1,2}:\d{2}:\d{2})</span>",
        re.I,
    )

    # Marcadores de disciplina (texto curto)
    markers = []
    for d in DISCIPLINAS:
        for m in re.finditer(re.escape(d), html):
            window = html[max(0, m.start() - 80) : m.end() + 40]
            if re.search(rf">\s*{re.escape(d)}\s*<", window):
                markers.append((m.start(), d))
    markers.sort()
    compact = []
    for pos, d in markers:
        if compact and compact[-1][1] == d and pos - compact[-1][0] < 500:
            continue
        compact.append((pos, d))

    def disc_at(pos: int) -> str | None:
        cur = None
        for mpos, d in compact:
            if mpos > pos:
                break
            cur = d
        return cur

    seen = set()
    aulas = []
    for m in pattern.finditer(html):
        label = clean(m.group(1))
        if "Marcar aula" in label:
            continue
        titulo = re.sub(
            r"\s*[-–—]\s*(?:Professor(?:a)?|Prof\.)\s+.+$",
            "",
            label,
            flags=re.I,
        ).strip()
        if "Lei nº 13.146/15 - Livro" in titulo:
            continue
        segundos = parse_hhmmss(m.group(2))
        if segundos is None:
            continue

        matches = [d for d in DISCIPLINAS if d.lower() in titulo.lower()]
        if matches:
            matches.sort(key=len, reverse=True)
            disciplina = matches[0]
        else:
            disciplina = disc_at(m.start())

        key = (disciplina or "", titulo.lower())
        if key in seen:
            continue
        seen.add(key)

        aulas.append(
            {
                "disciplina": disciplina,
                "titulo": titulo,
                "duracao": m.group(2),
                "segundos": segundos,
                "minutos": max(1, round(segundos / 60)),
            }
        )
    return aulas


def merge_into_seed(aulas: list[dict]) -> dict:
    seed = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    # index por (disciplina, titulo)
    index = {}
    for a in aulas:
        if not a["disciplina"]:
            continue
        index[(a["disciplina"], a["titulo"].lower())] = a

    matched = 0
    missing = []
    for disc in seed:
        for t in disc["topicos"]:
            key = (disc["nome"], t["titulo"].lower())
            a = index.get(key)
            if a:
                t["duracao"] = a["duracao"]
                t["segundos"] = a["segundos"]
                t["minutos_video"] = a["minutos"]
                # estimativa = vídeo + buffer questões (15 min)
                t["minutos_estimados"] = a["minutos"] + 15
                matched += 1
            else:
                missing.append(f"{disc['nome']}: {t['titulo']}")

    OUT_JSON.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"matched": matched, "missing": missing, "aulas_extraidas": len(aulas)}


def main():
    html = load_html_from_transcript()
    print(f"html chars: {len(html)}")
    aulas = extract_lesson_durations(html)
    DURACOES_JSON.write_text(
        json.dumps(aulas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"aulas com duração: {len(aulas)}")
    if aulas:
        mins = [a["minutos"] for a in aulas]
        print(
            f"minutos vídeo: min={min(mins)} med={sorted(mins)[len(mins)//2]} max={max(mins)} "
            f"total_h={sum(mins)/60:.1f}"
        )
        # sample
        for a in aulas[:5]:
            print(f"  [{a['disciplina']}] {a['titulo']} -> {a['duracao']} ({a['minutos']} min)")

    stats = merge_into_seed(aulas)
    print(
        f"match seed: {stats['matched']} / missing: {len(stats['missing'])} / "
        f"extraidas: {stats['aulas_extraidas']}"
    )
    if stats["missing"][:10]:
        print("missing sample:")
        for m in stats["missing"][:10]:
            print(" ", m)


if __name__ == "__main__":
    main()
