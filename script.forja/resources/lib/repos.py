import gzip
import hashlib
import io
import os
import re
import xml.etree.ElementTree as ET

from . import red, sistema
from .util import T, log, version_kodi, version_mayor

TAM_MAX_INDICE = 12 * 1024 * 1024
TAM_MAX_DESCOMPRIMIDO = 80 * 1024 * 1024


def _aplica(directorio, kodi):
    minimo = directorio.get('minversion')
    maximo = directorio.get('maxversion')
    if minimo and version_mayor(minimo, kodi):
        return False
    if maximo and version_mayor(kodi, maximo):
        return False
    return True


def indices_de_raiz(raiz):
    kodi = '%d.0.0' % version_kodi()
    urls = []
    for ext in raiz.findall('extension'):
        if ext.get('point') != 'xbmc.addon.repository':
            continue
        for d in ext.findall('dir'):
            info = d.find('info')
            if info is None or not (info.text or '').strip() or not _aplica(d, kodi):
                continue
            chk = d.find('checksum')
            urls.append(((info.text or '').strip(), (info.get('compressed') or '').lower() == 'true',
                         ((chk.text or '').strip() if chk is not None else '')))
    return urls


def _indices(repo_id):
    det = sistema.detalles(repo_id)
    if not det or not det.get('path'):
        return []
    try:
        raiz = ET.parse(os.path.join(det['path'], 'addon.xml')).getroot()
    except (OSError, ET.ParseError):
        return []
    return indices_de_raiz(raiz)


def indices_inseguros(repo_id):
    return [t[0] for t in _indices(repo_id) if t[0].lower().startswith('http://')]


_RX_CHECKSUM = re.compile(r'\s*([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})(?:\s|$)')
_ALGORITMOS = {32: 'md5', 40: 'sha1', 64: 'sha256'}


def _resumen(alg, datos):
    try:
        h = hashlib.new(alg, usedforsecurity=False)
    except TypeError:
        h = hashlib.new(alg)
    h.update(datos)
    return h.hexdigest()


def _verificar_checksum(bruto, datos, url_checksum):
    try:
        txt, _, _ = red.get_bytes(url_checksum, limite=4096, timeout=10)
    except Exception as e:
        log('Checksum %s no disponible; se omite: %s' % (url_checksum, e))
        return
    m = _RX_CHECKSUM.match((txt or b'').decode('utf-8', 'replace'))
    if not m:
        log('Checksum %s ilegible; se omite.' % url_checksum)
        return
    esperado = m.group(1).lower()
    alg = _ALGORITMOS[len(esperado)]
    for blob in (bruto, datos):
        if _resumen(alg, blob) == esperado:
            return
    raise red.ErrorRed(T('err_checksum_indice'))


def leer_indice(url, comprimido=False, url_checksum='', timeout=15):
    bruto, _, _ = red.get_bytes(url, limite=TAM_MAX_INDICE, timeout=timeout)
    if bruto is None:
        raise red.ErrorRed('Sin contenido')
    datos = bruto
    if comprimido or url.lower().endswith('.gz') or bruto[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(bruto)) as g:
            datos = g.read(TAM_MAX_DESCOMPRIMIDO + 1)
        if len(datos) > TAM_MAX_DESCOMPRIMIDO:
            raise red.ErrorRed('Índice demasiado grande')
    if url_checksum:
        _verificar_checksum(bruto, datos, url_checksum)
    return datos


def versiones(repo_id):
    out = {}
    for url, comprimido, chk in _indices(repo_id):
        try:
            indice = ET.fromstring(leer_indice(url, comprimido, chk))
        except Exception as e:
            log('Índice de %s no disponible (%s): %s' % (repo_id, url, e))
            continue
        for a in indice.findall('addon'):
            aid, ver = a.get('id'), a.get('version', '')
            if aid and (aid not in out or version_mayor(ver, out[aid])):
                out[aid] = ver
    return out
