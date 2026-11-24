import json
import os
import re
import tempfile
import time
import unicodedata

import xbmc
import xbmcaddon

from .textos import TEXTOS


def log(msg, nivel=xbmc.LOGINFO):
    xbmc.log('[Forja] %s' % msg, nivel)


def log_error(msg):
    log(msg, xbmc.LOGERROR)


def T(clave, **kw):
    txt = TEXTOS.get(clave)
    if txt is None:
        log('Texto sin definir: %s' % clave, xbmc.LOGWARNING)
        return clave
    try:
        return txt.format(**kw) if kw else txt
    except (KeyError, IndexError):
        return txt


def ajuste(nombre, defecto=None):
    try:
        valor = xbmcaddon.Addon().getSetting(nombre)
    except Exception:
        return defecto
    if valor == '' or valor is None:
        return defecto
    if isinstance(defecto, bool):
        return valor.lower() == 'true'
    if isinstance(defecto, int):
        try:
            return int(float(valor))
        except ValueError:
            return defecto
    return valor


def version_kodi():
    try:
        txt = xbmc.getInfoLabel('System.BuildVersion')
        m = re.match(r'(\d+)', txt)
        return int(m.group(1)) if m else 21
    except Exception:
        return 21


def asegurar_dir(ruta):
    if not os.path.isdir(ruta):
        os.makedirs(ruta)
    return ruta


def leer_json(ruta, defecto=None):
    try:
        with open(ruta, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribir_json(ruta, datos):
    asegurar_dir(os.path.dirname(ruta))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, ruta)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def borrar_arbol(ruta):
    import shutil
    shutil.rmtree(ruta, ignore_errors=True)


def ahora_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def sin_acentos(txt):
    txt = unicodedata.normalize('NFKD', txt or '')
    return ''.join(c for c in txt if not unicodedata.combining(c)).lower()


def slug(txt, defecto='lista'):
    s = re.sub(r'[^a-z0-9]+', '-', sin_acentos(txt)).strip('-')
    return s[:40] or defecto


def tam_legible(n):
    n = float(n or 0)
    for u in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or u == 'GB':
            return ('%d %s' % (n, u)) if u == 'B' else ('%.1f %s' % (n, u)).replace('.', ',')
        n /= 1024.0


def dominio(url):
    m = re.match(r'^[a-z][a-z0-9+.-]*://([^/:?#]+)', url or '', re.I)
    return m.group(1).lower() if m else (url or '')


_PRE = ('alpha', 'beta', 'rc', 'dev', 'pre', 'a', 'b')


def clave_version(v):
    out = []
    for tok in re.findall(r'\d+|[A-Za-z]+', str(v or '')):
        if tok.isdigit():
            out.append((1, int(tok), ''))
        elif tok.lower() in _PRE:
            out.append((0, 0, tok.lower()))
    while out and out[-1] == (1, 0, ''):
        out.pop()
    return out


def version_mayor(a, b):
    ka, kb = clave_version(a), clave_version(b)
    n = max(len(ka), len(kb))
    fin = (1, 0, '')
    ka += [fin] * (n - len(ka))
    kb += [fin] * (n - len(kb))
    return ka > kb
