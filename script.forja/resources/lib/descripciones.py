import gzip
import hashlib
import io
import os
import time
import xml.etree.ElementTree as ET
import zipfile

import xbmcvfs

from . import const, red, repos, sistema, versiones
from .util import escribir_json, leer_json, log, version_kodi, version_mayor

ARCHIVO_CACHE = os.path.join(const.DIR_CACHE, 'descripciones.json')
CADUCIDAD = 86400
REINTENTO_FALLO = 600
VIGENCIA_INDICE = 1800
TAM_MAX_ZIP = 40 * 1024 * 1024
TAM_MAX_INDICE = 12 * 1024 * 1024
TAM_MAX_DESCOMPRIMIDO = 80 * 1024 * 1024
TAM_MAX_ADDON_XML = 1024 * 1024
MAX_TEXTO = 3000
PUNTOS_METADATA = ('xbmc.addon.metadata', 'kodi.addon.metadata')


def _elegir(meta, etiqueta):
    cand = meta.findall(etiqueta)
    for pref in ('es', 'en'):
        for c in cand:
            if (c.get('lang') or 'en').lower().startswith(pref):
                t = (c.text or '').strip()
                if t:
                    return t
    for c in cand:
        t = (c.text or '').strip()
        if t:
            return t
    return ''


def texto_addon(nodo):
    for ext in nodo.findall('extension'):
        if ext.get('point') in PUNTOS_METADATA:
            return (_elegir(ext, 'description') or _elegir(ext, 'summary'))[:MAX_TEXTO]
    return ''


def datos_addon(nodo):
    req = []
    for imp in nodo.findall('requires/import'):
        did = imp.get('addon')
        if not did or did.startswith(('xbmc.', 'kodi.')):
            continue
        if (imp.get('optional') or 'false').lower() == 'true':
            continue
        req.append([did, imp.get('version') or ''])
    return {'t': texto_addon(nodo), 'r': req, 'v': nodo.get('version') or ''}


def _raiz_addon_xml_de_zip(datos):
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        nombres = {n.replace('\\', '/'): n for n in z.namelist()}
        validos = [n for n in nombres
                   if n.endswith('/addon.xml') and n.count('/') == 1 or n == 'addon.xml']
        if not validos:
            return None
        real = nombres[min(validos, key=len)]
        if z.getinfo(real).file_size > TAM_MAX_ADDON_XML:
            return None
        return ET.fromstring(z.read(real))


def _bajar_zip(url, sha256=''):
    datos, _, _ = red.get_bytes(url, limite=TAM_MAX_ZIP, timeout=25)
    if sha256 and hashlib.sha256(datos).hexdigest().lower() != sha256.lower():
        raise red.ErrorRed('SHA-256 no coincide')
    return datos


def _gunzip(datos):
    with gzip.GzipFile(fileobj=io.BytesIO(datos)) as g:
        res = g.read(TAM_MAX_DESCOMPRIMIDO + 1)
    if len(res) > TAM_MAX_DESCOMPRIMIDO:
        raise red.ErrorRed('Índice demasiado grande')
    return res


def _descripciones_de_indice(datos):
    out = {}
    for _, el in ET.iterparse(io.BytesIO(datos), events=('end',)):
        if el.tag != 'addon':
            continue
        aid, ver = el.get('id'), el.get('version') or ''
        if aid:
            previo = out.get(aid)
            if previo is None or version_mayor(ver, previo[0]):
                out[aid] = (ver, datos_addon(el))
        el.clear()
    return {k: v[1] for k, v in out.items()}


def _ruta_real(ruta):
    if ruta.startswith('special://'):
        return xbmcvfs.translatePath(ruta)
    return ruta


