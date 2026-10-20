# cja

A [CMake](https://cmake.org)-compatible build system that generates [Ninja](https://ninja-build.org) build files.

Build a project with a `CMakeLists.txt` using:

```sh
cja
ninja
```

This is equivalent to the following with CMake:

```sh
cmake -Bbuild -GNinja -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_COLOR_DIAGNOSTICS=1 -DCMAKE_EXPORT_COMPILE_COMMANDS=1
ninja -Cbuild
```

## Install

```sh
pip install cja
```

Or, if you're in a managed Python environment:

```sh
pipx install cja
```

## Comparison to CMake

* The `build.ninja` file is generated in your project root, not in the build directory. To allow multiple build
  configurations in parallel, the file name is `<builddir>.ninja`.
* Paths are relative to the project root, while CMake uses absolute paths. This is faster, reduces output, and also
  reduces binary size as paths (e.g. for debug symbols) are shorter.
  When reading output from a Docker container, this lets you click paths and open the correct files in your local
  editor.
* Instead of a separate tool like CTest, cja generates a phony `test` target that runs all tests as part of the Ninja
  build graph, so tests can start as soon as the first test binary is ready. Tests run one after another in Ninja's
  console pool; `test-parallel` (or `cja test --parallel`) runs them in parallel instead. Test fixtures
  (`FIXTURES_SETUP`, `FIXTURES_REQUIRED`, `FIXTURES_CLEANUP`) become dependencies between the test targets, so unlike
  CTest a cleanup test doesn't run when a test requiring its fixture fails.
* Colors for compiler diagnostics are enabled by default.
* `_builddir_/compile_commands.json` is always generated.
* More colorful, simplified output. For example, when downloading dependencies, cja shows progress bars using
  [Rich](https://github.com/Textualize/rich), while CMake shows no output (or simple multi-line output when
  `-DFETCHCONTENT_QUIET=0` is specified).

Limitations to keep cja simple:

* Only generates Ninja build files.
* Out-of-tree builds aren't allowed.
* Only supports Linux, macOS, and Windows.
* Only supports clang with a GNU-like command line on Windows.

## Build Subcommand

cja supports a `build` subcommand, which runs `ninja` automatically afterward.

### `cja --release` / `cja build --release`

`cja --release` is equivalent to:
```sh
cja -Bbuild-release -DCMAKE_BUILD_TYPE=Release
```

`cja build --release` additionally runs ninja:
```sh
cja -Bbuild-release -DCMAKE_BUILD_TYPE=Release
ninja -f build-release.ninja
```

### `-B` and `-D`

`cja build`, `cja run` and `cja test` accept `-B` and `-D` like `cja` itself, e.g.
`cja build -Bout -DFOO=1`. `-B` takes precedence over `build-release` from `--release`. Passing `-D`
reconfigures an existing build directory; without it, the existing configuration is kept.

## Run Subcommand

cja also generates a `run` phony target that executes the first executable (or the one set via
[VS_STARTUP_PROJECT](https://cmake.org/cmake/help/latest/prop_dir/VS_STARTUP_PROJECT.html)) in your `CMakeLists.txt`.

## Format Subcommand

`cja format` formats CMake files, similar to [cmake-format](https://github.com/cheshirekow/cmake_format) or
`clang-format`:

```sh
cja format CMakeLists.txt               # print the formatted file
cja format -i CMakeLists.txt foo.cmake  # format files in place
cja format --check CMakeLists.txt       # exit with 1 if the file isn't formatted
cja format -i --lines 10:20 CMakeLists.txt  # only format statements touching lines 10-20
```

Like clang-format's `--lines`, `--lines START:END` (1-based, inclusive, can be repeated) restricts formatting to the
statements that touch these lines or the blank lines before them. Everything else is left byte-for-byte unchanged.

Without file arguments it reads from stdin (use `--assume-filename` to tell it where the file lives).

These options are read from the nearest `.clang-format`:

* `IndentWidth`, `UseTab` and `TabWidth`
* `ColumnLimit` (`0` means no limit)
* `MaxEmptyLinesToKeep`
* `LineEnding`
* `BasedOnStyle` (for the defaults of the options above) and `DisableFormat`

If there's a `.cmake-format.json`, the nearest one overrides them. These options of its `format` section are supported:

* `line_width`, `tab_size` and `use_tabchars`
* `max_subgroups_hwrap`, `max_pargs_hwrap`, `max_rows_cmdline`, `min_prefix_chars`, `max_prefix_chars` and
  `max_lines_hwrap`
* `line_ending`, `command_case` and `disable`

The `parse` section isn't needed: the keywords of custom commands are inferred from their arguments.

Everything else follows cmake-format's defaults, with a few differences:

* A command call that fits on one line is kept on one line, like clang-format does (cmake-format breaks calls with
  more than two argument groups or six arguments). Setting `max_subgroups_hwrap` or `max_pargs_hwrap` in
  `.cmake-format.json` switches to cmake-format's behavior.
* Comments are never reflowed.
* The names of user-defined commands keep their spelling (builtin commands are still lowercased) and UPPERCASE words
  in their arguments are treated as keywords.
* Line endings and a UTF-8 BOM are preserved.

Use `# cmake-format: off` / `# cmake-format: on` (or `# clang-format off` / `on`) to exclude a region.

## LSP Subcommand

`cja lsp` is a [Language Server Protocol](https://microsoft.github.io/language-server-protocol/) server for CMake
files. It talks to the editor over stdin/stdout (`--stdio` is accepted and is the default), so an editor extension
only has to launch `cja lsp --stdio`.

When the editor opens a workspace folder, all `CMakeLists.txt` and `*.cmake` files in it are indexed (build
directories, hidden directories and `_deps` are skipped). The server provides:

* **Semantic highlighting** of commands (builtin, user-defined functions and macros), keywords, variables, function
  parameters, targets, strings, numbers, constants and comments
* **Diagnostics** for syntax errors and unbalanced blocks (`if()` without `endif()` and so on) while typing
* **Go to definition** and **find references** for functions and macros, variables, targets, and the files named by
  `include()` and `add_subdirectory()`
* **Hover** with the definition (and the comment above it) of user-defined commands, variables and targets, and a link
  to the documentation of builtin commands
* **Completion** of command names, of the keywords of the current command, of target names and of variable names
  after `${`
* **Document symbols** (functions, macros, targets, options and the project), **folding** and **formatting** of the
  whole document or of the selected lines (like `cja format` and `cja format --lines`)

Nothing is executed for these. Optionally, the project can also be configured with cja to report the errors and
warnings of a real configure run (e.g. unsupported arguments with `--strict`) as diagnostics. This runs CMake code
from the project (`execute_process()`, downloads with FetchContent, …) and writes the build directory, so it's off by
default. It runs on save with `configureOnSave`, or when the client sends the `cja.configure` command
(`workspace/executeCommand`). These options can be passed as `initializationOptions` or as `cja` settings in
`workspace/didChangeConfiguration`:

| Option            | Default   | Description                                  |
| ----------------- | --------- | -------------------------------------------- |
| `configureOnSave` | `false`   | Configure the project when a file is saved   |
| `buildDir`        | `"build"` | Build directory used for configuring         |
| `strict`          | `true`    | Configure with `--strict`                    |
| `configureArgs`   | `[]`      | Additional arguments, e.g. `["-DFOO=ON"]`    |
