"""
Recorre recursivamente la carpeta de Google Drive del catálogo, detecta PDFs
nuevos o modificados desde la última corrida (usando data/manifest.json) y
los descarga a un directorio temporal para su parseo.

Requiere la variable de entorno GDRIVE_SA_KEY_JSON con el contenido del
JSON de la service account (se guarda como secret en GitHub Actions).

Uso:
    python sync_drive.py --folder-id <ID_CARPETA_RAIZ> --out downloads/ --manifest data/manifest.json
"""
import argparse
import io
import json
import os
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def get_drive_service():
    key_json = os.environ.get('GDRIVE_SA_KEY_JSON')
    if not key_json:
        sys.exit('Falta la variable de entorno GDRIVE_SA_KEY_JSON')
    info = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


def list_pdfs_recursive(service, folder_id, path_prefix=''):
    """Devuelve lista de dicts {id, title, modifiedTime, path} para todos los
    PDFs bajo folder_id, recorriendo subcarpetas."""
    out = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields='nextPageToken, files(id, name, mimeType, modifiedTime)',
            pageToken=page_token,
            pageSize=1000,
        ).execute()
        for f in resp.get('files', []):
            if f['mimeType'] == 'application/vnd.google-apps.folder':
                out.extend(list_pdfs_recursive(service, f['id'], f"{path_prefix}{f['name']}/"))
            elif f['mimeType'] == 'application/pdf':
                out.append({
                    'id': f['id'],
                    'title': f['name'],
                    'modifiedTime': f['modifiedTime'],
                    'path': f"{path_prefix}{f['name']}",
                })
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return out


def download_file(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(dest_path, 'wb')
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folder-id', required=True)
    ap.add_argument('--out', required=True, help='directorio donde descargar PDFs nuevos/cambiados')
    ap.add_argument('--manifest', required=True, help='ruta a data/manifest.json')
    ap.add_argument('--force', action='store_true',
                     help='ignora el manifest y re-descarga/reprocesa TODOS los PDFs, '
                          'aunque su modifiedTime no haya cambiado. Util para un '
                          'backfill puntual (ej. despues de arreglar el parser) sin '
                          'esperar a que Vento vuelva a subir cada archivo.')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if os.path.exists(args.manifest):
        with open(args.manifest, encoding='utf-8') as f:
            manifest = json.load(f)
    else:
        manifest = {}

    service = get_drive_service()
    all_pdfs = list_pdfs_recursive(service, args.folder_id)
    print(f'Encontrados {len(all_pdfs)} PDFs en Drive.')
    if args.force:
        print('--force activo: se re-descargaran y reprocesaran TODOS los PDFs.')

    changed = []
    seen_ids = set()
    for f in all_pdfs:
        seen_ids.add(f['id'])
        prev = manifest.get(f['id'])
        if not args.force and prev and prev.get('modifiedTime') == f['modifiedTime']:
            continue  # sin cambios
        dest = os.path.join(args.out, f"{f['id']}.pdf")
        print(f"Descargando: {f['path']} ({f['id']})")
        download_file(service, f['id'], dest)
        changed.append({**f, 'local_path': dest})
        manifest[f['id']] = {
            'title': f['title'],
            'path': f['path'],
            'modifiedTime': f['modifiedTime'],
        }

    # Nota: si un archivo desaparece de Drive, NO se borra del manifest ni del
    # índice de compatibilidad — así conservas el respaldo histórico. Solo se
    # marca para referencia (opcional, se puede consultar seen_ids vs manifest).
    missing_ids = set(manifest.keys()) - seen_ids
    if missing_ids:
        print(f'{len(missing_ids)} archivo(s) ya no están en Drive (se conservan en el índice como histórico).')
        for mid in missing_ids:
            manifest[mid]['ausente_desde'] = manifest[mid].get('ausente_desde') or 'pendiente_de_fecha'

    with open(args.manifest, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)

    # Lista de trabajo para el siguiente paso (build_index.py)
    with open(os.path.join(args.out, '_changed.json'), 'w', encoding='utf-8') as f:
        json.dump(changed, f, ensure_ascii=False, indent=2)

    print(f'{len(changed)} PDF(s) nuevos o modificados, listos para parsear.')


if __name__ == '__main__':
    main()
