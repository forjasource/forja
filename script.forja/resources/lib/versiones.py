import json
import re
import time
import xml.etree.ElementTree as ET

from . import red
from .util import T, log, version_mayor

VIGENCIA = 1800
_CACHE = {}
_RX_URL = re.compile(r'[-_]v?(\d+(?:\.\d+)+(?:[-+~]?[A-Za-z0-9.]+)?)\.zip$', re.I)
_RX_RAW = re.compile(r'^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?([^/]+)/(.*)$')
_RX_GH_RAW = re.compile(r'^https://github\.com/([^/]+)/([^/]+)/raw/(?:refs/heads/)?([^/]+)/(.*)$')
_RX_GH_IO = re.compile(r'^https://([^/.]+)\.github\.io/(.*)$')
_VERSION = r'(\d+(?:\.\d+)*(?:[-+~][A-Za-z0-9.]+)?)'


def desde_url(url):
    m = _RX_URL.search((url or '').split('?')[0].split('#')[0])
    return m.group(1) if m else ''


def tiene_plantilla(e):
    return '{version}' in (getattr(e, 'zip', '') or '')


def _version_de_xml(datos, addon_id, estricto=False):
    raiz = ET.fromstring(datos)
    if raiz.tag == 'addon':
        if estricto and raiz.get('id') != addon_id:
            return ''
        return raiz.get('version') or ''
    mejor = ''
    for a in raiz.findall('addon'):
        v = a.get('version') or ''
        if a.get('id') == addon_id and v and (not mejor or version_mayor(v, mejor)):
            mejor = v
    return mejor


def _partes_plantilla(e):
    url = (e.zip or '').split('?')[0].split('#')[0]
    base, _, archivo = url.rpartition('/')
    if '{version}' not in archivo:
        return None
    prefijo, sufijo = archivo.split('{version}', 1)
    nombre = re.sub(r'[-_]v?$', '', prefijo, flags=re.I) or prefijo
    return base + '/', prefijo, sufijo, nombre


def _urls_xml_derivadas(e, partes):
    base, _, _, nombre = partes
    urls = []
    for i in ([e.id] if nombre == e.id else [e.id, nombre]):
        for u in (base + 'addon.xml', base + i + '/addon.xml', base + 'addons.xml'):
            if u not in urls:
                urls.append(u)
    return urls


def _origen_github(base):
    for rx in (_RX_RAW, _RX_GH_RAW):
        m = rx.match(base)
        if m:
            return m.groups()
    m = _RX_GH_IO.match(base)
    if m:
        return m.group(1), m.group(1) + '.github.io', None, m.group(2)
    return None


def _mejor_version(nombres, prefijo, sufijo):
    rx = re.compile('^' + re.escape(prefijo) + _VERSION + re.escape(sufijo) + '$', re.I)
    mejor = ''
    for n in nombres:
        mm = rx.match(n or '')
        if mm and (not mejor or version_mayor(mm.group(1), mejor)):
            mejor = mm.group(1)
    return mejor


def _listado_api_github(dueno, repo, rama, ruta):
    api = 'https://api.github.com/repos/%s/%s/contents/%s' % (dueno, repo, ruta.strip('/'))
    if rama:
        api += '?ref=' + rama
    datos, _, _ = red.get_bytes(api, limite=2 * 1024 * 1024, timeout=10)
    return [it.get('name') for it in json.loads(datos.decode('utf-8')) if isinstance(it, dict)]


def _listado_jsdelivr(dueno, repo, rama, ruta):
    url = 'https://data.jsdelivr.com/v1/packages/gh/%s/%s@%s?structure=flat' % (dueno, repo, rama)
    datos, _, _ = red.get_bytes(url, limite=4 * 1024 * 1024, timeout=10)
    carpeta = ('/' + ruta.strip('/')).rstrip('/')
    nombres = []
    for f in json.loads(datos.decode('utf-8')).get('files') or []:
        dir_, _, nombre = (f.get('name') or '').rpartition('/')
        if dir_ == carpeta:
            nombres.append(nombre)
    return nombres


def _desde_listado_github(e, partes):
    base, prefijo, sufijo, _ = partes
    origen = _origen_github(base)
    if not origen:
        return ''
    fuentes = [_listado_api_github] + ([_listado_jsdelivr] if origen[2] else [])
    for fuente in fuentes:
        try:
            ver = _mejor_version(fuente(*origen), prefijo, sufijo)
        except red.ErrorSinConexion:
            raise
        except Exception as exc:
            log('Versión de %s: %s no disponible (%s)' % (e.id, fuente.__name__, exc))
            continue
        if ver:
            return ver
    return ''


def _detectar(e):
    partes = _partes_plantilla(e)
    if not partes:
        return ''
    ids = [e.id] if partes[3] == e.id else [e.id, partes[3]]
    dudosa = ''
    for url in _urls_xml_derivadas(e, partes):
        try:
            datos, _, _ = red.get_bytes(url, limite=4 * 1024 * 1024, timeout=10)
            ver = ''
            for i in ids:
                ver = _version_de_xml(datos, i, estricto=True)
                if ver:
                    break
            if not ver:
                continue
            if red.existe(e.zip.replace('{version}', ver)):
                return ver
            dudosa = dudosa or ver
            log('Versión de %s: %s indica %s pero ese zip no existe' % (e.id, url, ver))
        except red.ErrorSinConexion:
            raise
        except Exception as exc:
            log('Versión de %s: %s no sirve (%s)' % (e.id, url, exc))
    ver = _desde_listado_github(e, partes)
    return ver or dudosa


def remota(e, forzar=False):
    xml = getattr(e, 'addon_xml', '')
    if not xml and not tiene_plantilla(e):
        return ''
    c = _CACHE.get(e.id)
    if c and not forzar and time.time() - c[0] < VIGENCIA:
        return c[1]
    ver = ''
    try:
        if xml:
            datos, _, _ = red.get_bytes(xml, limite=4 * 1024 * 1024, timeout=10)
            ver = _version_de_xml(datos, e.id)
        else:
            ver = _detectar(e)
    except Exception as exc:
        log('Versión de %s no disponible (%s): %s' % (e.id, xml or e.zip, exc))
        if c:
            ver = c[1]
    _CACHE[e.id] = (time.time(), ver)
    return ver


def cache_remota(e):
    c = _CACHE.get(e.id)
    return c[1] if c else ''


class _Origen:
    version = ''

    def __init__(self, id_, zip_, addon_xml):
        self.id, self.zip, self.addon_xml = id_, zip_, addon_xml


def url_repo(rep):
    return url_zip(_Origen(rep.get('id', ''), rep.get('zip', ''), rep.get('addon_xml', '')))


def version_conocida(e, detectada=''):
    c = _CACHE.get(e.id)
    if c and c[1]:
        return c[1]
    plantilla = '{version}' in (e.zip or '')
    return ((desde_url(e.zip) if not plantilla else '') or detectada or e.version or '')


def url_zip(e):
    url = e.zip or ''
    if '{version}' not in url:
        return url
    ver = remota(e)
    if not ver:
        raise red.ErrorRed(T('err_sin_version'))
    return url.replace('{version}', ver)
