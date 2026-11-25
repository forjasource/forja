import json
import re
import xml.etree.ElementTree as ET

from . import const
from .util import sin_acentos, slug, version_mayor

RE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,120}$')
RE_SHA = re.compile(r'^[0-9a-fA-F]{64}$')


class ErrorCatalogo(Exception):
    pass


ALIAS = {
    'id': ('id', 'addonid', 'addon_id'),
    'nombre': ('nombre', 'name', 'titulo', 'title'),
    'descripcion': ('descripcion', 'description', 'desc', 'resumen', 'summary'),
    'categoria': ('categoria', 'category', 'cat', 'grupo'),
    'tipo': ('tipo', 'type'),
    'zip': ('zip', 'url', 'download', 'descarga', 'enlace'),
    'sha256': ('sha256', 'hash'),
    'version': ('version', 'ver'),
    'autor': ('autor', 'author', 'provider', 'provider-name'),
    'icono': ('icono', 'icon', 'thumb'),
    'fanart': ('fanart', 'fondo'),
    'etiquetas': ('etiquetas', 'tags'),
    'repositorio': ('repositorio', 'repository', 'repo'),
    'requiere_kodi': ('requiere_kodi', 'kodi_min'),
    'web': ('web', 'website', 'homepage'),
    'addon_xml': ('addon_xml', 'addonxml', 'xml'),
}

ICONOS_CATEGORIA = {
    'video': 'DefaultAddonVideo.png', 'musica': 'DefaultAddonMusic.png',
    'audio': 'DefaultAddonMusic.png', 'imagenes': 'DefaultAddonPicture.png',
    'juegos': 'DefaultAddonGame.png', 'programas': 'DefaultAddonProgram.png',
    'scripts': 'DefaultAddonService.png', 'servicios': 'DefaultAddonService.png',
    'skins': 'DefaultAddonSkin.png', 'repositorios': 'DefaultAddonRepository.png',
    'idiomas': 'DefaultAddonLanguage.png', 'tv': 'DefaultAddonPVRClient.png',
    'visualizaciones': 'DefaultAddonVisualization.png',
    'salvapantallas': 'DefaultAddonScreensaver.png', 'tiempo': 'DefaultAddonWeather.png',
    'dependencias': 'DefaultAddonLibrary.png', 'scrapers': 'DefaultAddonInfoProvider.png',
    'subtitulos': 'DefaultAddonSubtitles.png',
}
ICONO_DEFECTO = 'DefaultAddon.png'


def _tomar(d, campo, defecto=None):
    for k in ALIAS[campo]:
        if k in d and d[k] not in (None, ''):
            return d[k]
    return defecto


def _texto(v, maximo=2000):
    return str(v).strip()[:maximo] if v is not None else ''


class Entrada:
    __slots__ = ('id', 'nombre', 'descripcion', 'categoria', 'tipo', 'zip', 'sha256',
                 'version', 'autor', 'icono', 'fanart', 'etiquetas', 'repositorio',
                 'requiere_kodi', 'web', 'addon_xml', 'lista_id', 'lista_nombre', '_busqueda')

    def __init__(self):
        for s in self.__slots__:
            setattr(self, s, None)
        self.etiquetas = []
        self._busqueda = None

    def a_dict(self):
        d = {'id': self.id, 'nombre': self.nombre, 'categoria': self.categoria, 'tipo': self.tipo}
        for k in ('descripcion', 'zip', 'sha256', 'version', 'autor', 'icono', 'fanart',
                  'repositorio', 'requiere_kodi', 'web', 'addon_xml'):
            v = getattr(self, k)
            if v:
                d[k] = v
        if self.etiquetas:
            d['etiquetas'] = list(self.etiquetas)
        return d

    @property
    def texto_busqueda(self):
        if self._busqueda is None:
            self._busqueda = sin_acentos(' '.join(
                [self.nombre or '', self.id or '', self.descripcion or '', self.autor or '',
                 ' '.join(self.etiquetas)]))
        return self._busqueda


