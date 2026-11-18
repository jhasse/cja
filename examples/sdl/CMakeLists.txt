cmake_minimum_required(VERSION 3.16)
project(sdl_example LANGUAGES C)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
    NAME SDL3
    VERSION 3.4.20
    URL https://github.com/libsdl-org/SDL/releases/download/release-3.4.20/SDL3-3.4.20.tar.gz
    URL_HASH SHA256=f3bb06f55bed9557227a700af2ea62e49497ebdf58037732a731a5fb3ef8581f
    OPTIONS "SDL_SHARED OFF" "SDL_STATIC ON" "SDL_TEST_LIBRARY OFF"
)

add_executable(sdl_example main.c)
target_link_libraries(sdl_example PRIVATE SDL3::SDL3)
