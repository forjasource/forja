import hashlib
import os

DIRS_IGNORADOS = ('__pycache__', '.git', '.github')
NOMBRES_IGNORADOS = ('.DS_Store', 'Thumbs.db')
EXT_IGNORADAS = ('.pyc', '.pyo')


def es_ignorado(nombre, es_dir=False):
    if es_dir:
        return nombre in DIRS_IGNORADOS
    return nombre in NOMBRES_IGNORADOS or nombre.endswith(EXT_IGNORADAS) or nombre.startswith('.git')


def archivos(raiz):
    salida = []
    for base, dirs, nombres in os.walk(raiz):
        dirs[:] = sorted(d for d in dirs if not es_ignorado(d, True))
        for n in sorted(nombres):
            if es_ignorado(n):
                continue
            ruta = os.path.join(base, n)
            salida.append((os.path.relpath(ruta, raiz).replace(os.sep, '/'), ruta))
    salida.sort()
    return salida


def _sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, 'rb') as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b''):
            h.update(bloque)
    return h.hexdigest()


def huella_arbol(raiz):
    lineas = ['%s\t%s' % (rel, _sha256_archivo(ruta)) for rel, ruta in archivos(raiz)]
    return hashlib.sha256('\n'.join(lineas).encode('utf-8')).hexdigest()