class Lista:

    def __init__(self):
        self.id = ''
        self.nombre = ''
        self.descripcion = ''
        self.autor = ''
        self.version = ''
        self.actualizado = ''
        self.url_actualizacion = ''
        self.categorias = []
        self.entradas = []
        self.packs = []
        self.avisos = []

    def por_id(self, addon_id):
        for e in self.entradas:
            if e.id == addon_id:
                return e
        return None

    def nombre_categoria(self, cat_id):
        for c in self.categorias:
            if c['id'] == cat_id:
                return c['nombre']
        return cat_id or ''

    def icono_categoria(self, cat_id):
        for c in self.categorias:
            if c['id'] == cat_id:
                return c.get('icono') or ICONOS_CATEGORIA.get(cat_id, ICONO_DEFECTO)
        return ICONOS_CATEGORIA.get(cat_id, ICONO_DEFECTO)

    def buscar(self, texto, entradas=None):
        fichas = [t for t in sin_acentos(texto).split() if t]
        base = self.entradas if entradas is None else entradas
        if not fichas:
            return list(base)
        return [e for e in base if all(t in e.texto_busqueda for t in fichas)]

    def a_dict(self):
        d = {'esquema': const.ESQUEMA, 'id': self.id, 'nombre': self.nombre}
        for k in ('descripcion', 'autor', 'version', 'actualizado', 'url_actualizacion'):
            v = getattr(self, k)
            if v:
                d[k] = v
        d['categorias'] = [dict(c) for c in self.categorias]
        d['addons'] = [e.a_dict() for e in self.entradas]
        if self.packs:
            d['packs'] = [dict(p) for p in self.packs]
        return d

    @classmethod
    def desde_json(cls, texto, id_forzado=None, nombre_defecto=None):
        try:
            datos = json.loads(texto)
        except ValueError as e:
            raise ErrorCatalogo('JSON no válido: %s' % e)
        return cls.desde_dict(datos, id_forzado, nombre_defecto)

    @classmethod
    def desde_dict(cls, datos, id_forzado=None, nombre_defecto=None):
        lista = cls()
        avisos = lista.avisos

        if isinstance(datos, list):
            datos = {'addons': datos}
        if not isinstance(datos, dict):
            raise ErrorCatalogo('El archivo no contiene un catálogo.')
        crudos = None
        for k in ('addons', 'complementos', 'items'):
            if isinstance(datos.get(k), list):
                crudos = datos[k]
                break
        if crudos is None:
            raise ErrorCatalogo('No se encuentra la lista «addons» en el JSON.')
        esquema = datos.get('esquema', 1)
        if isinstance(esquema, int) and esquema > const.ESQUEMA:
            avisos.append('El catálogo usa un esquema más nuevo (%s); algunos campos se ignorarán.' % esquema)

        lista.nombre = _texto(datos.get('nombre') or datos.get('name') or nombre_defecto or 'Lista sin nombre', 80)
        lista.id = id_forzado or slug(_texto(datos.get('id')) or lista.nombre)
        lista.descripcion = _texto(datos.get('descripcion') or datos.get('description'))
        lista.autor = _texto(datos.get('autor') or datos.get('author'), 80)
        lista.version = _texto(datos.get('version'), 30)
        lista.actualizado = _texto(datos.get('actualizado') or datos.get('updated'), 30)
        lista.url_actualizacion = _texto(datos.get('url_actualizacion') or datos.get('update_url'), 500)

        cats = datos.get('categorias') or datos.get('categories') or []
        if isinstance(cats, dict):
            cats = [{'id': k, 'nombre': v} if isinstance(v, str) else dict(v, id=k) for k, v in cats.items()]
        por_clave = {}
        for c in cats:
            if isinstance(c, str):
                c = {'nombre': c}
            if not isinstance(c, dict):
                continue
            nombre = _texto(c.get('nombre') or c.get('name') or c.get('id'), 40)
            if not nombre:
                continue
            cid = slug(_texto(c.get('id')) or nombre, 'otros')
            if cid in por_clave:
                continue
            reg = {'id': cid, 'nombre': nombre,
                   'icono': _texto(c.get('icono') or c.get('icon')) or ICONOS_CATEGORIA.get(cid, ICONO_DEFECTO)}
            por_clave[cid] = reg
            por_clave[sin_acentos(nombre)] = reg
            lista.categorias.append(reg)

        def resolver_categoria(valor):
            if not valor:
                return 'otros'
            valor = _texto(valor, 40)
            reg = por_clave.get(slug(valor)) or por_clave.get(sin_acentos(valor))
            if reg is None:
                cid = slug(valor, 'otros')
                reg = {'id': cid, 'nombre': valor if valor != cid else valor.capitalize(),
                       'icono': ICONOS_CATEGORIA.get(cid, ICONO_DEFECTO)}
                por_clave[cid] = reg
                por_clave[sin_acentos(valor)] = reg
                lista.categorias.append(reg)
            return reg['id']

        vistos = set()
        for i, d in enumerate(crudos, 1):
            if isinstance(d, str):
                d = {'id': d}
            if not isinstance(d, dict):
                avisos.append('Elemento %d ignorado: no es un objeto.' % i)
                continue
            e = Entrada()
            e.id = _texto(_tomar(d, 'id'), 120)
            if not RE_ID.match(e.id or ''):
                avisos.append('Elemento %d ignorado: id «%s» no válido.' % (i, e.id))
                continue
            if e.id in vistos:
                avisos.append('«%s» está repetido; se usa la primera aparición.' % e.id)
                continue
            vistos.add(e.id)
            e.nombre = _texto(_tomar(d, 'nombre', e.id), 80)
            e.descripcion = _texto(_tomar(d, 'descripcion', ''))
            e.categoria = resolver_categoria(_tomar(d, 'categoria'))
            e.version = _texto(_tomar(d, 'version', ''), 30)
            e.autor = _texto(_tomar(d, 'autor', ''), 80)
            e.icono = _texto(_tomar(d, 'icono', ''), 500)
            e.fanart = _texto(_tomar(d, 'fanart', ''), 500)
            e.web = _texto(_tomar(d, 'web', ''), 500)
            e.addon_xml = _texto(_tomar(d, 'addon_xml', ''), 500)
            e.requiere_kodi = _texto(_tomar(d, 'requiere_kodi', ''), 10)
            e.zip = _texto(_tomar(d, 'zip', ''), 600)
            sha = _texto(_tomar(d, 'sha256', ''), 80)
            if sha and not RE_SHA.match(sha):
                avisos.append('«%s»: la huella SHA-256 no es válida y se ignora.' % e.id)
                sha = ''
            e.sha256 = sha.lower()
            tipo = sin_acentos(_texto(_tomar(d, 'tipo', ''), 20))
            tipo = {'oficial': 'kodi', 'repo': 'kodi', 'repositorio': 'kodi', 'alfa': 'kodi', 'directo': 'zip'}.get(tipo, tipo)
            if tipo not in ('kodi', 'zip'):
                tipo = 'zip' if e.zip else 'kodi'
            if tipo == 'zip' and not e.zip:
                avisos.append('«%s»: es de tipo zip pero no tiene URL; se ignora.' % e.id)
                continue
            e.tipo = tipo
            et = _tomar(d, 'etiquetas', [])
            if isinstance(et, str):
                et = [x.strip() for x in et.split(',')]
            e.etiquetas = [_texto(x, 30) for x in et if _texto(x)][:12]
            rep = _tomar(d, 'repositorio')
            if isinstance(rep, str) and rep:
                rep = {'id': rep}
            if isinstance(rep, dict) and rep.get('id'):
                rep = {'id': _texto(rep['id'], 120), 'zip': _texto(rep.get('zip') or rep.get('url') or '', 600),
                       'sha256': _texto(rep.get('sha256') or '', 80).lower(),
                       'addon_xml': _texto(rep.get('addon_xml') or rep.get('xml') or '', 600)}
                e.repositorio = {k: v for k, v in rep.items() if v}
            else:
                e.repositorio = None
            lista.entradas.append(e)

        for i, p in enumerate(datos.get('packs') or [], 1):
            if not isinstance(p, dict):
                continue
            ids = [_texto(x, 120) for x in (p.get('addons') or []) if isinstance(x, str)]
            nombre = _texto(p.get('nombre') or p.get('name'), 60)
            if not nombre or not ids:
                avisos.append('Pack %d ignorado: sin nombre o sin addons.' % i)
                continue
            faltan = [x for x in ids if x not in vistos]
            if faltan:
                avisos.append('Pack «%s»: addons que no están en la lista: %s' % (nombre, ', '.join(faltan)))
            lista.packs.append({'id': slug(_texto(p.get('id')) or nombre, 'pack%d' % i), 'nombre': nombre,
                                'descripcion': _texto(p.get('descripcion') or p.get('description')),
                                'addons': [x for x in ids if x in vistos],
                                'icono': _texto(p.get('icono') or p.get('icon')) or 'DefaultAddonsInstalled.png'})
        lista.packs = [p for p in lista.packs if p['addons']]
        lista.categorias.sort(key=lambda c: sin_acentos(c['nombre']))
        return lista


