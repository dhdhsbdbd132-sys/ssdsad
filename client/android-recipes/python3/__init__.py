"""Retain Android 7 support with CPython 3.12 and the current NDK."""

from pathlib import Path

from pythonforandroid.recipes.python3 import Python3Recipe


class AndroidPythonRecipe(Python3Recipe):
    def get_recipe_dir(self):
        # Reuse upstream patches rather than duplicating the pinned recipe.
        return str(Path(self.ctx.root_dir) / "recipes" / "python3")

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        if self.ctx.ndk_api < 26:
            # CPython3.12 calls Android's API26-only group enumeration without
            # a feature guard. Its optional Unix grp module is unused here.
            env["py_cv_module_grp"] = "n/a"
        return env


recipe = AndroidPythonRecipe()
