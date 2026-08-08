"""
Normaliza medidas de llanta escritas en distintas notaciones a una clave
canónica, para poder detectar que "3.00-17", "3.00-R17", "3.00/17",
"300/17" y "300-17" son LA MISMA medida.

Cubre dos sistemas de notación que Vento usa en paralelo:

  - "Bias" / pulgadas (ancho nominal en pulgadas - rin):
      3.00-17, 3.00-R17, 3.00/17, 300/17, 300-17   -> ancho=3.00", rin=17
  - "Métrico" (ancho en mm / relación de aspecto - rin):
      120/90-18, 80/100-21, 130/70-R17             -> ancho=120mm, aspecto=90, rin=18

NO resuelve equivalencia FÍSICA entre los dos sistemas (ej. si un
"80/100-21" cabe donde va un "3.00-21"). Eso requiere una tabla de
conversión validada por alguien con el catálogo físico, no se puede
inferir del texto. Ver tabla_equivalencias_medidas.json.
"""
import re

NUM = r'(\d+(?:\.\d+)?)'

# separador entre el (ancho o aspecto) y el rin: cubre "-", "/", " ",
# "R", "RIN", "-R", "/R", "-RIN", " RIN ", etc.
SEP_RIN = r'\s*(?:-\s*R(?:IN)?|/\s*R(?:IN)?|R(?:IN)?|-|/)\s*'

# metric: ancho/aspecto SEP_RIN rin  (3 números; el separador entre
# ancho y aspecto SIEMPRE es "/", el separador antes del rin es flexible)
METRIC_RE = re.compile(
    rf'{NUM}\s*/\s*{NUM}{SEP_RIN}{NUM}', re.IGNORECASE
)

# bias: ancho SEP_RIN rin  (2 números; "ancho" puede venir con decimal
# -> 3.00 -> o sin decimal como entero de 3 cifras -> 300)
BIAS_RE = re.compile(
    rf'{NUM}{SEP_RIN}{NUM}', re.IGNORECASE
)

# ATV/cuatrimoto: diámetro x ancho - rin (ej. "22x10-10")
ATV_RE = re.compile(
    rf'{NUM}\s*[xX×]\s*{NUM}{SEP_RIN}{NUM}'
)


def _norm_bias_width(raw):
    """'300' -> 3.00   |  '3.00' -> 3.00  |  '2.5' -> 2.50"""
    v = float(raw)
    if v >= 100 and '.' not in raw:
        v = v / 100.0
    return round(v, 2)


def parse_medida(texto):
    """
    Devuelve una clave canónica tipo:
      ('metric', ancho_mm:int, aspecto:int, rin:int)   ej. ('metric', 120, 90, 18)
      ('bias', ancho_in:float, rin:int)                ej. ('bias', 3.0, 17)
      ('atv', diametro_in:float, ancho_in:float, rin:int)  ej. ('atv', 22.0, 10.0, 10)
    o None si no se reconoce ninguna medida en el texto.

    Las llantas ATV/cuatrimoto usan un TERCER sistema: diámetro x ancho
    - rin (ej. "22x10-10" o, en el catálogo Vento, "22/10 RIN 10").
    Numéricamente luce igual que la notación métrica (dos números y un
    rin), pero el significado es distinto -- por eso se detecta aparte,
    usando la palabra "ATV" en el texto o el separador "x" como señal.
    """
    if not texto:
        return None
    t = texto.upper()

    m = ATV_RE.search(t)
    if m:
        d, w, rin = m.groups()
        return ('atv', float(d), float(w), int(round(float(rin))))

    es_atv = 'ATV' in t
    m = METRIC_RE.search(t)
    if m:
        n1, n2, rin = m.groups()
        if es_atv:
            return ('atv', float(n1), float(n2), int(round(float(rin))))
        return ('metric', int(round(float(n1))), int(round(float(n2))), int(round(float(rin))))

    m = BIAS_RE.search(t)
    if m:
        ancho_raw, rin_raw = m.groups()
        ancho = _norm_bias_width(ancho_raw)
        rin = int(round(float(rin_raw)))
        return ('bias', ancho, rin)

    return None


def medida_canonica_str(clave):
    """Representación legible de la clave canónica, para mostrar en UI."""
    if clave is None:
        return None
    if clave[0] == 'metric':
        _, ancho, aspecto, rin = clave
        return f'{ancho}/{aspecto}-{rin}'
    if clave[0] == 'atv':
        _, d, w, rin = clave
        return f'{d:g}x{w:g}-{rin}'
    if clave[0] == 'bias_rango':
        _, amin, amax, rin = clave
        return f'{amin:.2f}/{amax:.2f}-{rin}'
    _, ancho, rin = clave
    return f'{ancho:.2f}-{rin}'


# ---------------------------------------------------------------------
# Recámaras (cámaras de aire): a diferencia de las llantas, una misma
# recámara suele cubrir un RANGO de anchos de llanta, no una medida
# puntual. Ej. "2.75/3.00-R18" significa que sirve para llantas de
# 2.75 A 3.00 pulgadas en rin 18 — no son dos medidas distintas.
# ---------------------------------------------------------------------

WIDTHS_METRICAS_CONOCIDAS = [80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180]


