import html
import os
import re
import time

from . import const, red
from .util import escribir_json, leer_json, log, sin_acentos

URL_TOPS = 'https://mundokodi.com/tops/'
ARCHIVO = os.path.join(const.PERFIL, 'top_mundokodi.json')
VIGENCIA = 12 * 3600
LIMITE = 2 * 1024 * 1024
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
         'noviembre', 'diciembre']

_RX_ENTRADA = re.compile(r'<h2[^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RX_BLOQUE = re.compile(r'<(h3|p)\b[^>]*>(.*?)</\1>', re.S | re.I)
_RX_RANGO = re.compile(r'^\s*(\d{1,3})\s*[.\-):]*\s*(.+?)\s*$', re.S)
_RX_ENLACE = re.compile(r'href="(https?://[^"]+)"')


def _texto(fragmento):
    fragmento = re.sub(r'<!--.*?-->', '', fragmento, flags=re.S)
    fragmento = re.sub(r'<[^>]+>', '', fragmento)
    return re.sub(r'\s+', ' ', html.unescape(fragmento)).strip()


def ultimo_top(pagina):
    mejor = None
    for url, titulo in _RX_ENTRADA.findall(pagina):
        titulo = _texto(titulo)
        bajo = sin_acentos(titulo)
        if 'addons' not in bajo:
            continue
        mes = next((i for i, m in enumerate(MESES, 1) if re.search(r'\b%s\b' % m, bajo)), 0)
        anio = re.search(r'\b(20\d\d)\b', bajo)
        if not mes or not anio:
            continue
        clave = (int(anio.group(1)), mes)
        if mejor is None or clave > mejor[0]:
            mejor = (clave, url, titulo)
    if mejor is None:
        return None
    (anio, mes), url, titulo = mejor
    return {'url': url, 'titulo': titulo, 'anio': anio, 'mes': mes}


def parsear_top(pagina):
    items = []
    actual = None
    for etiqueta, interior in _RX_BLOQUE.findall(pagina):
        if etiqueta.lower() == 'h3':
            m = _RX_RANGO.match(_texto(interior))
            if m:
                enlace = _RX_ENLACE.search(interior)
                actual = {'pos': int(m.group(1)), 'nombre': m.group(2),
                          'web': enlace.group(1) if enlace else '', 'descripcion': ''}
                items.append(actual)
            elif actual is not None:
                break
        elif actual is not None:
            texto = _texto(interior)
            if texto:
                actual['descripcion'] = (actual['descripcion'] + ' ' + texto).strip()
    return items


def periodo(top):
    if not top:
        return ''
    return '%s %d' % (MESES[top['mes'] - 1].capitalize(), top['anio'])


def cargar_cache():
    datos = leer_json(ARCHIVO, None)
    if isinstance(datos, dict) and datos.get('items') and datos.get('mes') in range(1, 13):
        return datos
    return None


def vigente(top):
    return bool(top) and time.time() - top.get('obtenido', 0) < VIGENCIA


def descargar():
    pagina, _, _ = red.get_texto(URL_TOPS, limite=LIMITE, timeout=12)
    ref = ultimo_top(pagina)
    if not ref:
        raise red.ErrorRed('No se encontró el último Top en %s' % URL_TOPS)
    articulo, _, _ = red.get_texto(ref['url'], limite=LIMITE, timeout=12)
    items = parsear_top(articulo)
    if len(items) < 3:
        raise red.ErrorRed('No se pudo leer el Top de %s' % ref['url'])
    ref.update({'obtenido': int(time.time()), 'items': items})
    escribir_json(ARCHIVO, ref)
    return ref


def actualizar(actual, forzar=False):
    if not forzar and vigente(actual):
        return actual, False
    try:
        nuevo = descargar()
    except Exception as e:
        log('Top de Mundo Kodi no disponible: %s' % e)
        if actual:
            actual = dict(actual, obtenido=int(time.time()) - VIGENCIA + 1800)
        return actual, False
    cambio = not actual or {k: v for k, v in nuevo.items() if k != 'obtenido'} != \
        {k: v for k, v in actual.items() if k != 'obtenido'}
    return nuevo, cambio


def _clave(txt):
    return re.sub(r'[^a-z0-9]', '', sin_acentos(txt))


def _coincide(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    corto, largo = sorted((a, b), key=len)
    return len(corto) >= 4 and largo.startswith(corto) and largo[len(corto):].isdigit()


def emparejar(top, entradas):
    if not top:
        return []
    claves = [(e, {_clave(e.nombre), _clave(e.id.split('.')[-1])}) for e in entradas]
    pares, usados = [], set()
    for item in sorted(top['items'], key=lambda i: i['pos']):
        objetivo = _clave(item['nombre'])
        for e, ks in claves:
            if e.id not in usados and any(_coincide(objetivo, k) for k in ks):
                usados.add(e.id)
                pares.append((item, e))
                break
    return pares