def combinar(listas, id_=const.ID_TODAS, nombre='Todas las listas'):
    res = Lista()
    res.id, res.nombre = id_, nombre
    cats = {}
    vistos = set()
    for l in listas:
        for c in l.categorias:
            cats.setdefault(c['id'], dict(c))
        for e in l.entradas:
            if e.id in vistos:
                continue
            vistos.add(e.id)
            res.entradas.append(e)
        res.packs.extend(p for p in l.packs if p['id'] not in {q['id'] for q in res.packs})
    res.categorias = sorted(cats.values(), key=lambda c: sin_acentos(c['nombre']))
    return res


_CATEGORIA_POR_EXTENSION = (
    ('xbmc.addon.repository', 'repositorios'),
    ('xbmc.gui.skin', 'skins'),
    ('kodi.resource.language', 'idiomas'),
    ('xbmc.player.musicviz', 'visualizaciones'),
    ('kodi.visualization', 'visualizaciones'),
    ('xbmc.ui.screensaver', 'salvapantallas'),
    ('kodi.pvrclient', 'tv'),
    ('xbmc.metadata.scraper', 'scrapers'),
    ('xbmc.python.weather', 'tiempo'),
    ('xbmc.python.module', 'dependencias'),
    ('xbmc.python.library', 'dependencias'),
    ('xbmc.service', 'servicios'),
    ('xbmc.python.script', 'programas'),
    ('kodi.game.libretro', 'juegos'),
)


