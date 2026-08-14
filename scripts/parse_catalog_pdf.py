"""
Parsea un PDF de catálogo "por modelo" de Vento (estructura:
SECCION: VCxx/VMxx <NOMBRE> seguido de una tabla Ref. | Código | Descripción)
y devuelve una lista de piezas encontradas.

Algunos PDFs del Drive (ej. "Yuma 250 - 2026.pdf") tienen la tabla
incrustada como IMAGEN (captura de pantalla) o como DIAGRAMA VECTORIAL
(dibujo de líneas/curvas, ej. despieces de motor) en vez de texto/tabla
real -- pdfplumber no puede leer texto de ninguno de los dos casos. Para
esos casos se activa un respaldo con OCR (tesseract) que renderiza la
página completa como imagen y lee el texto.

Nota: pdfplumber solo cuenta como "imagen" los objetos raster (fotos/
capturas incrustadas), NO los gráficos vectoriales. Por eso el OCR se
activa siempre que no se encontró ninguna tabla de texto en la página,
en vez de basarse en el % de área cubierta por imágenes -- ese umbral
subestimaba páginas dominadas por diagramas vectoriales (ej. "Phantom S
170 - 2026.pdf", donde despieces de estator/generador son vectores y se
saltaban silenciosamente, dando solo 4 códigos extraídos de todo el PDF).

Uso como librería:
    from parse_catalog_pdf import parse_pdf, parse_model_year_from_filename
    filas = parse_pdf("Tornado 300 - 2026.pdf")
"""
import re
import pdfplumber

# Código de refacción Vento: 2 letras + 6-8 dígitos (ej. VC01020046, VM04020045)
CODE_RE = re.compile(r'^[A-Z]{2}\d{6,8}$')
# case-insensitive: el OCR a veces lee el código en minúsculas (ej. "vM10010035")
CODE_ANYWHERE_RE = re.compile(r'\b[A-Z]{2}\d{6,8}\b', re.IGNORECASE)
SECTION_RE = re.compile(r'SECCION:\s*([A-Z]{2}\d{2})\s+([^\n]+)')
# "Tornado 300 - 2026.pdf" -> modelo="Tornado 300", anio="2026"
FILENAME_RE = re.compile(r'^(.*?)\s*-\s*(\d{4})\s*\.pdf$', re.IGNORECASE)

# (Histórico) Umbral que se usaba para decidir si activar OCR según el
# área cubierta por imágenes rasterizadas. Se dejó de usar como gate
# porque no detectaba diagramas vectoriales (ver nota arriba); ahora el
# OCR se activa siempre que la página no produjo ninguna tabla de texto.
UMBRAL_AREA_IMAGEN = 0.30


