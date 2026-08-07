"""
Parsea un PDF de catálogo "por modelo" de Vento (estructura:
SECCION: VCxx/VMxx <NOMBRE> seguido de una tabla Ref. | Código | Descripción)
y devuelve una lista de piezas encontradas.

Uso como librería:
    from parse_catalog_pdf import parse_pdf, parse_model_year_from_filename
    filas = parse_pdf("Tornado 300 - 2026.pdf")
"""
import re
import pdfplumber

# Código de refacción Vento: 2 letras + 6-8 dígitos (ej. VC01020046, VM04020045)
CODE_RE = re.compile(r'^[A-Z]{2}\d{6,8}$')
SECTION_RE = re.compile(r'SECCION:\s*([A-Z]{2}\d{2})\s+([^\n]+)')
# "Tornado 300 - 2026.pdf" -> modelo="Tornado 300", anio="2026"
FILENAME_RE = re.compile(r'^(.*?)\s*-\s*(\d{4})\s*\.pdf$', re.IGNORECASE)


def parse_model_year_from_filename(filename):
    m = FILENAME_RE.match(filename.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # fallback: sin año detectable
    return filename.rsplit('.', 1)[0].strip(), None


def parse_pdf(path):
    """Devuelve lista de dicts: seccion_cod, seccion_nombre, ref, codigo, descripcion, pagina"""
    results = []
    current_section = (None, None)
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            m = SECTION_RE.search(text)
            if m:
                current_section = (m.group(1), m.group(2).strip())

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
                    results.append({
                        'seccion_cod': current_section[0],
                        'seccion_nombre': current_section[1],
                        'ref': (ref or '').strip(),
                        'codigo': codigo,
                        'descripcion': desc,
                        'pagina': i,
                    })
    return results


if __name__ == '__main__':
    import sys
    import json
    path = sys.argv[1]
    filas = parse_pdf(path)
    print(json.dumps(filas, ensure_ascii=False, indent=2))