def desde_addons_xml(texto_xml, url_datadir, nombre='Repositorio importado'):
    try:
        raiz = ET.fromstring(texto_xml)
    except ET.ParseError as e:
        raise ErrorCatalogo('addons.xml no válido: %s' % e)
    nodos = [raiz] if raiz.tag == 'addon' else raiz.findall('addon')
    if not nodos:
        raise ErrorCatalogo('El addons.xml no contiene addons.')
    base = url_datadir.rstrip('/') + '/'
    mejores = {}
    for a in nodos:
        aid, ver = a.get('id'), a.get('version') or ''
        if not aid or not RE_ID.match(aid):
            continue
        previo = mejores.get(aid)
        if previo is not None and not version_mayor(ver, previo.get('version')):
            continue
        puntos = [x.get('point', '') for x in a.findall('extension')]
        cat = 'otros'
        for prefijo, c in _CATEGORIA_POR_EXTENSION:
            if any(p.startswith(prefijo) for p in puntos):
                cat = c
                break
        else:
            for ext in a.findall('extension'):
                if ext.get('point') == 'xbmc.python.pluginsource':
                    prov = (ext.findtext('provides') or '').split()
                    cat = {'video': 'video', 'audio': 'musica', 'image': 'imagenes', 'game': 'juegos',
                           'executable': 'programas'}.get(prov[0] if prov else '', 'programas')
        meta = next((x for x in a.findall('extension') if x.get('point') == 'xbmc.addon.metadata'), None)
        resumen = desc = ''
        icono = ''
        if meta is not None:
            def elegir(tag):
                cand = meta.findall(tag)
                for pref in ('es', 'en'):
                    for c in cand:
                        if (c.get('lang') or 'en').lower().startswith(pref):
                            return (c.text or '').strip()
                return (cand[0].text or '').strip() if cand else ''
            resumen, desc = elegir('summary'), elegir('description')
            ic = meta.findtext('assets/icon')
            if ic:
                icono = '%s%s/%s' % (base, aid, ic.lstrip('/'))
        mejores[aid] = {'id': aid, 'nombre': a.get('name') or aid, 'version': ver,
                        'autor': a.get('provider-name') or '', 'categoria': cat,
                        'descripcion': (desc or resumen)[:600], 'tipo': 'zip',
                        'zip': '%s%s/%s-%s.zip' % (base, aid, aid, ver), 'icono': icono}
    datos = {'nombre': nombre, 'descripcion': 'Importado de un addons.xml (%d addons).' % len(mejores),
             'addons': sorted(mejores.values(), key=lambda d: sin_acentos(d['nombre']))}
    return Lista.desde_dict(datos, nombre_defecto=nombre)