def parse_model_year_from_filename(filename):
    m = FILENAME_RE.match(filename.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return filename.rsplit('.', 1)[0].strip(), None


def _area_imagenes(page):
    area_pagina = page.width * page.height
    if area_pagina == 0:
        return 0.0
    area_img = sum(
        max(0, img['x1'] - img['x0']) * max(0, img['bottom'] - img['top'])
        for img in page.images
    )
    return area_img / area_pagina


def _parse_tabla_texto(page):
    """Extrae filas Ref/Código/Descripción de tablas de texto real
    (rápido y confiable cuando el PDF sí tiene texto seleccionable)."""
    filas = []
    for table in page.extract_tables():
        if not table:
            continue
        header = [c.strip() if c else '' for c in table[0]]
        if 'Código' not in header and 'Ref.' not in header:
            continue  # no es la tabla de refacciones (ej. tabla de aceite)
        for row in table[1:]:
            if not row or len(row) < 3:
                continue
            ref, codigo, desc = row[0], row[1], row[2]
            if not codigo:
                continue
            codigo = codigo.strip()
            if not CODE_RE.match(codigo):
                continue
            desc = (desc or '').replace('\n', ' ').strip()
            filas.append({'ref': (ref or '').strip(), 'codigo': codigo, 'descripcion': desc})
    return filas


def _linea_util(linea):
    """Filtra ruido de OCR (líneas de diagrama, números sueltos,
    símbolos) que no aporta a la descripción."""
    letras = sum(c.isalpha() for c in linea)
    return letras >= 3


# El pie de página institucional ("Si tienes dudas escríbenos...
# vento.com", el logo "VENTO") aparece en TODAS las páginas y el OCR lo
# lee como texto normal. Si la última fila real de la tabla queda antes
# del pie de página (el caso común), ese texto se pegaba a la
# descripción de esa última fila porque no hay ningún código después
# que cierre la fila y dispare cerrar_actual(). Se filtra aparte en vez
# de depender de _linea_util (que sí cuenta como "útil" por tener
# suficientes letras).
_RUIDO_PIE_PAGINA_RE = re.compile(r'vento\.com|whatsapp|^VEN.?TO$', re.IGNORECASE)


def _es_ruido_pie_pagina(linea):
    return bool(_RUIDO_PIE_PAGINA_RE.search(linea))


# Fila OCR con Ref + Código + Descripción juntos en una sola línea, ej.
# "1  VM10010035  Estator" (tablas con texto real bajo el diagrama, donde
# OCR sí conserva la fila completa). El OCR de estas tablas mete ruido
# de los bordes de celda como separador en vez de espacio real (ej.
# "1_|vM10010035" o "2 |VM10030023 [Rotor"), y a veces confunde
# mayúsculas/minúsculas del código (ej. "vM10010035" en vez de
# "VM10010035") -- por eso la clase de separador acepta |, [, ], _
# ademas de espacio/punto/parentesis, y el match es case-insensitive
# (el código se normaliza a mayúsculas al capturarlo).
FILA_COMPLETA_OCR_RE = re.compile(
    r'^(\d{1,3})[\s.\)_|\[\]\\/]*([A-Z]{2}\d{6,8})[\s|\[\]]*(.*)$',
    re.IGNORECASE,
)


def _parse_tabla_ocr(page):
    """Respaldo: renderiza la página como imagen y usa OCR.

    Maneja DOS formatos distintos que aparecen en los catálogos, porque
    el layout de la tabla en la imagen varía según el PDF:

      1) Ref + Código + Descripción en la MISMA línea de OCR
         (ej. "1 VM10010035 Estator") -> fila completa de una vez.
      2) Código SOLO en su propia línea, con la descripción en la(s)
         línea(s) siguiente(s) -> se acumulan hasta el siguiente código.

    Si solo se maneja el caso 2 (como antes), tablas del tipo 1 pierden
    TODAS sus filas en silencio: cada línea "1 VM10010035 Estator" es más
    larga que "código + 3 caracteres", nunca dispara "código solo", y
    termina tratada como texto descriptivo de la fila anterior (o se
    descarta si es la primera fila de la tabla). Esto pasó con
    "Hipster 170 - 2025.pdf" pág. 32: la tabla completa (VM10010035,
    VM10030023, VM10010026) se perdía sin ningún aviso.

    --psm 6 (asume un solo bloque uniforme de texto) en vez del default
    (--psm 3, que intenta segmentar párrafos/columnas) porque en tablas
    densas el modo automático se saltaba filas completas -- probado
    contra el PDF real: con psm 3 tesseract solo leía 1 de 3 filas de la
    sección VM10 GENERADOR; con psm 6 lee las 3.
    """
    import pytesseract

    im = page.to_image(resolution=300).original
    texto = pytesseract.image_to_string(im, config='--psm 6')

    filas = []
    codigo_actual = None
    ref_actual = ''
    desc_lines = []

    def cerrar_actual():
        if codigo_actual:
            desc = ' '.join(l.strip() for l in desc_lines if _linea_util(l)).strip()
            filas.append({'ref': ref_actual, 'codigo': codigo_actual, 'descripcion': desc})

    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or _es_ruido_pie_pagina(linea):
            continue

        m_completa = FILA_COMPLETA_OCR_RE.match(linea)
        if m_completa:
            cerrar_actual()
            ref_actual = m_completa.group(1)
            codigo_actual = m_completa.group(2).upper()
            resto = m_completa.group(3).strip()
            desc_lines = [resto] if resto else []
            continue

        m = CODE_ANYWHERE_RE.search(linea)
        # una línea que es *solo* el código (o el código + basura corta)
        # marca el inicio de una nueva pieza
        if m and len(linea) <= len(m.group(0)) + 3:
            cerrar_actual()
            ref_actual = ''
            codigo_actual = m.group(0).upper()
            desc_lines = []
        else:
            desc_lines.append(linea)
    cerrar_actual()
    return filas


def parse_pdf(path, usar_ocr=True):
    """Devuelve (results, diagnosticos).

    results: lista de dicts seccion_cod, seccion_nombre, ref, codigo,
    descripcion, pagina, fuente.

    diagnosticos: lista de páginas donde se detectó un encabezado de
    sección ("SECCION: VMxx ...", es decir, la página SÍ debería traer
    una tabla de refacciones) pero terminamos con 0 filas extraídas ahí
    -- ni por texto ni por OCR. Antes esto pasaba en silencio (ver caso
    "Hipster 170 - 2025.pdf" pág. 32); ahora queda registrado para poder
    revisar manualmente en vez de descubrirlo por accidente meses después.
    """
    results = []
    diagnosticos = []
    current_section = (None, None)
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            m = SECTION_RE.search(text)
            if m:
                current_section = (m.group(1), m.group(2).strip())

            filas = _parse_tabla_texto(page)
            fuente = 'texto'

            # Respaldo OCR: si no se encontró ninguna tabla de texto real,
            # asumimos que la tabla está "quemada" en la página (imagen
            # raster o diagrama vectorial) y renderizamos + OCR. Ya no se
            # filtra por % de área de imagen (ver nota al inicio del archivo).
            if not filas and usar_ocr:
                filas = _parse_tabla_ocr(page)
                fuente = 'ocr'

            # Diagnóstico: la página anuncia una sección de refacciones
            # (SECCION: VMxx/VCxx ...) pero no se extrajo ninguna fila.
            # No se limita a páginas con "m" (sección nueva en ESTA
            # página) porque una sección puede seguir vigente de la
            # página anterior y aun así traer su propia tabla.
            if not filas and current_section[0] is not None:
                diagnosticos.append({
                    'pagina': i,
                    'seccion_cod': current_section[0],
                    'seccion_nombre': current_section[1],
                    'motivo': 'seccion detectada pero 0 filas extraidas (ni texto ni OCR)',
                })

            for f in filas:
                results.append({
                    'seccion_cod': current_section[0],
                    'seccion_nombre': current_section[1],
                    'ref': f['ref'],
                    'codigo': f['codigo'],
                    'descripcion': f['descripcion'],
                    'pagina': i,
                    'fuente': fuente,
                })
    return results, diagnosticos


if __name__ == '__main__':
    import sys
    import json
    path = sys.argv[1]
    filas, diagnosticos = parse_pdf(path)
    print(json.dumps({'filas': filas, 'diagnosticos': diagnosticos}, ensure_ascii=False, indent=2))
