"""Installed entry point for the ReCarted! CLI."""

import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from cyclopts import App

from .convert import convert_image, save_new
from .example import example_image
from .images import RECIPES, identify, read_input

app = App(
    name="recarted",
    help="ReCarted! Atari 8-bit cassette and floppy converter for A8PicoCart.",
    version=version("recarted"),
)


@app.command
def inspect(source: Path) -> None:
    """Identify an image by content and check for a conversion recipe."""
    image = identify(read_input(source))
    print(f"{source.name}: {image.medium}. {image.detail}")
    if image.recipe:
        print(f"Matched: {image.recipe.name}. Output: A8PicoCart type 41 (128 KiB).")
    elif image.medium in ("ATR", "CAS"):
        print("No matching recipe; this revision cannot be converted yet.")


@app.command
def recipes() -> None:
    """List known cassette and disk recipes and their output formats."""
    for recipe in RECIPES:
        formats = (
            "CAR (read-only virtual disk)" if recipe.loader == "disk" else "CAR or XEX"
        )
        print(f"{recipe.medium}  {recipe.name}: {formats}")


@app.command
def convert(source: Path, *, output: Path | None = None) -> None:
    """Convert a supported image. Defaults to a new .car next to the input."""
    image = identify(read_input(source))
    out = output if output is not None else source.with_suffix(".car")
    artifact = convert_image(image, out.suffix.lower().lstrip("."))
    save_new(out, artifact)
    print(f"Created {out} ({len(artifact):,} bytes).")
    if image.recipe and image.recipe.loader == "disk":
        print("The virtual disk is read-only; use the original ATR to save changes.")


@app.command
def example(output: Path) -> None:
    """Create an original colour-bar demo tape (.cas) or disk (.atr) to try."""
    save_new(output, example_image(output.suffix.lower().lstrip(".")))
    print(f"Created {output}. Now run recarted convert on this file.")


@app.command
def test(car: Path, *, os_rom: Path | None = None) -> None:
    """Open a type-41 CAR interactively in Atari800; judge the result on screen."""
    image = identify(read_input(car))
    if image.mapper != 41:
        raise ValueError("test expects a type-41 .car. Convert your input first.")
    emulator = shutil.which("atari800")
    if not emulator:
        raise ValueError(
            "Install Atari800 to use test; conversion does not need an emulator."
        )
    cmd = [emulator, "-no-autosave-config", "-xl", "-pal", "-nobasic", "-nopatchall"]
    if os_rom is not None:
        if not os_rom.is_file() or os_rom.stat().st_size != 16384:
            raise ValueError("Expected a 16 KiB XL/XE OS ROM file.")
        cmd += ["-xlxe_rom", str(os_rom.resolve())]
    print(
        "Starting Atari800; this is an interactive check, not a hardware certification.",
        flush=True,
    )
    result = subprocess.run([*cmd, "-cart", str(car.resolve())], check=False)
    if result.returncode:
        raise ValueError(f"Atari800 exited with status {result.returncode}.")


def main() -> None:
    try:
        app()
    except (ValueError, OSError) as exc:
        print(f"recarted: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
