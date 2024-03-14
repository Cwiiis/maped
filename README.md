# maped

Amstrad CPC (Plus/GX4000) tile map editor

![Screenshot of application](/../doc-assets/screenshot.png?raw=true)

`maped` is a tile map editor specifically targetting the Amstrad CPC Plus. It has built-in support for the standard CPC screen modes and enforces restrictions that make sense given the platform. It is designed to be used in conjunction with an image editor and is most useful for editing existing image maps and assigning and keeping track of map metadata.

## Install and usage

`maped` depends on Python 3, [pytk](https://docs.python.org/3/library/tk.html) (distributed with Python by default on Windows and Mac) and [pypng](https://gitlab.com/drj11/pypng). `pypng` can be installed using `pip`, by running `pip install --user pypng`.

Alternatively, you can run and install `maped` dependencies via [poetry](https://python-poetry.org). You need to have `poetry` [installed in your system](https://python-poetry.org/docs/#installation). Once available, use the following commands:

```bash
# Setup a virtual environment for maped.
# This only needs to be done once.
poetry install

# Run maped
poetry run python maped.py
```

