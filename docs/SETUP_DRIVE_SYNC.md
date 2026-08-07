# Sincronización automática Drive → índice de compatibilidad

Esto conecta tu carpeta de Drive (`197vrtgA3CLZz5gxJf3PM0_CKgrT9tFCR`) con tu
repo de GitHub Pages. Corre una vez al día (o manualmente), detecta PDFs
nuevos/modificados, los parsea y actualiza `data/refacciones_index.json` sin
borrar nunca información histórica.

## 1. Crear la service account en Google Cloud

1. Ve a https://console.cloud.google.com/ y crea (o reutiliza) un proyecto.
2. Habilita la **Google Drive API** (menú "APIs y servicios" → "Habilitar APIs").
3. "APIs y servicios" → "Credenciales" → "Crear credenciales" → **Cuenta de servicio**.
   - Nombre sugerido: `sync-refacciones`
   - No necesita roles de proyecto (solo se usará para leer Drive).
4. Entra a la cuenta de servicio creada → pestaña "Claves" → "Agregar clave" →
   **JSON**. Se descarga un archivo `.json`. Guárdalo, lo necesitas en el paso 3.
5. Copia el **email** de la cuenta de servicio (algo como
   `sync-refacciones@tu-proyecto.iam.gserviceaccount.com`).

## 2. Compartir la carpeta de Drive con la service account

1. Abre https://drive.google.com/drive/folders/197vrtgA3CLZz5gxJf3PM0_CKgrT9tFCR
2. Clic derecho → "Compartir" → pega el email de la service account →
   permiso **Viewer (Lector)** → Enviar.
   - Esto es suficiente porque el pipeline solo lee, nunca escribe en Drive.

## 3. Configurar el repo de GitHub

En tu repo `coodinadorgenref-gc/NP`:

1. **Settings → Secrets and variables → Actions → New repository secret**
   - Nombre: `GDRIVE_SA_KEY_JSON`
   - Valor: pega el contenido completo del archivo `.json` descargado en el paso 1.4.
2. **Settings → Secrets and variables → Actions → Variables → New repository variable**
   - Nombre: `GDRIVE_FOLDER_ID`
   - Valor: `197vrtgA3CLZz5gxJf3PM0_CKgrT9tFCR`
3. Copia estos archivos a tu repo (respetando las rutas):
   - `scripts/parse_catalog_pdf.py`
   - `scripts/sync_drive.py`
   - `scripts/build_index.py`
   - `.github/workflows/sync-refacciones.yml`
   - crea una carpeta vacía `data/` (puede llevar un `.gitkeep`)

## 4. Primera corrida

- Ve a la pestaña **Actions** de tu repo → "Sync catálogo desde Google Drive"
  → **Run workflow** (botón manual). Esto va a bajar y parsear TODOS los PDFs
  la primera vez (puede tardar varios minutos porque son ~7 años de catálogos).
- Corridas siguientes son incrementales: solo procesan lo que cambió de fecha
  de modificación en Drive.

## 5. Conectar el índice con tu buscador (`index.html` del sitio)

`data/refacciones_index.json` queda con esta forma:

```json
{
  "VC02010037": {
    "descripcion": "BATERIA VENTO GEL YB6L-B -,+",
    "aplicaciones": [
      {
        "modelo": "Screamer 300 Sportiva",
        "anio": "2026",
        "seccion_cod": "VC02",
        "seccion_nombre": "SISTEMA ELECTRICO",
        "fuente_pdf": "Screamer 300 Sportiva - 2026.pdf",
        "primera_vez": "2026-08-07",
        "ultima_vez": "2026-08-07",
        "activo": true
      }
    ]
  }
}
```

En tu buscador solo tienes que hacer `fetch('data/refacciones_index.json')`
y buscar por clave (`índice[códigoBuscado]`). Si quieres, en la UI puedes
mostrar en gris/aparte las aplicaciones con `"activo": false` (piezas que ya
no aparecen en el catálogo vigente de Drive, pero que siguen documentadas
como respaldo histórico).

## Notas sobre el respaldo/histórico

- **Nunca se borra nada del JSON automáticamente.** Si Vento quita un modelo
  o una pieza de Drive, la próxima corrida solo la marca `activo: false` con
  fecha de desactivación — el dato sigue disponible.
- El **historial de git** de tu repo es un respaldo adicional: cada commit
  automático queda versionado, así que puedes ver exactamente qué cambió
  cada día (`git log -p -- data/refacciones_index.json`) y hacer rollback si
  hace falta.
- Si en algún momento quieres purgar de verdad piezas inactivas muy viejas,
  hazlo como paso manual aparte — el pipeline nunca lo hace solo.
