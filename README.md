# cninja

A CMake reimplementation in Python that generates Ninja build files.

## Usage

```sh
# Configure in current directory
cninja

# Specify build directory
cninja -B build-release

# Set CMake variables
cninja -DCMAKE_BUILD_TYPE=Release
cninja -DCMAKE_BUILD_TYPE=Debug -DENABLE_TESTS=ON
```

After configuration, build with Ninja:

```sh
ninja
```

## Build Subcommand

cninja supports a `build` subcommand that works similar to cargo:

### `cninja build`

Equivalent to calling:
```
cninja -Bbuild
ninja
```

### `cninja build --release`

Equivalent to calling:
```sh
cninja -Bbuild-release -DCMAKE_BUILD_TYPE=Release
ninja -f build-release.ninja
```

## Test Subcommand

### `cninja test`

Equivalent to calling:
```sh
cninja build
ninja -f build.ninja test
```

### `cninja test --release`

Equivalent to calling:
```sh
cninja build --release
ninja -f build-release.ninja test
```

## Run Subcommand

cninja generates a "run" phony target which executes the first executable in your CMakeLists.txt.

### `cninja run`

Equivalent to calling:
```sh
cninja build
ninja -f build.ninja run
```

### `cninja run --release`

Equivalent to calling:
```sh
cninja build --release
ninja -f build-release.ninja run
```

## Supported CMake Commands

### Project Structure
- `cmake_minimum_required(VERSION x.y)`
- `project(name)`
- `add_executable(name sources...)`
- `add_library(name [STATIC|SHARED|OBJECT] sources...)`
- `add_subdirectory(dir)`
- `install(TARGETS targets... [DESTINATION dir])` (defaults to $HOME/.local/bin for TARGETS)

### Variables
- `set(VAR value...)`
- `set(VAR value CACHE TYPE "doc" [FORCE])`
- `option(VAR "description" [ON|OFF])`

### Control Flow
- `if() / elseif() / else() / endif()`
- `foreach() / endforeach()` (with RANGE, IN LISTS, IN ITEMS)

### Target Properties
- `target_link_libraries(target [PUBLIC|PRIVATE|INTERFACE] libs...)`
- `target_sources(target [PUBLIC|PRIVATE|INTERFACE] sources...)`
- `target_compile_features(target [PUBLIC|PRIVATE|INTERFACE] features...)`
- `target_compile_definitions(target [PUBLIC|PRIVATE|INTERFACE] defs...)`
- `target_include_directories(target [PUBLIC|PRIVATE|INTERFACE] [SYSTEM] dirs...)`
- `set_source_files_properties(files... PROPERTIES prop value...)` (supports OBJECT_DEPENDS, INCLUDE_DIRECTORIES, COMPILE_DEFINITIONS)

### Finding Dependencies
- `find_program(VAR name [NAMES ...] [REQUIRED])`
- `find_package(name [REQUIRED])` - supports GTest and Threads via pkg-config

### Testing
- `add_test(NAME name COMMAND cmd args...)` or `add_test(name cmd args...)`
- `include(CTest)` - adds a `test` target (or use `include(module)` for other modules)

### Other
- `message([STATUS|WARNING|FATAL_ERROR] "text")`
- `add_compile_definitions(defs...)`
- `add_compile_options(options...)`
- `add_custom_command(OUTPUT ... COMMAND ... DEPENDS ...)`

## Build Types

Set `CMAKE_BUILD_TYPE` to control optimization:

| Build Type | Flags |
|------------|-------|
| Debug | `-g -O0` |
| Release | `-O3 -DNDEBUG` |
| RelWithDebInfo | `-O2 -g -DNDEBUG` |
| MinSizeRel | `-Os -DNDEBUG` |

## Example

CMakeLists.txt:
```cmake
cmake_minimum_required(VERSION 3.10)
project(myapp)

add_executable(myapp main.cpp)
target_compile_features(myapp PUBLIC cxx_std_17)
```

Build:
```sh
cninja -DCMAKE_BUILD_TYPE=Release
ninja
./build/myapp
```

## Limitations

- Only supports Ninja generator (by design)
- Limited find_package support (GTest, Threads via pkg-config)
- No generator expressions
