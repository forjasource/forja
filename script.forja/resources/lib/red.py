import hashlib
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request

import xbmcvfs

from . import const
from .util import T, ajuste, asegurar_dir, log


class ErrorRed(Exception):
    pass


class ErrorSinConexion(ErrorRed):
    pass


class Cancelado(Exception):
    pass


def normalizar_url(url):
    url = (url or '').strip()
    m = re.match(r'^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$', url)
    if m:
        return 'https://raw.githubusercontent.com/%s/%s/%s' % m.groups()
    m = re.match(r'^https?://gist\.github\.com/([^/]+)/([0-9a-f]+)/?$', url)
    if m:
        return 'https://gist.githubusercontent.com/%s/%s/raw' % m.groups()
    return url


def validar_url(url):
    url = (url or '').strip()
    bajo = url.lower()
    if not (bajo.startswith('https://') or bajo.startswith('http://')):
        raise ErrorRed(T('err_url_invalida'))
    return url


def _abrir(peticion, timeout):
    try:
        return urllib.request.urlopen(peticion, timeout=timeout)
    except (urllib.error.URLError, ssl.SSLError) as e:
        motivo = getattr(e, 'reason', e)
        if not isinstance(motivo, ssl.SSLCertVerificationError):
            raise
        cert = xbmcvfs.translatePath('special://xbmc/system/certs/cacert.pem')
        if not os.path.isfile(cert):
            raise
        log('Certificados del sistema no válidos; se usa el paquete de Kodi')
        return urllib.request.urlopen(peticion, timeout=timeout, context=ssl.create_default_context(cafile=cert))


def _timeout(forzado=None):
    return forzado or ajuste('tiempo_espera', 20)


def _peticion(url, cabeceras=None):
    cab = {'User-Agent': const.USER_AGENT, 'Accept-Encoding': 'identity'}
    cab.update(cabeceras or {})
    return urllib.request.Request(url, headers=cab)


def _traducir(exc, url):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return ErrorRed(T('err_http_404'))
        return ErrorRed(T('err_http_codigo', codigo=exc.code))
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return ErrorSinConexion(T('err_timeout'))
    if isinstance(exc, urllib.error.URLError):
        return ErrorSinConexion(T('err_conexion', motivo=str(getattr(exc, 'reason', exc))[:120]))
    return ErrorRed(str(exc)[:160])


def get_bytes(url, limite=const.TAM_MAX_LISTA, etag=None, modificado=None, timeout=None):
    url = validar_url(normalizar_url(url))
    cab = {}
    if etag:
        cab['If-None-Match'] = etag
    if modificado:
        cab['If-Modified-Since'] = modificado
    try:
        with _abrir(_peticion(url, cab), _timeout(timeout)) as r:
            datos = r.read(limite + 1)
            if len(datos) > limite:
                raise ErrorRed(T('err_demasiado_grande'))
            return datos, r.headers.get('ETag'), r.headers.get('Last-Modified')
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag, modificado
        raise _traducir(e, url)
    except ErrorRed:
        raise
    except Exception as e:
        raise _traducir(e, url)


_HUELLAS = {}
_RX_SHA256 = re.compile(r'^\s*([0-9a-fA-F]{64})(?:\s|$)')
_RX_MD5 = re.compile(r'^\s*([0-9a-fA-F]{32})(?:\s|$)')


def huella_remota(url):
    url = normalizar_url(url)
    if url in _HUELLAS:
        return _HUELLAS[url]
    base = url.split('?')[0].split('#')[0]
    res = (None, '')
    for sufijo, tipo, rx in (('.sha256', 'sha256', _RX_SHA256), ('.sha256sum', 'sha256', _RX_SHA256),
                             ('.md5', 'md5', _RX_MD5)):
        try:
            datos, _, _ = get_bytes(base + sufijo, limite=2048, timeout=8)
        except Exception:
            continue
        m = rx.match(datos.decode('utf-8', 'replace')) if datos else None
        if m:
            res = (tipo, m.group(1).lower())
            break
    _HUELLAS[url] = res
    return res


def existe(url, timeout=10):
    url = validar_url(normalizar_url(url))
    try:
        with _abrir(_peticion(url, {'Range': 'bytes=0-0'}), _timeout(timeout)):
            return True
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except Exception as e:
        raise _traducir(e, url)


def get_texto(url, **kw):
    datos, etag, mod = get_bytes(url, **kw)
    return (datos.decode('utf-8-sig', 'replace') if datos is not None else None), etag, mod


def descargar(url, destino, sha256=None, progreso=None, cancelado=None, md5=None):
    url = validar_url(normalizar_url(url))
    asegurar_dir(os.path.dirname(destino))
    parcial = destino + '.part'
    h = hashlib.sha256()
    hm = _nuevo_md5() if md5 else None
    hecho = 0
    t0 = time.time()
    try:
        with _abrir(_peticion(url), _timeout()) as r, open(parcial, 'wb') as f:
            total = int(r.headers.get('Content-Length') or 0)
            if total and total > const.TAM_MAX_ZIP:
                raise ErrorRed(T('err_demasiado_grande'))
            while True:
                if cancelado and cancelado():
                    raise Cancelado()
                trozo = r.read(64 * 1024)
                if not trozo:
                    break
                f.write(trozo)
                h.update(trozo)
                if hm is not None:
                    hm.update(trozo)
                hecho += len(trozo)
                if hecho > const.TAM_MAX_ZIP:
                    raise ErrorRed(T('err_demasiado_grande'))
                if progreso:
                    progreso(hecho, total, hecho / max(time.time() - t0, 0.001))
    except (Cancelado, ErrorRed):
        _quitar(parcial)
        raise
    except Exception as e:
        _quitar(parcial)
        raise _traducir(e, url)

    real = h.hexdigest()
    if sha256 and real.lower() != sha256.lower():
        _quitar(parcial)
        log('SHA-256 no coincide: esperado %s, obtenido %s' % (sha256, real))
        raise ErrorRed(T('err_sha256'))
    if md5 and hm is not None and hm.hexdigest().lower() != md5.lower():
        _quitar(parcial)
        log('MD5 no coincide: esperado %s, obtenido %s' % (md5, hm.hexdigest()))
        raise ErrorRed(T('err_sha256'))
    os.replace(parcial, destino)
    log('Descargado %s (SHA-256 %s)' % (url, real))
    return real


def _nuevo_md5():
    try:
        return hashlib.md5(usedforsecurity=False)
    except TypeError:
        return hashlib.md5()


def _quitar(ruta):
    try:
        os.remove(ruta)
    except OSError:
        pass
