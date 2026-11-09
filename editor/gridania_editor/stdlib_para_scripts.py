"""Los scripts de tools/py se descargan y se importan en tiempo de ejecucion; PyInstaller no ve sus imports. Este modulo los declara
para que el .exe incluya toda la biblioteca estandar que usan. No hace nada mas."""
import argparse, array, base64, bisect, bz2, codecs, collections, concurrent.futures, contextlib, copy, csv, ctypes, ctypes.util, datetime, decimal, difflib  # noqa
import fnmatch, functools, gc, glob, gzip, hashlib, heapq, html, importlib, io, itertools, json, logging, lzma, math, multiprocessing, operator, os  # noqa
import pathlib, pickle, platform, queue, random, re, shutil, sqlite3, statistics, string, struct, subprocess, sys, tempfile, textwrap, threading  # noqa
import time, traceback, types, typing, unicodedata, urllib.parse, urllib.request, uuid, zipfile, zlib  # noqa
