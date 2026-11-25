import os

import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ID = ADDON.getAddonInfo('id')
NOMBRE = ADDON.getAddonInfo('name')
VERSION = ADDON.getAddonInfo('version')
RUTA = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
PERFIL = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

DIR_LISTAS = os.path.join(PERFIL, 'listas')
DIR_COPIAS = os.path.join(PERFIL, 'copias')
DIR_CACHE = os.path.join(PERFIL, 'cache')
ARCHIVO_ESTADO = os.path.join(PERFIL, 'estado.json')

DIR_TEMP = os.path.join(xbmcvfs.translatePath('special://temp'), 'forja')
DIR_ADDONS = xbmcvfs.translatePath('special://home/addons')

ARCHIVO_DEFECTO = os.path.join(RUTA, 'resources', 'data', 'catalogo_defecto.json')

ESQUEMA = 1

URLS_DEFECTO = ('https://forjasource.github.io/addons/addons.json',)
URL_ACTUALIZACION_FORJA = 'https://forjasource.github.io/forja/forja.json'
REV_CATALOGO = 2
ID_DEFECTO = 'defecto'
ID_TODAS = '__todas__'

TAM_MAX_LISTA = 8 * 1024 * 1024
TAM_MAX_ZIP = 700 * 1024 * 1024
TAM_MAX_DESCOMPRIMIDO = 1500 * 1024 * 1024
USER_AGENT = 'Forja/%s (Kodi)' % VERSION

RAMAS_KODI = {19: 'matrix', 20: 'nexus', 21: 'omega', 22: 'piers', 23: 'piers'}