def _expandir_rango_abreviado(a1, a2):
    """Atajo común del gremio: en un rango tipo '3.50/75', el segundo
    número comparte el entero del primero y se escribe recortado
    ('75' en vez de '3.75'). Si a2 no tiene punto y es de 2 cifras,
    se reconstruye usando la parte entera de a1."""
    if '.' in a1 and '.' not in a2 and len(a2) == 2:
        entero = a1.split('.')[0]
        return a1, f'{entero}.{a2}'
    return a1, a2


def _preseparar_jam(texto):
    """Inserta separadores en bloques de dígitos pegados típicos de
    medidas métricas mal capturadas, ej. '12090' -> '120/90',
    'RUEDA TRASERA' se ignora, solo actúa sobre bloques de 4-5 dígitos."""
    def repl(m):
        bloque = m.group(0)
        for w in WIDTHS_METRICAS_CONOCIDAS:
            sw = str(w)
            if bloque.startswith(sw):
                resto = bloque[len(sw):]
                if resto.isdigit() and 2 <= len(resto) <= 3:
                    return f'{sw}/{resto}'
        return bloque
    return re.sub(r'\b\d{4,5}\b', repl, texto)


def parse_medida_camara(texto):
    """
    Devuelve una clave canónica para recámaras:
      ('metric', ancho_mm:int, aspecto:int, rin:int)
      ('bias_rango', ancho_min:float, ancho_max:float, rin:int)   -- CUBRE un rango
      ('bias', ancho_in:float, rin:int)
    o None si no se reconoce ninguna medida.
    """
    if not texto:
        return None
    t = _preseparar_jam(texto.upper())
    # normalizar separador de ancho/aspecto: a veces viene con espacio o guion
    # en vez de "/", ej. "80 100 R21" o "130-70-17"
    t = re.sub(r'(\d)\s*[-\s]\s*(\d)(\s*(?:R|RIN)?\s*\d)', r'\1/\2\3', t, count=1)

    m = METRIC_RE.search(t)
    if m:
        a1, a2, rin = m.groups()
        # atajo del gremio: '3.50/75' -> '3.50/3.75' (a2 recortado
        # comparte el entero de a1)
        a1, a2 = _expandir_rango_abreviado(a1, a2)
        # si ambos números traen punto decimal, es notación bias (rango),
        # no métrica -- los anchos métricos siempre son enteros
        if '.' not in a1 and '.' not in a2:
            return ('metric', int(round(float(a1))), int(round(float(a2))), int(round(float(rin))))
        amin, amax = sorted([float(a1), float(a2)])
        return ('bias_rango', round(amin, 2), round(amax, 2), int(round(float(rin))))

    m = BIAS_RE.search(t)
    if m:
        ancho_raw, rin_raw = m.groups()
        ancho = _norm_bias_width(ancho_raw)
        rin = int(round(float(rin_raw)))
        return ('bias', ancho, rin)

    return None


def talla_en_rango(ancho_llanta, clave_camara):
    """¿El ancho (en pulgadas, sistema bias) de una llanta cae dentro
    del rango que cubre esta recámara? Solo compara dentro del MISMO
    sistema de notación (bias vs bias) -- no cruza bias con métrico,
    eso requiere la tabla de equivalencias físicas confirmadas."""
    if clave_camara is None:
        return False
    if clave_camara[0] == 'bias_rango':
        _, amin, amax, _ = clave_camara
        return amin <= ancho_llanta <= amax
    if clave_camara[0] == 'bias':
        _, ancho, _ = clave_camara
        return ancho == ancho_llanta
    return False


if __name__ == '__main__':
    print('--- Llantas ATV ---')
    casos_atv = [
        'LLANTA 22/10-10 TL # L 4  ATV',
        'LLANTA 23/7-10 TL # L 4  ATV',
        '22x10-10',
        '22X10-10',
    ]
    for c in casos_atv:
        clave = parse_medida(c)
        print(f'{c!r:40} -> {clave}  ({medida_canonica_str(clave)})')

    print()
    print('--- Rango abreviado en recámara ---')
    for c in ['CAMARA 3.50/75-17', 'CAMARA 3.50/3.75-17']:
        clave = parse_medida_camara(c)
        print(f'{c!r:30} -> {clave}  ({medida_canonica_str(clave)})')

    print()
    casos_camara = [
        'CAMARA 2.75/3.00-R18',
        'CAMARA 3.00-17',
        'CAMARA 120/80-18',
        'CAMARA NEUMATICA  3.00-21',
        'CAMARA 2.50/2.75-R17',
        'CAMARA 110/90-17',
        'CAMARA 3.50-18',
        'CAMARA NEUMATICA 2.50/2.75-18',
        'CAMARA NEUMATICA 3.75/4.000-18',
        'CAMARA RUEDA DEL 80 100 R21',
        'CAMARA RUEDA TRASERA 12090 R18',
        'CAMARA TRASERA 130-70-17',
        'CAMARA DELANTERA 2.75 18',
        'CAMARA DELANTERA 3.0-17',
        'CAMARA TRASERA 3.00 18',
        'CAMARA WI-FI  SOLAR',
        'CG CAMARA INTERNACIONAL DE CINCO ENGRANAJES',
    ]
    print('--- Recámaras ---')
    for c in casos_camara:
        clave = parse_medida_camara(c)
        print(f'{c!r:50} -> {clave}  ({medida_canonica_str(clave)})')

    print()
    print('--- ¿Una llanta 2.90-18 cabe en la recámara 2.75/3.00-R18? ---')
    clave = parse_medida_camara('CAMARA 2.75/3.00-R18')
    print(talla_en_rango(2.90, clave))
