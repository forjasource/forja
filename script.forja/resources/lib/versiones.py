import re
import time
import xml.etree.ElementTree as ET

from . import red
from .util import T, log, version_mayor

VIGENCIA = 1800
_CACHE = {}
_RX_URL = re.compile(r'[-_]v?(\d+(?:\.\d+)+(?:[-+~]?[A-Za-z0-9.]+)?)\.zip$', re.I)


def desde_url(url):
    m = _RX_URL.search((url or '').split('?')[0].split('#')[0])
    return m.group(1) if m else ''


def _version_de_xml(datos, addon_id):
    raiz = ET.fromstring(datos)
    if raiz.tag == 'addon':
        return raiz.get('version') or ''
    mejor = ''
    for a in raiz.findall('addon'):
        v = a.get('version') or ''
        if a.get('id') == addon_id and v and (not mejor or version_mayor(v, mejor)):
            mejor = v
    return mejor


def remota(e, forzar=False):
    if not getattr(e, 'addon_xml', ''):
        return ''
    c = _CACHE.get(e.id)
    if c and not forzar and time.time() - c[0] < VIGENCIA:
        return c[1]
    ver = ''
    try:
        datos, _, _ = red.get_bytes(e.addon_xml, limite=4 * 1024 * 1024, timeout=10)
        ver = _version_de_xml(datos, e.id)
    except Exception as exc:
        log('Versión de %s no disponible (%s): %s' % (e.id, e.addon_xml, exc))
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
