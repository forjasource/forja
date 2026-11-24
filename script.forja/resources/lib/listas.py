import copy
import os

from . import catalogo, const, red
from .catalogo import ErrorCatalogo, Lista
from .util import (ahora_iso, ajuste, asegurar_dir, borrar_arbol, dominio, escribir_json, leer_json,
                   log, slug, version_mayor)


class GestorListas:
    def __init__(self):
        asegurar_dir(const.DIR_LISTAS)
        self.estado = leer_json(const.ARCHIVO_ESTADO, {}) or {}
        self._cache = {}
        self._normalizar_estado()

    def _normalizar_estado(self):
        e = self.estado
        e.setdefault('version', 1)
        e.setdefault('listas', {})
        e.setdefault('orden', [])
        e.setdefault('activa', const.ID_DEFECTO)
        for lid in list(e['listas']):
            if lid != const.ID_DEFECTO and not os.path.exists(self._ruta(lid)):
                e['listas'].pop(lid)
        e['orden'] = [x for x in e['orden'] if x in e['listas']]
        self._asegurar_defecto()
        for lid in e['listas']:
            if lid not in e['orden']:
                e['orden'].append(lid)
        if e['activa'] != const.ID_TODAS and e['activa'] not in e['listas']:
            e['activa'] = const.ID_DEFECTO
        self.guardar_estado()

    def guardar_estado(self):
        escribir_json(const.ARCHIVO_ESTADO, self.estado)

    def deps_registradas(self, addon_id):
        return list((self.estado.get('deps') or {}).get(addon_id, []))

    def registrar_deps(self, addon_id, ids):
        if not ids:
            return
        actuales = self.estado.setdefault('deps', {}).setdefault(addon_id, [])
        for d in ids:
            if d not in actuales:
                actuales.append(d)
        self.guardar_estado()

    def olvidar_deps(self, addon_id):
        if (self.estado.get('deps') or {}).pop(addon_id, None) is not None:
            self.guardar_estado()

    def _ruta(self, lid):
        return os.path.join(const.DIR_LISTAS, '%s.json' % lid)

    def _meta(self, lid):
        return self.estado['listas'].get(lid)

    def _asegurar_defecto(self):
        with open(const.ARCHIVO_DEFECTO, 'r', encoding='utf-8') as f:
            empaquetada = Lista.desde_json(f.read(), id_forzado=const.ID_DEFECTO)
        meta = self.estado['listas'].get(const.ID_DEFECTO)
        ruta = self._ruta(const.ID_DEFECTO)
        escribir = meta is None or not os.path.exists(ruta)
        if not escribir and meta.get('origen', {}).get('tipo') == 'empaquetada' \
                and not meta.get('etag') and not meta.get('modificado'):
            actual = leer_json(ruta, {}) or {}
            if version_mayor(empaquetada.version, actual.get('version', '0')):
                escribir = True
        if escribir:
            escribir_json(ruta, empaquetada.a_dict())
            self.estado['listas'][const.ID_DEFECTO] = {
                'nombre': empaquetada.nombre, 'origen': {'tipo': 'empaquetada'}, 'solo_lectura': True,
                'total': len(empaquetada.entradas), 'actualizada': '', 'etag': '', 'modificado': ''}
            self._cache.pop(const.ID_DEFECTO, None)

    def listas(self):
        out = []
        for lid in self.estado['orden']:
            m = self.estado['listas'][lid]
            out.append({'id': lid, 'nombre': m.get('nombre', lid), 'total': m.get('total', 0),
                        'activa': lid == self.estado['activa'], 'origen': m.get('origen', {}),
                        'solo_lectura': bool(m.get('solo_lectura')), 'actualizada': m.get('actualizada', '')})
        return out

    @property
    def id_activa(self):
        return self.estado['activa']

    def cargar(self, lid):
        if lid in self._cache:
            return self._cache[lid]
        datos = leer_json(self._ruta(lid))
        try:
            lista = Lista.desde_dict(datos, id_forzado=lid)
        except (ErrorCatalogo, TypeError, AttributeError) as e:
            if lid == const.ID_DEFECTO:
                self.restaurar_defecto()
                return self.cargar(lid)
            raise ErrorCatalogo('La lista «%s» está dañada: %s' % (lid, e))
        meta = self._meta(lid) or {}
        lista.nombre = meta.get('nombre') or lista.nombre
        for e in lista.entradas:
            e.lista_id, e.lista_nombre = lid, lista.nombre
        self._cache[lid] = lista
        return lista

    def lista_activa(self):
        if self.id_activa == const.ID_TODAS:
            return catalogo.combinar([self.cargar(l) for l in self.estado['orden']])
        return self.cargar(self.id_activa)

    def activar(self, lid):
        if lid != const.ID_TODAS and lid not in self.estado['listas']:
            raise KeyError(lid)
        self.estado['activa'] = lid
        self.guardar_estado()

    def descripcion_origen(self, lid):
        o = (self._meta(lid) or {}).get('origen', {})
        t = o.get('tipo')
        if t == 'empaquetada':
            return 'incluida'
        if t in ('url', 'addons_xml'):
            return dominio(o.get('valor', ''))
        if t == 'archivo':
            return os.path.basename(o.get('valor', ''))
        return 'local'

    def _id_libre(self, nombre):
        base = slug(nombre)
        lid, n = base, 2
        while lid in self.estado['listas'] or lid in (const.ID_TODAS,):
            lid = '%s-%d' % (base, n)
            n += 1
        return lid

    def _registrar(self, lista, nombre, origen, solo_lectura=False, etag='', modificado=''):
        lid = self._id_libre(nombre or lista.nombre)
        lista.id = lid
        if nombre:
            lista.nombre = nombre
        escribir_json(self._ruta(lid), lista.a_dict())
        self.estado['listas'][lid] = {
            'nombre': lista.nombre, 'origen': origen, 'solo_lectura': solo_lectura,
            'total': len(lista.entradas), 'actualizada': ahora_iso(), 'etag': etag or '',
            'modificado': modificado or ''}
        self.estado['orden'].append(lid)
        self.guardar_estado()
        self._cache.pop(lid, None)
        return lid

    def anadir_desde_url(self, url, nombre=None, datadir=None):
        url = red.normalizar_url(url)
        texto, etag, mod = red.get_texto(url)
        lista, origen = self._interpretar(texto, url, nombre, datadir)
        return self._registrar(lista, nombre or lista.nombre, origen, etag=etag, modificado=mod)

    def _interpretar(self, texto, url, nombre=None, datadir=None):
        if texto.lstrip().startswith('<'):
            datadir = datadir or url.rsplit('/', 1)[0] + '/'
            lista = catalogo.desde_addons_xml(texto, datadir, nombre or 'Repositorio de %s' % dominio(url))
            return lista, {'tipo': 'addons_xml', 'valor': url, 'datadir': datadir}
        lista = Lista.desde_json(texto, nombre_defecto=nombre)
        return lista, {'tipo': 'url', 'valor': url}

    def anadir_desde_archivo(self, ruta, nombre=None):
        try:
            with open(ruta, 'r', encoding='utf-8-sig') as f:
                texto = f.read(const.TAM_MAX_LISTA + 1)
        except OSError as e:
            raise ErrorCatalogo('No se pudo leer el archivo: %s' % e)
        if len(texto) > const.TAM_MAX_LISTA:
            raise ErrorCatalogo('El archivo es demasiado grande.')
        lista = Lista.desde_json(texto, nombre_defecto=nombre or os.path.splitext(os.path.basename(ruta))[0])
        return self._registrar(lista, nombre or lista.nombre, {'tipo': 'archivo', 'valor': ruta})

    def crear_vacia(self, nombre):
        lista = Lista.desde_dict({'nombre': nombre, 'addons': []})
        return self._registrar(lista, nombre, {'tipo': 'local'})

    def duplicar(self, lid, nombre):
        origen = copy.deepcopy(leer_json(self._ruta(lid)))
        lista = Lista.desde_dict(origen)
        lista.url_actualizacion = ''
        return self._registrar(lista, nombre, {'tipo': 'local'})

    def _urls_actualizacion(self, lid):
        if lid == const.ID_DEFECTO:
            propia = ajuste('url_catalogo_defecto', '')
            return [propia] if propia else list(const.URLS_DEFECTO)
        o = (self._meta(lid) or {}).get('origen', {})
        return [o['valor']] if o.get('tipo') in ('url', 'addons_xml') and o.get('valor') else []

    def puede_actualizarse(self, lid):
        o = (self._meta(lid) or {}).get('origen', {})
        return bool(self._urls_actualizacion(lid)) or (o.get('tipo') == 'archivo')

    def actualizar(self, lid, forzar=False):
        meta = self._meta(lid)
        if meta is None:
            return 'no_aplica'
        origen = meta.get('origen', {})
        etag = mod = ''
        if origen.get('tipo') == 'archivo':
            try:
                with open(origen['valor'], 'r', encoding='utf-8-sig') as f:
                    texto = f.read(const.TAM_MAX_LISTA + 1)
            except OSError as e:
                raise ErrorCatalogo('No se pudo leer el archivo: %s' % e)
            lista = Lista.desde_json(texto)
        else:
            urls = self._urls_actualizacion(lid)
            if not urls:
                return 'no_aplica'
            texto = None
            ultimo_error = None
            for url in urls:
                try:
                    texto, etag, mod = red.get_texto(
                        url, etag=None if forzar else (meta.get('etag') or None),
                        modificado=None if forzar else (meta.get('modificado') or None))
                    ultimo_error = None
                    break
                except red.ErrorRed as e:
                    ultimo_error = e
            if ultimo_error is not None:
                raise ultimo_error
            meta['actualizada'] = ahora_iso()
            if texto is None:
                self.guardar_estado()
                return 'sin_cambios'
            lista, _ = self._interpretar(texto, url, datadir=origen.get('datadir'))
        if meta.get('renombrada'):
            lista.nombre = meta['nombre']
        elif lid != const.ID_DEFECTO:
            meta['nombre'] = lista.nombre
        lista.id = lid
        escribir_json(self._ruta(lid), lista.a_dict())
        meta.update({'total': len(lista.entradas), 'etag': etag or '', 'modificado': mod or '',
                     'actualizada': ahora_iso()})
        self.guardar_estado()
        self._cache.pop(lid, None)
        return 'actualizada'

    def actualizar_todas(self):
        hechas, errores = 0, []
        for lid in list(self.estado['orden']):
            if not self.puede_actualizarse(lid):
                continue
            try:
                if self.actualizar(lid) == 'actualizada':
                    hechas += 1
            except (red.ErrorRed, ErrorCatalogo) as e:
                errores.append((self._meta(lid).get('nombre', lid), str(e)))
                log('Actualizar lista %s: %s' % (lid, e))
        return hechas, errores

    def pendientes(self, horas):
        import time
        limite = time.time() - horas * 3600
        out = []
        for lid in self.estado['orden']:
            if not self.puede_actualizarse(lid):
                continue
            try:
                t = time.mktime(time.strptime(self._meta(lid).get('actualizada', ''), '%Y-%m-%dT%H:%M:%S'))
            except (ValueError, OverflowError):
                t = 0
            if t < limite:
                out.append(lid)
        return out

    def restaurar_defecto(self):
        self.estado['listas'].pop(const.ID_DEFECTO, None)
        self._cache.pop(const.ID_DEFECTO, None)
        self._asegurar_defecto()
        if const.ID_DEFECTO not in self.estado['orden']:
            self.estado['orden'].insert(0, const.ID_DEFECTO)
        self.guardar_estado()

    def _editable(self, lid):
        m = self._meta(lid)
        if m is None or m.get('solo_lectura'):
            raise ErrorCatalogo('Esta lista es de solo lectura. Duplícala para poder editarla.')

    def renombrar(self, lid, nombre):
        m = self._meta(lid)
        if lid == const.ID_DEFECTO:
            raise ErrorCatalogo('La lista por defecto no se puede renombrar.')
        m['nombre'] = nombre.strip()[:80]
        m['renombrada'] = True
        datos = leer_json(self._ruta(lid))
        datos['nombre'] = m['nombre']
        escribir_json(self._ruta(lid), datos)
        self.guardar_estado()
        self._cache.pop(lid, None)

    def eliminar(self, lid):
        if lid == const.ID_DEFECTO:
            raise ErrorCatalogo('La lista por defecto no se puede eliminar.')
        self.estado['listas'].pop(lid, None)
        self.estado['orden'] = [x for x in self.estado['orden'] if x != lid]
        try:
            os.remove(self._ruta(lid))
        except OSError:
            pass
        if self.estado['activa'] == lid:
            self.estado['activa'] = const.ID_DEFECTO
        self.guardar_estado()
        self._cache.pop(lid, None)

    def anadir_entrada(self, lid, datos):
        self._editable(lid)
        crudo = leer_json(self._ruta(lid))
        previos = [d for d in crudo.get('addons', []) if d.get('id') != datos.get('id')]
        previos.append(datos)
        crudo['addons'] = previos
        nueva = Lista.desde_dict(crudo, id_forzado=lid)
        if nueva.por_id(datos.get('id')) is None:
            raise ErrorCatalogo('; '.join(nueva.avisos[-1:]) or 'Entrada no válida.')
        self._guardar_editada(lid, nueva)

    def quitar_entradas(self, lid, ids):
        self._editable(lid)
        crudo = leer_json(self._ruta(lid))
        crudo['addons'] = [d for d in crudo.get('addons', []) if d.get('id') not in set(ids)]
        self._guardar_editada(lid, Lista.desde_dict(crudo, id_forzado=lid))

    def _guardar_editada(self, lid, lista):
        meta = self._meta(lid)
        lista.nombre = meta['nombre']
        escribir_json(self._ruta(lid), lista.a_dict())
        meta['total'] = len(lista.entradas)
        meta['actualizada'] = ahora_iso()
        self.guardar_estado()
        self._cache.pop(lid, None)

    def exportar(self, lid, ruta):
        datos = leer_json(self._ruta(lid))
        if os.path.isdir(ruta):
            ruta = os.path.join(ruta, '%s.json' % lid)
        escribir_json(ruta, datos)
        return ruta

    def limpiar(self):
        borrar_arbol(const.DIR_TEMP)
        borrar_arbol(const.DIR_CACHE)
