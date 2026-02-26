# cja

A [CMake](https://cmake.org)-compatible build system that generates [Ninja](https://ninja-build.org) build files.

Build a project with a `CMakeLists.txt` using:

```sh
cja
ninja
```

This is equivalent to the following with CMake:

```sh
cmake -Bbuild -GNinja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_COLOR_DIAGNOSTICS=1 -DCMAKE_EXPORT_COMPILE_COMMANDS=1
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
  build graph, so tests can start as soon as the first test binary is ready.
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

### `cja build --release`

Equivalent to calling:
```sh
cja -Bbuild-release -DCMAKE_BUILD_TYPE=Release
ninja -f build-release.ninja
```

## Run Subcommand

cja also generates a `run` phony target that executes the first executable (or the one set via
[VS_STARTUP_PROJECT](https://cmake.org/cmake/help/latest/prop_dir/VS_STARTUP_PROJECT.html)) in your `CMakeLists.txt`.
