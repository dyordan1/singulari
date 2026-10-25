"""Everything a model is shown lives in prompt/ at the repo root: prose as .md,
short lines as .toml, with $name placeholders. This module finds and fills them."""

import os
import string
import tomllib

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompt")


def text(name, **values):
    with open(os.path.join(DIR, name), encoding="utf-8") as f:
        return fill(f.read().removesuffix("\n"), **values)


def lines(name):
    with open(os.path.join(DIR, name), "rb") as f:
        return tomllib.load(f)


def fill(template, **values):
    return string.Template(template).substitute(values)
