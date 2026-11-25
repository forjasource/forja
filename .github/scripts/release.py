#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CARPETA = 'script.forja'
ID_ADDON = 'script.forja'
RE_VERSION = re.compile(r'^\d+(\.\d+){1,3}([-+~][0-9A-Za-z.]+)?$')
RE_ZIP_HTML = re.compile(r'script\.forja-[0-9][0-9A-Za-z.+~-]*?\.zip')
FECHA_ZIP = (2024, 1, 1, 0, 0, 0)


def fallo(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    sys.exit(1)


def cargar_huella():
    ruta = RAIZ / CARPETA / 'resources' / 'lib' / 'huella_arbol.py'
    espec = importlib.util.spec_from_file_location('huella_arbol', ruta)
    mod = importlib.util.module_from_spec(espec)
    espec.loader.exec_module(mod)
    return mod


def sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b''):
            h.update(bloque)
    return h.hexdigest()


def escribir_si_cambia(ruta, contenido_bytes):
    if ruta.exists() and ruta.read_bytes() == contenido_bytes:
        return False
    ruta.write_bytes(contenido_bytes)
    return True


def poner_version_en_addon_xml(version):
    ruta = RAIZ / CARPETA / 'addon.xml'
    if not ruta.exists():
        fallo('No existe %s' % ruta)
    texto = ruta.read_bytes().decode('utf-8')
    m = re.search(r'<addon\b[^>]*>', texto)
    if not m:
        fallo('addon.xml no tiene la etiqueta <addon>')
    etiqueta = m.group(0)
    if 'id="%s"' % ID_ADDON not in etiqueta:
        fallo('El id del addon no es %s' % ID_ADDON)
    nueva, n = re.subn(r'(\bversion=")[^"]*(")', r'\g<1>%s\g<2>' % version, etiqueta, count=1)
    if n != 1:
        fallo('No se encontró version="..." en la etiqueta <addon>')
    if nueva != etiqueta:
        ruta.write_bytes((texto[:m.start()] + nueva + texto[m.end():]).encode('utf-8'))
        print('addon.xml -> versión %s' % version)


def construir_zip(huella, destino):
    carpeta = RAIZ / CARPETA
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, ruta in huella.archivos(str(carpeta)):
            info = zipfile.ZipInfo('%s/%s' % (CARPETA, rel), date_time=FECHA_ZIP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            with open(ruta, 'rb') as f:
                z.writestr(info, f.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def actualizar_html(nombre_zip):
    ruta = RAIZ / 'index.html'
    if not ruta.exists():
        html = ('<html>\n <head>\n <h1>Root/</h1>\n </head>\n <body>\n'
                '    <li><a href="%s">%s</a></li>\n </body></html>\n' % (nombre_zip, nombre_zip))
        ruta.write_bytes(html.encode('utf-8'))
        return True
    texto = ruta.read_bytes().decode('utf-8')
    if RE_ZIP_HTML.search(texto):
        nuevo = RE_ZIP_HTML.sub(nombre_zip, texto)
    else:
        item = '    <li><a href="%s">%s</a></li>\n' % (nombre_zip, nombre_zip)
        nuevo = texto.replace('</body>', item + ' </body>', 1) if '</body>' in texto else texto + item
    return escribir_si_cambia(ruta, nuevo.encode('utf-8'))


def main():
    ruta_json = RAIZ / 'forja.json'
    if not ruta_json.exists():
        fallo('Falta forja.json en la raíz del repositorio')
    try:
        datos = json.loads(ruta_json.read_text(encoding='utf-8'))
    except ValueError as e:
        fallo('forja.json no es un JSON válido: %s' % e)
    version = str(datos.get('version') or '').strip()
    if not RE_VERSION.match(version):
        fallo('La versión de forja.json no es válida: %r (usa p. ej. 1.6.0)' % version)

    poner_version_en_addon_xml(version)
    huella = cargar_huella()
    contenido = huella.huella_arbol(str(RAIZ / CARPETA))
    nombre_zip = '%s-%s.zip' % (ID_ADDON, version)
    ruta_zip = RAIZ / nombre_zip

    ya_publicado = (
        ruta_zip.exists()
        and 'zip' not in datos
        and datos.get('contenido_sha256') == contenido
        and datos.get('sha256') == sha256_archivo(ruta_zip)
    )
    if ya_publicado:
        print('Sin cambios en el contenido: se mantiene %s' % nombre_zip)
    else:
        for viejo in RAIZ.glob(ID_ADDON + '-*.zip'):
            if viejo.name != nombre_zip:
                viejo.unlink()
                print('Borrado %s' % viejo.name)
        construir_zip(huella, ruta_zip)
        sha = sha256_archivo(ruta_zip)
        resto = {k: v for k, v in datos.items()
                 if k not in ('version', 'zip', 'sha256', 'contenido_sha256')}
        nuevo = {'version': version, 'sha256': sha, 'contenido_sha256': contenido}
        nuevo.update(resto)
        ruta_json.write_bytes((json.dumps(nuevo, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        print('Creado %s (sha256 %s)' % (nombre_zip, sha))
        print('Huella del contenido: %s' % contenido)

    if actualizar_html(nombre_zip):
        print('index.html -> %s' % nombre_zip)

    salida = os.environ.get('GITHUB_OUTPUT')
    if salida:
        with open(salida, 'a', encoding='utf-8') as f:
            f.write('version=%s\n' % version)


if __name__ == '__main__':
    main()
