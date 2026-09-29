import os
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

HERE = os.path.dirname(os.path.abspath(__file__))


class BuildPy(build_py):
    def run(self):
        super().run()
        built_jw = os.path.join(self.build_lib, "jw")
        if os.path.isdir(built_jw):
            for name in os.listdir(built_jw):
                if name.startswith("test_") and name.endswith(".py"):
                    os.remove(os.path.join(built_jw, name))
        docs = os.path.join(HERE, "docs")
        if not os.path.isfile(os.path.join(docs, "index.html")):
            return
        target = os.path.join(self.build_lib, "jw", "site")
        os.makedirs(target, exist_ok=True)
        shutil.copy2(os.path.join(docs, "index.html"), target)
        assets = os.path.join(docs, "assets")
        if os.path.isdir(assets):
            shutil.copytree(assets, os.path.join(target, "assets"), dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildPy})
