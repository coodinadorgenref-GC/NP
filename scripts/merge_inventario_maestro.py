"""
Fusiona compatibilidad (modelo/año) capturada en los reportes de
INVENTARIO (formato Coordinador, no PDF de catálogo) hacia
data/refacciones_index.json, de forma NO DESTRUCTIVA:

  - Código nuevo (no existía en el índice, ej. viene solo de PDF que
    nunca se subió a Drive) -> se agrega con su descripción y aplicaciones.
  - Código ya existente -> se conserva descripción y aplicaciones actuales;
    solo se AGREGAN aplicaciones (modelo, año) que no estuvieran ya
    presentes (comparación normalizada, insensible a mayúsculas/espacios).
  - Nunca se borra ni se desactiva nada de lo que ya había.

Cada aplicación agregada por esta vía queda marcada con
fuente_pdf = "INVENTARIO_MAESTRO_CRUZADO" (en vez del nombre del PDF)
para poder distinguir su origen si hace falta depurar después.

Uso:
    python merge_inventario_maestro.py \
        --rows rows_maestro.json \
        --index ../data/refacciones_index.json
"""
import argparse
import datetime
import json
import re

TODAY = datetime.date.today().isoformat()
FUENTE = "INVENTARIO_MAESTRO_CRUZADO"

# años válidos observados en los catálogos (2020-2026 con margen)
YEAR_RE = re.compile(r'^(.*?)[\s,]*\b(19|20)\d{2}\b\s*$')
JUNK_TOKENS = {'', 'VARIOS', 'TODOS', 'TODO', '-', '#N/A', 'N/A', 'NA'}


def _normaliza_clave(modelo, anio):
    m = re.sub(r'\s+', ' ', (modelo or '').strip()).upper()
    a = (anio or '').strip()
    return (m, a)


def parse_compatibilidad(texto):
    """Separa un string 'Modelo1 2024,Modelo2 2024' o
    'Modelo1 2024 - Modelo2 2023' en tokens (modelo, anio)."""
    if not texto:
        return []
    texto = texto.strip()
    if ' - ' in texto:
        partes = re.split(r'\s+-\s+', texto)
    else:
        partes = texto.split(',')

    SOLO_ANIO_RE = re.compile(r'^\s*(19|20)\d{2}\s*$')

    salida = []
    for p in partes:
        p = re.sub(r'\s+', ' ', p.strip())
        if not p or p.upper() in JUNK_TOKENS:
            continue

        # Coma capturada de más dentro del cuadro original (ej.
        # "HAWK 250,  2022") deja un token que es SOLO el año --
        # se pega a la entrada anterior si esa no tenía año todavía.
        if SOLO_ANIO_RE.match(p) and salida and salida[-1][1] is None:
            modelo_prev, _ = salida[-1]
            salida[-1] = (modelo_prev, p.strip())
            continue

        m = YEAR_RE.match(p)
        if m:
            modelo = m.group(1).strip().rstrip(',').strip()
            # recupera el año completo (el regex solo capturó el prefijo del siglo)
            anio_match = re.search(r'(19|20)\d{2}', p)
            anio = anio_match.group(0) if anio_match else None
            if not modelo:
                continue
            salida.append((modelo, anio))
        else:
            # sin año detectado (ej. "MAXI SCOOTER 175 M2") -- se conserva
            # igual, es información de compatibilidad válida aunque no
            # tenga año asociado
            salida.append((p, None))
    return salida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rows', required=True, help='rows_maestro.json (salida del merge INVENTARIO_MAESTRO_CRUZADO)')
    ap.add_argument('--index', required=True, help='ruta a data/refacciones_index.json')
    args = ap.parse_args()

    with open(args.rows, encoding='utf-8') as f:
        rows = json.load(f)
    with open(args.index, encoding='utf-8') as f:
        index = json.load(f)

    codigos_nuevos = 0
    aplicaciones_agregadas = 0
    codigos_tocados = set()

    for r in rows:
        codigo = r['codigo']
        # IMPORTANTE: parsear cada fuente POR SEPARADO, nunca el string ya
        # concatenado (compatibilidad_final mezcla separadores distintos:
        # 12-08 usa comas, 29-07 usa " - "; parsear el string unido rompe
        # el primer/último token de cada mitad).
        tokens = (
            parse_compatibilidad(r.get('compatibilidad_12_08'))
            + parse_compatibilidad(r.get('aplicacion_29_07'))
        )
        if not tokens:
            continue

        entry = index.get(codigo)
        if entry is None:
            entry = {'descripcion': r.get('descripcion') or '', 'aplicaciones': []}
            index[codigo] = entry
            codigos_nuevos += 1

        existentes = {
            _normaliza_clave(a['modelo'], a.get('anio') or '')
            for a in entry['aplicaciones']
        }

        for modelo, anio in tokens:
            clave = _normaliza_clave(modelo, anio or '')
            if clave in existentes:
                continue
            entry['aplicaciones'].append({
                'modelo': modelo,
                'anio': anio,
                'seccion_cod': None,
                'seccion_nombre': None,
                'fuente_pdf': FUENTE,
                'primera_vez': TODAY,
                'ultima_vez': TODAY,
                'activo': True,
            })
            existentes.add(clave)
            aplicaciones_agregadas += 1
            codigos_tocados.add(codigo)

    with open(args.index, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f'Códigos nuevos agregados al índice: {codigos_nuevos}')
    print(f'Aplicaciones (modelo/año) nuevas agregadas: {aplicaciones_agregadas}')
    print(f'Códigos existentes que recibieron al menos 1 aplicación nueva: {len(codigos_tocados) - codigos_nuevos}')
    print(f'Total códigos en el índice ahora: {len(index)}')


if __name__ == '__main__':
    main()
