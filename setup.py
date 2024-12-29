#!/usr/bin/env python3
import os

from setuptools import setup

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def required(requirements_file):
    """ Read requirements file and remove comments and empty lines. """
    with open(os.path.join(BASEDIR, requirements_file), 'r') as f:
        requirements = f.read().splitlines()
        if 'MYCROFT_LOOSE_REQUIREMENTS' in os.environ:
            print('USING LOOSE REQUIREMENTS!')
            requirements = [r.replace('==', '>=').replace('~=', '>=') for r in requirements]
        return [pkg for pkg in requirements
                if pkg.strip() and not pkg.startswith("#")]


def get_version():
    """ Find the version of the package"""
    version_file = os.path.join(BASEDIR, 'ovos_persona', 'version.py')
    major, minor, build, alpha = (None, None, None, None)
    with open(version_file) as f:
        for line in f:
            if 'VERSION_MAJOR' in line:
                major = line.split('=')[1].strip()
            elif 'VERSION_MINOR' in line:
                minor = line.split('=')[1].strip()
            elif 'VERSION_BUILD' in line:
                build = line.split('=')[1].strip()
            elif 'VERSION_ALPHA' in line:
                alpha = line.split('=')[1].strip()

            if ((major and minor and build and alpha) or
                    '# END_VERSION_BLOCK' in line):
                break
    version = f"{major}.{minor}.{build}"
    if alpha and int(alpha) > 0:
        version += f"a{alpha}"
    return version


PLUGIN_ENTRY_POINT = 'ovos-persona-pipeline-plugin=ovos_persona:PersonaService'
HM_PLUGIN_ENTRY_POINT = 'hivemind-persona-agent-plugin=ovos_persona.hpm:PersonaProtocol'

setup(
    name='ovos-persona',
    version=get_version(),
    description='persona ovos',
    url='https://github.com/OpenVoiceOS/ovos-persona',
    author='jarbasai',
    author_email='jarbasai@mailfence.com',
    license='MIT',
    packages=['ovos_persona'],
    zip_safe=True,
    install_requires=required("requirements.txt"),
    long_description="ovos persona",
    long_description_content_type='text/markdown',
    entry_points={'opm.pipeline': PLUGIN_ENTRY_POINT,
                  'hivemind.agent.protocol': HM_PLUGIN_ENTRY_POINT},
)
