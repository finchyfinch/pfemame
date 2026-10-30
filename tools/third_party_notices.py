#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# third_party_notices.py

"""
Collect the licences of the third-party software that cx_Freeze bundles into a pfeMAME build.

A frozen build carries the Python runtime and every package pfeMAME uses (wxPython, Pillow, OpenCV, numpy, py7zr ...).
Most of their licences say their copyright notice and licence text must go with any copy, so after each build
tools/setup.py calls write_third_party_licenses(), which:

    - works out which installed packages ended up in the build's lib folder (and lib/library.zip),
    - copies each package's own licence files into <build>/third_party_licenses/,
    - copies Python's own LICENSE.txt (which also covers OpenSSL, libffi, sqlite ... in the Windows runtime),
    - writes THIRD_PARTY_NOTICES.txt listing every package, its version and its licence.

The list is built from what is actually in the build, so it stays right when packages are added or removed.
"""

import os
import re
import shutil
import sys
import sysconfig
import zipfile
from importlib import metadata

FOLDER_NAME = 'third_party_licenses'
NOTICES_FILE = 'THIRD_PARTY_NOTICES.txt'
LICENSE_FILE_PATTERN = re.compile(r'(LICEN[CS]E|COPYING|NOTICE|AUTHORS|COPYRIGHT)', re.IGNORECASE)
OWN_DISTRIBUTIONS = {'pfemame'}


def top_level_names(lib_dir: str) -> set:
    """The top-level module / package names in a cx_Freeze lib folder, including those zipped into library.zip."""
    names = set()
    if not os.path.isdir(lib_dir):
        return names
    for entry in os.listdir(lib_dir):
        names.add(entry.split('.')[0])          # wx, PIL, _cffi_backend.cp314-win_amd64.pyd -> _cffi_backend
    library_zip = os.path.join(lib_dir, 'library.zip')
    if os.path.isfile(library_zip):
        with zipfile.ZipFile(library_zip) as archive:
            for name in archive.namelist():
                names.add(name.split('/')[0].split('.')[0])
    names.discard('')
    return names


def bundled_distributions(lib_dir: str) -> list:
    """The installed distributions (pip packages) that provide modules found in the build, sorted by name."""
    providers = metadata.packages_distributions()
    found = {}
    for name in top_level_names(lib_dir):
        for distribution_name in providers.get(name, []):
            if distribution_name.lower() in OWN_DISTRIBUTIONS:
                continue
            try:
                distribution = metadata.distribution(distribution_name)
            except metadata.PackageNotFoundError:
                continue
            found[distribution.metadata['Name'].lower()] = distribution
    return [found[key] for key in sorted(found)]


def license_name(distribution) -> str:
    """The licence a distribution declares: its SPDX expression, its License field or its licence classifiers."""
    meta = distribution.metadata
    expression = meta.get('License-Expression')
    if expression:
        return expression.strip()
    classifiers = [c.split('::')[-1].strip() for c in meta.get_all('Classifier') or [] if c.startswith('License ::')]
    classifiers = [c for c in classifiers if c not in ('OSI Approved',)]
    declared = (meta.get('License') or '').strip()
    if declared.upper() == 'UNKNOWN':
        declared = ''
    # Some packages paste the whole licence text into the License field - only use it when it is short
    if declared and '\n' not in declared and len(declared) <= 80:
        return declared
    if classifiers:
        return ', '.join(classifiers)
    return 'see the licence files'


def license_files(distribution) -> list:
    """
    Paths of the licence / notice files shipped in a distribution's metadata.  A few packages (pywin32, PyPubSub,
    PyOpenGL ...) keep them inside the package instead, so those are used when the metadata has none.
    """
    in_metadata, in_package = [], []
    for file in distribution.files or []:
        if not LICENSE_FILE_PATTERN.search(file.name) or file.suffix in ('.py', '.pyc', '.pyd', '.so', '.dll'):
            continue
        path = file.locate()
        if not os.path.isfile(path):
            continue
        if any(part.endswith(('.dist-info', '.egg-info')) for part in file.parts):
            in_metadata.append(str(path))
        else:
            in_package.append(str(path))
    return in_metadata or in_package


def python_license_file():
    """Python's own LICENSE.txt, wherever this Python keeps it."""
    candidates = [os.path.join(sys.base_prefix, 'LICENSE.txt'),
                  os.path.join(sysconfig.get_paths()['stdlib'], 'LICENSE.txt'),
                  os.path.join(sys.base_prefix, 'share', 'doc', f'python{sys.version_info.major}.{sys.version_info.minor}',
                               'LICENSE.txt')]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def safe_name(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', text)


def write_third_party_licenses(build_dir: str, lib_dir: str = None) -> list:
    """
    Write <build_dir>/third_party_licenses.  Returns the names of bundled packages for which no licence file could be
    found, so the build can warn about them.
    """
    lib_dir = lib_dir or os.path.join(build_dir, 'lib')
    destination = os.path.join(build_dir, FOLDER_NAME)
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination)

    lines = ['Third-party software included with pfeMAME',
             '=' * 42,
             '',
             'The ready-to-run versions of pfeMAME include the software below.  Each keeps its own licence, which is',
             'not changed by the pfeMAME licence.  The licence files for each one are in this folder.',
             '',
             'MAME is not included.  ffmpeg / ffprobe are not included: pfeMAME uses your own copy if you have one.',
             '',
             f'{"Name":<32} {"Version":<16} Licence',
             f'{"-" * 32} {"-" * 16} {"-" * 40}']

    python_license = python_license_file()
    python_version = sys.version.split()[0]
    if python_license:
        shutil.copyfile(python_license, os.path.join(destination, f'Python-{python_version}-LICENSE.txt'))
    lines.append(f'{"Python":<32} {python_version:<16} PSF-2.0 (the file also lists the libraries in the runtime)')

    missing = []
    for distribution in bundled_distributions(lib_dir):
        name = distribution.metadata['Name']
        version = distribution.version
        copied = []
        for path in license_files(distribution):
            target = f'{safe_name(name)}-{version}-{safe_name(os.path.basename(path))}'
            if target in copied:
                target = f'{safe_name(name)}-{version}-{len(copied)}-{safe_name(os.path.basename(path))}'
            shutil.copyfile(path, os.path.join(destination, target))
            copied.append(target)
        if not copied:
            missing.append(name)
        lines.append(f'{name:<32} {version:<16} {license_name(distribution)}')

    lines += ['',
              'Trademarks: MAME is a registered trademark of Gregory Ember.  PAC-MAN and its characters are trademarks',
              'of Bandai Namco Entertainment Inc.',
              '']
    with open(os.path.join(destination, NOTICES_FILE), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(lines))
    return missing


if __name__ == '__main__':
    # Usage: python tools/third_party_notices.py <build folder>
    not_found = write_third_party_licenses(sys.argv[1] if len(sys.argv) > 1 else 'build')
    if not_found:
        print('No licence file found for: ' + ', '.join(not_found))