class Descripciones:

    def __init__(self):
        self._cache = leer_json(ARCHIVO_CACHE, {}) or {}
        self._memoria = {}
        self._fallos = {}
        self._indices = {}
        self._urls = {}

    def _local(self, info):
        ruta = _ruta_real((info or {}).get('path') or '')
        if not ruta:
            return None
        try:
            return datos_addon(ET.parse(os.path.join(ruta, 'addon.xml')).getroot())
        except (OSError, ET.ParseError):
            return None

    def _datos_rapido(self, e, info=None):
        if info:
            clave = (e.id, info.get('version', ''))
            if clave not in self._memoria:
                self._memoria[clave] = self._local(info)
            if self._memoria[clave] and self._memoria[clave]['t']:
                return self._memoria[clave]
        ficha = self._cache.get(e.id)
        if ficha and ficha.get('t') and ficha.get('v') == (e.version or '') \
                and time.time() - ficha.get('f', 0) < CADUCIDAD:
            return {'t': ficha['t'], 'r': ficha.get('r'), 'v': ficha.get('ver', '')}
        return None

    def version_cache(self, e):
        ficha = self._cache.get(e.id)
        if ficha and time.time() - ficha.get('f', 0) < CADUCIDAD:
            return ficha.get('ver', '')
        return ''

    def rapido(self, e, info=None):
        d = self._datos_rapido(e, info)
        return d['t'] if d else ''

    def _guardar(self, e, datos):
        self._cache[e.id] = {'v': e.version or '', 't': datos['t'], 'r': datos['r'], 'ver': datos.get('v', ''),
                            'f': time.time()}
        try:
            escribir_json(ARCHIVO_CACHE, self._cache)
        except Exception as exc:
            log('No se pudo guardar la caché de descripciones: %r' % exc)

    def resolver_datos(self, e, info=None, necesita_deps=False):
        datos = self._datos_rapido(e, info)
        if datos and (not necesita_deps or datos.get('r') is not None):
            return datos
        if time.time() - self._fallos.get(e.id, 0) < REINTENTO_FALLO:
            return datos
        try:
            nuevo = self._desde_zip(e) if e.tipo == 'zip' else self._desde_repositorio(e)
        except Exception as exc:
            log('Datos de %s no disponibles: %s' % (e.id, exc))
            nuevo = None
        if nuevo and nuevo['t']:
            self._guardar(e, nuevo)
            return nuevo
        if nuevo:
            return nuevo
        self._fallos[e.id] = time.time()
        return datos

    def resolver(self, e, info=None):
        d = self.resolver_datos(e, info)
        return d['t'] if d else ''

    def dependencias_pendientes(self, e, catalogo, instalados):
        pendientes, vistos = [], {e.id}

        def visitar(datos, prof):
            for did, minima in datos.get('r') or []:
                if did in vistos:
                    continue
                vistos.add(did)
                inst = instalados.get(did)
                if inst and not (minima and version_mayor(minima, inst.get('version', ''))):
                    continue
                entrada = catalogo.por_id(did) if catalogo else None
                pendientes.append((did, entrada.nombre if entrada else did))
                if prof < 4:
                    sub = self._datos_dependencia(did, entrada, e)
                    if sub:
                        visitar(sub, prof + 1)

        raiz = self.resolver_datos(e, instalados.get(e.id), necesita_deps=True)
        if raiz:
            visitar(raiz, 0)
        return pendientes

    def _datos_dependencia(self, did, entrada, padre):
        if entrada is not None:
            return self.resolver_datos(entrada, None, necesita_deps=True)
        urls = list(self.urls_indices(padre))
        if self._url_oficial() not in [u[0] for u in urls]:
            urls.append((self._url_oficial(), True, self._url_oficial() + '.md5'))
        for url, comprimido, chk in urls:
            try:
                mapa = self._indice(url, comprimido, chk)
            except Exception as exc:
                log('Índice %s no disponible: %s' % (url, exc))
                continue
            if did in mapa:
                return mapa[did]
        return None

    def _desde_zip(self, e):
        raiz = _raiz_addon_xml_de_zip(_bajar_zip(versiones.url_zip(e), e.sha256 or ''))
        return datos_addon(raiz) if raiz is not None else None

    @staticmethod
    def _url_oficial():
        rama = const.RAMAS_KODI.get(version_kodi(), 'omega')
        return 'https://mirrors.kodi.tv/addons/%s/addons.xml.gz' % rama

    def urls_indices(self, e):
        rep = e.repositorio or {}
        rid = rep.get('id')
        clave = rid or '__oficial__'
        if clave in self._urls:
            return self._urls[clave]
        urls = []
        if rid and sistema.esta_instalado(rid):
            urls = repos._indices(rid)
        if not urls and rep.get('zip'):
            raiz = _raiz_addon_xml_de_zip(_bajar_zip(versiones.url_repo(rep), rep.get('sha256') or ''))
            urls = repos.indices_de_raiz(raiz) if raiz is not None else []
        if not urls and not rid:
            urls = [(self._url_oficial(), True, self._url_oficial() + '.md5')]
        self._urls[clave] = urls
        return urls

    def _indice(self, url, comprimido, checksum=''):
        visto = self._indices.get(url)
        if visto and time.time() - visto[0] < VIGENCIA_INDICE:
            return visto[1]
        try:
            mapa = _descripciones_de_indice(repos.leer_indice(url, comprimido, checksum, timeout=20))
        except Exception:
            self._indices[url] = (time.time(), {})
            raise
        self._indices[url] = (time.time(), mapa)
        return mapa

    def _desde_repositorio(self, e):
        for url, comprimido, chk in self.urls_indices(e):
            try:
                mapa = self._indice(url, comprimido, chk)
            except Exception as exc:
                log('Índice %s no disponible: %s' % (url, exc))
                continue
            if e.id in mapa:
                return mapa[e.id]
        return None
