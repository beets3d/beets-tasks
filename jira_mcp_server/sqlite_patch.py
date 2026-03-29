# Use pysqlite3 when system sqlite is older than Django requirement.
import importlib
import sqlite3
import sys


if sqlite3.sqlite_version_info < (3, 31, 0):
    pysqlite3 = importlib.import_module("pysqlite3")
    sys.modules["sqlite3"] = pysqlite3
