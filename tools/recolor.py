#!/usr/bin/env python3

# STARCONS Recolor Utility
# Created by Mark Steele (SoleDeoGloria), 2026
# For the STARCONS project by CitizenRen
#
# Optional contributor tool for creating and updating colored button sets.
# buttons/Default is treated as the master button set.
# See RECOLOR.md for usage and configuration details.

import argparse
import json
import sys
from pathlib import Path

from PIL import Image


# The utility lives in tools/, one directory below the STARCONS root.
TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent

DEFAULT_SOURCE = REPO_ROOT / "buttons" / "Default"
DEFAULT_CONFIG = TOOL_DIR / "recolor-themes.json"


def normalize_hex(value):
    """Validate and normalize a six-digit RGB hexadecimal color."""
    value = value.strip().lstrip("#")

    if len(value) != 6:
        raise ValueError("Color must be a 6-digit hex value, e.g. #FF1E00")

    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("Color must be a valid hexadecimal value.") from exc

    return f"#{value.upper()}"


def hex_to_rgb(value):
    value = normalize_hex(value)
    raw = value[1:]
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def color_argument(value):
    try:
        return normalize_hex(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def load_config(path):
    """Load and validate the STARCONS theme configuration."""
    if not path.is_file():
        raise RuntimeError(f"Theme configuration not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON in theme configuration: {path}\\n{exc}"
        ) from exc

    if not isinstance(config, dict):
        raise RuntimeError("Theme configuration must contain a JSON object.")

    validated = {}

    for category, themes in config.items():
        if not isinstance(category, str) or not category.strip():
            raise RuntimeError("Theme category names must be non-empty strings.")

        if not isinstance(themes, dict):
            raise RuntimeError(
                f"Theme category '{category}' must contain a JSON object."
            )

        validated[category] = {}

        for name, settings in themes.items():
            if not isinstance(name, str) or not name.strip():
                raise RuntimeError(
                    f"Invalid theme name in category '{category}'."
                )

            if not isinstance(settings, dict):
                raise RuntimeError(
                    f"Theme '{name}' must contain a settings object."
                )

            color = settings.get("color")
            tolerance = settings.get("partial_tolerance", 0)

            if not isinstance(color, str):
                raise RuntimeError(
                    f"Theme '{name}' must define a string color."
                )

            try:
                color = normalize_hex(color)
            except ValueError as exc:
                raise RuntimeError(
                    f"Invalid color for theme '{name}': {color}"
                ) from exc

            if (
                not isinstance(tolerance, int)
                or isinstance(tolerance, bool)
                or tolerance < 0
                or tolerance > 255
            ):
                raise RuntimeError(
                    f"Theme '{name}' partial_tolerance must be "
                    "an integer from 0 through 255."
                )

            validated[category][name] = {
                "color": color,
                "partial_tolerance": tolerance,
            }

    return validated


def save_config(path, config):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\\n")

def create_recolored_image(source, rgb):
    with Image.open(source) as original:
        image = original.convert("RGBA")

    alpha = image.getchannel("A")
    recolored = Image.new("RGBA", image.size, (*rgb, 255))
    recolored.putalpha(alpha)

    return recolored


def images_equal(first, second):
    """Compare two images by exact RGBA pixel content."""
    try:
        with Image.open(second) as existing:
            existing = existing.convert("RGBA")

            if first.size != existing.size:
                return False

            return first.tobytes() == existing.tobytes()

    except (OSError, ValueError):
        return False


def themed_image_is_valid(
    source,
    destination,
    rgb,
    partial_tolerance,
):
    """
    Determine whether existing themed artwork is compatible with the
    configured theme without requiring byte-for-byte generator output.

    Existing artwork is considered valid when:
      * dimensions match the Default master,
      * the alpha mask matches the Default master,
      * fully opaque pixels exactly match the theme RGB,
      * partially transparent pixels remain within the configured
        anti-alias RGB tolerance.

    RGB values beneath fully transparent pixels are ignored.
    """
    try:
        with Image.open(source) as master_image:
            master = master_image.convert("RGBA")

        with Image.open(destination) as themed_image:
            themed = themed_image.convert("RGBA")

    except (OSError, ValueError):
        return False

    if master.size != themed.size:
        return False

    master_bytes = master.tobytes()
    themed_bytes = themed.tobytes()

    for i in range(0, len(master_bytes), 4):
        master_alpha = master_bytes[i + 3]

        themed_red = themed_bytes[i]
        themed_green = themed_bytes[i + 1]
        themed_blue = themed_bytes[i + 2]
        themed_alpha = themed_bytes[i + 3]

        # The themed image must preserve the master's alpha mask.
        if master_alpha != themed_alpha:
            return False

        # RGB beneath complete transparency has no rendered meaning.
        if themed_alpha == 0:
            continue

        deviation = max(
            abs(themed_red - rgb[0]),
            abs(themed_green - rgb[1]),
            abs(themed_blue - rgb[2]),
        )

        # Solid artwork must use the exact configured theme color.
        if themed_alpha == 255:
            if deviation != 0:
                return False

        # Anti-aliased edge pixels may contain the theme's configured
        # amount of RGB variation.
        elif deviation > partial_tolerance:
            return False

    return True


def recolor_png(
    source,
    destination,
    rgb,
    force=False,
    dry_run=False,
    partial_tolerance=None,
):
    recolored = create_recolored_image(source, rgb)

    if destination.exists():
        if not force:
            if partial_tolerance is None:
                valid = images_equal(recolored, destination)
            else:
                valid = themed_image_is_valid(
                    source,
                    destination,
                    rgb,
                    partial_tolerance,
                )

            if valid:
                return "skipped"

        result = "updated"
    else:
        result = "created"

    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        recolored.save(destination, "PNG")

    return result


def source_files(source):
    return sorted(
        path for path in source.iterdir()
        if path.is_file() and path.suffix.lower() == ".png"
    )


def same_path(first, second):
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return False


def generate_theme(
    source,
    destination,
    color,
    force=False,
    dry_run=False,
    partial_tolerance=None,
):
    if same_path(source, destination):
        raise RuntimeError(
            "Destination cannot be the same directory as the source."
        )

    files = source_files(source)

    if not files:
        raise RuntimeError(f"No PNG files found in: {source}")

    rgb = hex_to_rgb(color)

    counts = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    print()
    print(f"Theme:       {destination.name}")
    print(f"Color:       {color}")
    print(f"Destination: {destination}")
    print(f"Dry run:     {'yes' if dry_run else 'no'}")

    for source_file in files:
        destination_file = destination / source_file.name

        try:
            result = recolor_png(
                source_file,
                destination_file,
                rgb,
                force=force,
                dry_run=dry_run,
                partial_tolerance=partial_tolerance,
            )
            counts[result] += 1

            marker = {
                "created": "+",
                "updated": "*",
                "skipped": "=",
            }[result]

            print(f"  {marker} {source_file.name} [{result}]")

        except Exception as exc:
            counts["errors"] += 1
            print(
                f"  ! {source_file.name} [ERROR: {exc}]",
                file=sys.stderr,
            )

    return counts


def merge_counts(total, current):
    for key in total:
        total[key] += current[key]


def print_summary(counts):
    print()
    print("Summary")
    print("-------")
    print(f"Created: {counts['created']}")
    print(f"Updated: {counts['updated']}")
    print(f"Skipped: {counts['skipped']}")
    print(f"Errors:  {counts['errors']}")


def configured_themes(config, category=None):
    themes = []

    for current_category, entries in config.items():
        if category is not None and current_category != category:
            continue

        for name, settings in entries.items():
            themes.append(
                (
                    current_category,
                    name,
                    settings["color"],
                    settings["partial_tolerance"],
                )
            )

    return themes

def color_chit(color):
    """Return a two-character ANSI true-color sample for a hex color."""
    red, green, blue = hex_to_rgb(color)
    return f"\033[38;2;{red};{green};{blue}m██\033[0m"


def print_palette(config):
    print()
    print("Configured themes")
    print("-----------------")

    for category, themes in config.items():
        print(f"{category}:")

        for name, settings in themes.items():
            color = settings["color"]
            tolerance = settings["partial_tolerance"]

            tolerance_text = (
                ""
                if tolerance == 0
                else f"  (AA tolerance ±{tolerance})"
            )

            print(
                f"  {color_chit(color)}  "
                f"{name:<12} {color}{tolerance_text}"
            )

def prompt(text, default=None):
    if default is None:
        return input(f"{text}: ").strip()

    value = input(f"{text} [{default}]: ").strip()
    return value if value else str(default)


def confirm(text, default=True):
    suffix = "[Y/n]" if default else "[y/N]"

    while True:
        value = input(f"{text} {suffix}: ").strip().lower()

        if not value:
            return default

        if value in ("y", "yes"):
            return True

        if value in ("n", "no"):
            return False

        print("Please enter y or n.")


def add_theme_interactive(config, config_path):
    print()
    print("Add a new theme")
    print("---------------")

    existing_categories = list(config.keys())

    print("Existing categories:")
    for category in existing_categories:
        print(f"  {category}")

    category = prompt("Category", "manufacturer").strip()

    if not category:
        print("Theme not added: category cannot be empty.")
        return

    name = prompt("Theme name").strip()

    if not name:
        print("Theme not added: name cannot be empty.")
        return

    for current_category, themes in config.items():
        for existing_name in themes:
            if existing_name.casefold() == name.casefold():
                print(
                    f"Theme not added: '{existing_name}' already exists "
                    f"in category '{current_category}'."
                )
                return

    while True:
        color = prompt("Color (RRGGBB or #RRGGBB)")

        try:
            color = normalize_hex(color)
            break
        except ValueError as exc:
            print(exc)

    print()
    print(f"Category: {category}")
    print(f"Theme:    {name}")
    print(f"Color:    {color}")

    if not confirm("Save this theme?"):
        print("Theme not added.")
        return

    config.setdefault(category, {})
    config[category][name] = {
        "color": color,
        "partial_tolerance": 0,
    }
    save_config(config_path, config)

    print(f"Theme '{name}' added to {config_path.name}.")


def generate_selected_themes(
    source,
    config,
    selection,
    force=False,
    dry_run=False,
):
    if selection == "all":
        themes = configured_themes(config)
    else:
        themes = configured_themes(config, selection)

    if not themes:
        raise RuntimeError(
            f"No themes configured for selection: {selection}"
        )

    totals = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    print()
    print(f"Source: {source}")
    print(f"Themes: {len(themes)}")
    print(f"Force:  {'yes' if force else 'no'}")
    print(f"Dry run: {'yes' if dry_run else 'no'}")

    for _, name, color, tolerance in themes:
        destination = REPO_ROOT / "buttons" / name
        current = generate_theme(
            source,
            destination,
            color,
            force=force,
            dry_run=dry_run,
            partial_tolerance=tolerance,
        )
        merge_counts(totals, current)

    print_summary(totals)

    return totals


def interactive_mode(
    config,
    config_path,
    source,
    force=False,
    dry_run=False,
):
    while True:
        print()
        print("STARCONS Recolor Utility")
        print("========================")
        print(f"Source: {source}")
        print()
        print("1. Generate all configured themes")
        print("2. Generate manufacturer themes")
        print("3. Generate generic color themes")
        print("4. Generate one configured theme")
        print("5. Generate a custom color")
        print("6. Add a new theme")
        print("7. Show configured themes")
        print("8. Exit")

        choice = prompt("Choice", "1")

        if choice == "1":
            if confirm("Generate all configured themes?"):
                generate_selected_themes(
                    source,
                    config,
                    "all",
                    force=force,
                    dry_run=dry_run,
                )

        elif choice == "2":
            if confirm("Generate all manufacturer themes?"):
                generate_selected_themes(
                    source,
                    config,
                    "manufacturer",
                    force=force,
                    dry_run=dry_run,
                )

        elif choice == "3":
            if confirm("Generate all generic color themes?"):
                generate_selected_themes(
                    source,
                    config,
                    "generic",
                    force=force,
                    dry_run=dry_run,
                )

        elif choice == "4":
            themes = configured_themes(config)

            print()
            for index, (
                category,
                name,
                color,
                tolerance,
            ) in enumerate(themes, start=1):
                tolerance_text = (
                    ""
                    if tolerance == 0
                    else f", AA ±{tolerance}"
                )

                print(
                    f"{index:>2}. {color_chit(color)}  "
                    f"{name:<12} {color}  "
                    f"({category}{tolerance_text})"
                )

            selected = prompt("Theme number")

            try:
                index = int(selected) - 1
                category, name, color, tolerance = themes[index]
            except (ValueError, IndexError):
                print("Invalid theme selection.")
                continue

            destination = REPO_ROOT / "buttons" / name
            counts = generate_theme(
                source,
                destination,
                color,
                force=force,
                dry_run=dry_run,
                partial_tolerance=tolerance,
            )
            print_summary(counts)

        elif choice == "5":
            destination_name = prompt("Destination theme/directory name")

            if not destination_name:
                print("Destination name cannot be empty.")
                continue

            while True:
                color = prompt("Color (RRGGBB or #RRGGBB)")

                try:
                    color = normalize_hex(color)
                    break
                except ValueError as exc:
                    print(exc)

            destination = SCRIPT_DIR / "buttons" / destination_name
            counts = generate_theme(
                source,
                destination,
                color,
                force=force,
                dry_run=dry_run,
            )
            print_summary(counts)

        elif choice == "6":
            add_theme_interactive(config, config_path)
            config = load_config(config_path)

        elif choice == "7":
            print_palette(config)

        elif choice == "8":
            print("No changes made.")
            return

        else:
            print("Invalid selection.")


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Generate recolored STARCONS button themes from a master "
            "PNG directory while preserving transparency."
        ),
        epilog=(
            "With no arguments, the utility starts in interactive mode. "
            "The default master source is buttons/Default. "
            "The icons/ and icons/SVG/ collections are never modified."
        ),
    )

    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        help="Directory containing master PNG files",
    )

    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        help="Directory where recolored PNG files will be written",
    )

    parser.add_argument(
        "color",
        nargs="?",
        type=color_argument,
        help='Target color, e.g. "#FF1E00"',
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all themes defined in the configuration file",
    )

    parser.add_argument(
        "--category",
        metavar="NAME",
        help="Generate all themes in one configuration category",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite destination images even when already identical",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing any image files",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=(
            "Theme configuration file "
            "(default: recolor-themes.json beside this script)"
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    config_path = args.config.resolve()

    try:
        config = load_config(config_path)
    except RuntimeError as exc:
        parser.error(str(exc))

    source = (
        args.source.resolve()
        if args.source is not None
        else DEFAULT_SOURCE.resolve()
    )

    if not source.is_dir():
        parser.error(f"Source directory does not exist: {source}")

    positional_count = sum(
        value is not None
        for value in (args.source, args.destination, args.color)
    )

    if positional_count not in (0, 3):
        parser.error(
            "source, destination, and color must either all be supplied "
            "or all be omitted."
        )

    if args.all and args.category:
        parser.error("--all and --category cannot be used together.")

    if positional_count == 3:
        if args.all or args.category:
            parser.error(
                "Direct source/destination/color mode cannot be combined "
                "with --all or --category."
            )

        counts = generate_theme(
            source,
            args.destination.resolve(),
            args.color,
            force=args.force,
            dry_run=args.dry_run,
        )
        print_summary(counts)

        if counts["errors"]:
            sys.exit(1)

        return

    if args.all:
        counts = generate_selected_themes(
            source,
            config,
            "all",
            force=args.force,
            dry_run=args.dry_run,
        )

        if counts["errors"]:
            sys.exit(1)

        return

    if args.category:
        counts = generate_selected_themes(
            source,
            config,
            args.category,
            force=args.force,
            dry_run=args.dry_run,
        )

        if counts["errors"]:
            sys.exit(1)

        return

    interactive_mode(
        config,
        config_path,
        source,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
