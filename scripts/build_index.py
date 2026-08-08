"""
Toma los PDFs descargados por sync_drive.py (downloads/_changed.json + los
.pdf), los parsea con parse_catalog_pdf y hace merge NO DESTRUCTIVO sobre
data/refacciones_index.json:

  - Código nuevo -> se agrega.
  - Aplicación (modelo+sección) ya existente -> se actualiza descripción y
    fecha "ultima_vez", se marca activo=true.
  - Aplicación que pertenece a un PDF que se volvió a procesar pero cuya fila
    ya no aparece -> se marca activo=false (se conserva, no se borra).
  - PDFs no tocados en esta corrida -> sus aplicaciones no se tocan.

Esto da respaldo automático: si Vento quita un modelo o una pieza del Drive,
tu índice conserva el último estado conocido marcado como inactivo, en vez
de perder la información.
"""
import argparse
import datetime
import json
import os

from parse_catalog_pdf import parse_pdf, parse_model_year_from_filename
from tire_size_normalizer import parse_medida, parse_medida_camara, medida_canonica_str

TODAY = datetime.date.today().isoformat()


def _detectar_medida(codigo, descripcion):
    """Si la pieza es llanta o recámara, intenta extraer su medida
    canónica a partir de la descripción, para mostrarla en el buscador
    y poder comparar tallas entre códigos distintos. Devuelve None si
    no aplica o no se reconoce ninguna medida."""
    desc_up = (descripcion or '').upper()
    es_camara = 'CAMARA' in desc_up or 'RECAMARA' in desc_up or codigo.startswith('CAM')
    es_llanta = 'LLANTA' in desc_up or codigo.startswith('VG')

    if es_camara:
        clave = parse_medida_camara(descripcion)
    elif es_llanta:
        clave = parse_medida(descripcion)
    else:
        return None

    if clave is None:
        return None
    return {'tipo': clave[0], 'canonica': medida_canonica_str(clave)}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--downloads', required=True, help='directorio con los PDFs descargados + _changed.json')
    ap.add_argument('--index', required=True, help='ruta a data/refacciones_index.json')
    args = ap.parse_args()

    changed_path = os.path.join(args.downloads, '_changed.json')
    changed = load_json(changed_path, [])
    if not changed:
        print('No hay PDFs nuevos/modificados. Nada que actualizar.')
        return

    index = load_json(args.index, {})  # { codigo: { descripcion, aplicaciones: [...] } }

    for f in changed:
        modelo, anio = parse_model_year_from_filename(f['title'])
        fuente = f['title']
        filas = parse_pdf(f['local_path'])
        print(f"{fuente}: {len(filas)} filas parseadas (modelo={modelo}, año={anio})")

        vistos_en_este_pdf = set()

        for fila in filas:
            codigo = fila['codigo']
            entry = index.setdefault(codigo, {'descripcion': fila['descripcion'], 'aplicaciones': []})
            # la descripción más reciente gana (suele ser más completa)
            if fila['descripcion']:
                entry['descripcion'] = fila['descripcion']

            medida = _detectar_medida(codigo, entry['descripcion'])
            if medida:
                entry['medida'] = medida

            clave_app = (modelo, anio, fila['seccion_cod'])
            vistos_en_este_pdf.add((codigo, clave_app))

            existente = next(
                (a for a in entry['aplicaciones']
                 if (a['modelo'], a['anio'], a['seccion_cod']) == clave_app),
                None,
            )
            if existente:
                existente['activo'] = True
                existente['ultima_vez'] = TODAY
                existente['seccion_nombre'] = fila['seccion_nombre']
                existente['fuente_pdf'] = fuente
            else:
                entry['aplicaciones'].append({
                    'modelo': modelo,
                    'anio': anio,
                    'seccion_cod': fila['seccion_cod'],
                    'seccion_nombre': fila['seccion_nombre'],
                    'fuente_pdf': fuente,
                    'primera_vez': TODAY,
                    'ultima_vez': TODAY,
                    'activo': True,
                })

        # Soft-delete: aplicaciones de ESTE mismo modelo/PDF que ya no
        # aparecieron en la nueva versión del PDF.
        for codigo, entry in index.items():
            for a in entry['aplicaciones']:
                if a['fuente_pdf'] == fuente and a['modelo'] == modelo and a['anio'] == anio:
                    if (codigo, (a['modelo'], a['anio'], a['seccion_cod'])) not in vistos_en_este_pdf:
                        if a.get('activo', True):
                            a['activo'] = False
                            a['desactivado_el'] = TODAY

    with open(args.index, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)

    _anotar_medidas_relacionadas(index)

    with open(args.index, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f'Índice actualizado: {len(index)} códigos totales.')


def _anotar_medidas_relacionadas(index):
    """Para cada llanta/recámara con medida detectada, anota qué otros
    códigos comparten la MISMA medida canónica -- como referencia para
    quien busca, nunca como fusión automática (mismo tamaño puede ser
    distinto dibujo/uso, ver conversación sobre 3.00-18 P3 vs P4)."""
    from collections import defaultdict

    por_medida = defaultdict(list)
    for codigo, entry in index.items():
        medida = entry.get('medida')
        if medida:
            por_medida[(medida['tipo'], medida['canonica'])].append(codigo)

    for codigo, entry in index.items():
        medida = entry.get('medida')
        if not medida:
            continue
        hermanos = [c for c in por_medida[(medida['tipo'], medida['canonica'])] if c != codigo]
        if hermanos:
            entry['medida']['otros_codigos_misma_medida'] = sorted(hermanos)


if __name__ == '__main__':
    main()
