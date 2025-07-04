import os
from setuptools import setup, find_packages

def read_version():
    with open('sqlalchemy_signing/__metadata__.py', 'r') as f:
        lines = f.readlines()

    for line in lines:
        if line.startswith('__version__'):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]

    raise RuntimeError("Unable to find version string.")

version = read_version()

# Read README for long_description
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

requirements_file = os.getenv('REQUIREMENTS', 'requirements/base.txt')

# Read requirements/base.txt for install_requires
with open(requirements_file, encoding="utf-8") as f:
    install_requires = f.read().splitlines()
    
setup(
    name='sqlalchemy_signing',
    version=version,
    url='https://github.com/signebedi/sqlalchemy_signing',
    author='Sig Janoska-Bedi',
    author_email='signe@atreeus.com',
    description='a signing key extension for sqlalchemy',
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    install_requires=install_requires,
    python_requires='>=3.10',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
